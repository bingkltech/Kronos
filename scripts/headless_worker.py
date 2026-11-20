"""
scripts/headless_worker.py — Kronos Headless Lean 24/7 Production Worker for AWS EC2.

Designed specifically for resource-constrained cloud environments (e.g. AWS t2.micro / t3.micro with 1 GB RAM).
Maintains 100% mathematical and code parity with the local PC orchestrator without the memory overhead
of full-stack browser rendering and TradingView charting assets.

Key Invariants:
1. Zero Float Financial Math (Decimal across all accounting).
2. Base Checkpoint Immutability (Read-only Hugging Face models: NeoQuasar/Kronos-small).
3. Context Slicing Contract (df.iloc[-512:] tail slicing).
4. Mutual Exclusion Guard (Instance tagging: LIVE_AWS_...).
5. Memory Budget (< 350 MB RAM total footprint).
"""

import os
import sys
import time
import json
import signal
import shutil
import subprocess
import logging
import datetime
import threading
from decimal import Decimal
from typing import Optional, Dict, Any, Set, Tuple, List

# Ensure workspace root is in sys.path
WORKSPACE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if WORKSPACE_ROOT not in sys.path:
    sys.path.insert(0, WORKSPACE_ROOT)

import dotenv
dotenv.load_dotenv(os.path.join(WORKSPACE_ROOT, ".env"))

# Set default instance tag to AWS if not specified
if "KRONOS_INSTANCE_TAG" not in os.environ:
    os.environ["KRONOS_INSTANCE_TAG"] = "AWS"

from src.quant.config import ALL_SUPPORTED_SYMBOLS, TOP_10_SYMBOLS, DEFAULT_RISK_CONFIG
from src.quant.orchestrator import QuantBotOrchestrator
from src.quant.apex_scalper import ApexScalperEngine
from src.quant.gemini_strategy_arbiter import GeminiStrategyArbiter
from src.quant.kronos_onnx_engine import KronosTrajectoryEngine
from src.quant.binance_execution import PositionState, TradeTicket, BinanceAtomicExecutor
from src.quant.quota_notifier import QuotaNotifier
from src.quant.anti_bloat import get_anti_bloat_engine
from dataclasses import replace as _dc_replace
from risk_engine import (
    DEFAULT_CONFIG_PATH,
    BinanceExecutorReconciliationAdapter,
    RiskConfig,
    RiskEngine,
    StateReconciler,
    audit_lesson_alignment,
)

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s UTC] [%(levelname)s] [Kronos-Headless] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("KronosHeadless")


def _build_workspace_risk_config() -> RiskConfig:
    cfg = RiskConfig.from_file(DEFAULT_CONFIG_PATH)
    updates: Dict[str, Any] = {}
    for field_name in ("control_file_path", "ledger_db_path", "audit_log_dir"):
        val = getattr(cfg, field_name)
        if val and not os.path.isabs(val):
            updates[field_name] = os.path.join(WORKSPACE_ROOT, val)
    # Enforce portfolio concurrency cap (Max 3 trades total: 2 macro + 1 scalp)
    max_conc = int(os.getenv("KRONOS_MAX_CONCURRENT_POSITIONS", "3"))
    updates["max_concurrent_positions"] = max_conc
    return _dc_replace(cfg, **updates) if updates else cfg


# Instantiate Real-Money Integrity Standard (v3) Sovereign Risk Engine
risk_cfg = _build_workspace_risk_config()
_lesson_report = audit_lesson_alignment(
    risk_cfg, lessons_db_path=os.path.join(WORKSPACE_ROOT, "data", "lessons.db")
)
if _lesson_report.is_aligned:
    logger.info(
        "[RISK-ENGINE] Lesson alignment PASSED (%d/%d lessons mapped, %d structural invariants verified).",
        _lesson_report.mapped_count,
        _lesson_report.total_lessons_in_db,
        _lesson_report.structural_invariants_passed,
    )
else:
    logger.error("[RISK-ENGINE] Lesson alignment warnings/errors: %s", _lesson_report.issues)

executor = BinanceAtomicExecutor(dry_run=False, realistic_friction=True, symbols_config=ALL_SUPPORTED_SYMBOLS)
risk_engine = RiskEngine(
    config=risk_cfg,
    on_cancel_all_orders=lambda reason: (
        logger.critical("[RISK-KILL] Cancelling/purging resting orders: %s", reason),
        executor.purge_orphaned_algo_orders(),
    ),
    on_flatten_all_positions=lambda reason: (
        logger.critical("[RISK-KILL] Flattening all live positions: %s", reason),
        executor.flatten_all_live_positions(),
    ),
)
executor.risk_engine = risk_engine
state_reconciler = StateReconciler(
    adapter=BinanceExecutorReconciliationAdapter(executor),
    config=risk_cfg,
    on_kill_switch=lambda reason: risk_engine.trigger_kill_switch(reason, flatten_positions=True),
)
trajectory_engine = KronosTrajectoryEngine(service_url="", symbols_config=ALL_SUPPORTED_SYMBOLS)
runtime_risk_cfg = _dc_replace(
    DEFAULT_RISK_CONFIG,
    max_concurrent_positions=int(os.getenv("KRONOS_MAX_CONCURRENT_POSITIONS", "3"))
)
quant_bot = QuantBotOrchestrator(
    symbols_config=ALL_SUPPORTED_SYMBOLS,
    risk_config=runtime_risk_cfg,
    executor=executor,
    trajectory_engine=trajectory_engine,
    enable_volume_profile_veto=True,
    require_neural_model=False
)
apex_scalper = ApexScalperEngine(
    symbols_config=ALL_SUPPORTED_SYMBOLS,
    risk_config=runtime_risk_cfg,
    min_score_threshold=Decimal("0.35")
)
gemini_arbiter = GeminiStrategyArbiter()

# Autonomous 24/7 Anti-Bloat & Storage Hygiene Engine
anti_bloat = get_anti_bloat_engine()
anti_bloat.register_cache_pruner("quant_bot_index_engine", quant_bot.index_engine.prune_expired_caches)
anti_bloat.start_daemon(interval_seconds=30.0)

# Operational state & persistent trade-cap auto-pause guard
QUOTA_STATE_PATH = os.path.join(WORKSPACE_ROOT, "data", "aws_trade_quota.json")
quota_mgr = QuotaNotifier(quota_path=QUOTA_STATE_PATH)
running = True
live_trading_enabled = True
raw_trade_cap = os.getenv("KRONOS_LIVE_TRADE_CAP", "50").strip()
live_trade_cap: Optional[int] = int(raw_trade_cap) if raw_trade_cap.isdigit() else 50
live_session_trades: int = 0
live_cap_reached_utc: Optional[datetime.datetime] = None
scan_interval_sec = int(os.getenv("KRONOS_SCAN_INTERVAL", "60"))
last_scan_utc: Optional[datetime.datetime] = None
next_scan_utc: Optional[datetime.datetime] = None
last_cycle_summary: Optional[Dict[str, Any]] = None
previous_live_symbols: set = set()
consecutive_stopouts: int = 0
state_lock = threading.Lock()


def _save_quota_state() -> None:
    try:
        os.makedirs(os.path.dirname(QUOTA_STATE_PATH), exist_ok=True)
        payload = {
            "live_trading_enabled": live_trading_enabled,
            "live_trade_cap": live_trade_cap,
            "live_session_trades": live_session_trades,
            "live_cap_reached_utc": live_cap_reached_utc.isoformat() if live_cap_reached_utc else None,
            "updated_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }
        tmp_path = QUOTA_STATE_PATH + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
        os.replace(tmp_path, QUOTA_STATE_PATH)
    except Exception as e:
        logger.debug("Could not save quota state: %s", e)


def _load_quota_state() -> None:
    global live_trading_enabled, live_trade_cap, live_session_trades, live_cap_reached_utc
    if not os.path.exists(QUOTA_STATE_PATH):
        return
    try:
        with open(QUOTA_STATE_PATH, "r", encoding="utf-8") as f:
            d = json.load(f)
        if "live_trading_enabled" in d:
            live_trading_enabled = bool(d["live_trading_enabled"])
        if "live_trade_cap" in d:
            live_trade_cap = int(d["live_trade_cap"]) if d["live_trade_cap"] is not None else 50
        if "live_session_trades" in d:
            live_session_trades = max(0, int(d["live_session_trades"]))
        if d.get("live_cap_reached_utc"):
            live_cap_reached_utc = datetime.datetime.fromisoformat(d["live_cap_reached_utc"])
        # Safety invariant: if cap already reached, enforce STANDBY_PAUSED
        if live_trade_cap is not None and live_session_trades >= live_trade_cap:
            live_trading_enabled = False
    except Exception as e:
        logger.warning("Could not load quota state: %s", e)


def _record_live_trade_dispatch(symbol: str, source: str) -> None:
    """Increment live session trade counter, auto-pause immediately, and dispatch email when quota is reached."""
    global live_session_trades, live_trading_enabled, live_cap_reached_utc
    with state_lock:
        live_session_trades += 1
        cap_str = f"{live_session_trades}/{live_trade_cap}" if live_trade_cap is not None else f"{live_session_trades}/unlimited"
        logger.info("[LIVE TRADE QUOTA] Dispatched %s (%s) -> Count: %s", symbol, source, cap_str)
        if live_trade_cap is not None and live_session_trades >= live_trade_cap:
            live_trading_enabled = False
            live_cap_reached_utc = datetime.datetime.now(datetime.timezone.utc)
            logger.warning(
                "[AUTO-PAUSE CAP REACHED] %d/%d live trades executed! Switching AWS to STANDBY_PAUSED.",
                live_session_trades,
                live_trade_cap,
            )
            try:
                fresh_summary = quant_bot.executor.get_live_account_summary()
                quota_mgr.session_trades = live_session_trades
                quota_mgr.trade_cap = live_trade_cap
                quota_mgr.is_active = False
                quota_mgr.cap_reached_utc = live_cap_reached_utc
                quota_mgr.dispatch_completion_email(account_summary=fresh_summary)
            except Exception as mail_err:
                logger.error("[EMAIL NOTIFICATION ERROR] %s", mail_err)
        _save_quota_state()


def _has_trade_quota_remaining() -> bool:
    if live_trade_cap is None:
        return True
    return live_session_trades < live_trade_cap


_load_quota_state()


def execute_live_cycle():
    """Execute full market breadth and candidate evaluation with real Binance execution."""
    global last_scan_utc, next_scan_utc, last_cycle_summary
    now_u = datetime.datetime.now(datetime.timezone.utc)
    logger.info("Executing autonomous market scan cycle...")

    live_summary = quant_bot.executor.get_live_account_summary()
    if not live_summary.get("connected"):
        logger.warning("Binance connection unavailable: %s", live_summary.get("error"))
        return

    # Refresh Layer-3 Cancel-on-Disconnect heartbeat & Layer-4 State Reconciliation
    risk_engine.record_gateway_heartbeat()
    try:
        from risk_engine import PositionSnapshot, OrderSide
        internal_pos_map = {
            pos.symbol: PositionSnapshot(
                symbol=pos.symbol,
                side=OrderSide.coerce(pos.side),
                quantity=pos.quantity,
                entry_price=pos.entry_price,
                mark_price=pos.entry_price,
                stop_loss=pos.stop_loss,
            )
            for pos in quant_bot.executor.active_positions.values()
            if pos.state == PositionState.BRACKETS_ACTIVE
        }
        # Only flag phantoms when local tracking is populated (avoid false flatten on cold restart adopting live positions)
        if internal_pos_map:
            rec_report = state_reconciler.reconcile_once(internal_pos_map)
            if not rec_report.is_synchronized:
                logger.warning("[RISK-RECONCILER] Discrepancies resolved: %s", rec_report.actions_taken)
    except Exception as rec_err:
        logger.warning("Layer-4 StateReconciler warning: %s", rec_err)

    equity = live_summary.get("total_wallet_balance_usd", Decimal("0.00"))
    if equity <= Decimal("0"):
        equity = quant_bot.risk_config.small_account_threshold

    # Auto-reconcile and purge dangling/orphaned algo orders on Binance
    try:
        purged = quant_bot.executor.purge_orphaned_algo_orders()
        if purged:
            logger.info("Auto-purged orphaned algo orders: %s", purged)
    except Exception as e:
        logger.warning("Error running purge_orphaned_algo_orders: %s", e)

    # Active Position Oversight via CapitalRecycler (Lesson #41)
    try:
        from src.quant.capital_recycler import CapitalRecycler
        recycler = CapitalRecycler()
        active_positions = live_summary.get("positions", [])
        for pos in active_positions:
            sym = pos.get("symbol")
            entry_px = Decimal(str(pos.get("entry_price", "0")))
            curr_px = Decimal(str(pos.get("mark_price", entry_px)))
            eval_res = recycler.evaluate(pos, current_price=curr_px, current_time_utc=now_u, is_tsunami_shock=False)
            if eval_res.should_exit:
                logger.info("[CAPITAL RECYCLER] Strategy #1 position %s dead/stalled: %s. Executing Move-On...", sym, eval_res.action_reason)
                recycler.execute_move_on(
                    pos, eval_res, current_price=curr_px, current_time_utc=now_u,
                    binance_client=quant_bot.executor, quarantine_registry=quant_bot.symbol_cooldowns,
                    on_slot_liberated=lambda pid, s: logger.info("[SLOT LIBERATED] Capital Recycler freed macro slot from %s for fresh breakout.", s)
                )
    except Exception as rec_err:
        logger.warning("Error running CapitalRecycler on active positions: %s", rec_err)

    # Fetch lookbacks
    lookbacks = {}
    for sym in list(ALL_SUPPORTED_SYMBOLS.keys())[:5]:
        try:
            live_df = quant_bot.index_engine.fetch_lookback_dataframe(sym, limit=100)
            if live_df is not None and len(live_df) >= 20:
                lookbacks[sym] = live_df
        except Exception as e:
            logger.debug("Lookback fetch error for %s: %s", sym, e)

    if not live_trading_enabled or not _has_trade_quota_remaining():
        return

    # Concurrency and dedicated strategy allocation gates (2 trades max: 1 Macro + 1 Scalp)
    active_positions = live_summary.get("positions", [])
    active_symbols = [p.get("symbol") for p in active_positions if p.get("symbol")]
    scalp_active_symbols = quant_bot.executor.scalp_active_symbols
    macro_positions = [
        p for p in active_positions
        if p.get("symbol") not in scalp_active_symbols
    ]

    # Global Concurrency Clamp: Max 3 positions total across entire portfolio
    max_portfolio_positions = int(os.getenv("KRONOS_MAX_CONCURRENT_POSITIONS", "3"))
    if len(active_positions) >= max_portfolio_positions:
        logger.info(
            "[PORTFOLIO CONCURRENCY] Maximum concurrent positions held (%d/%d: %s). Holding.",
            len(active_positions),
            max_portfolio_positions,
            active_symbols
        )
        return

    # Dedicated Strategy Allocation: Strictly max 2 Macro trades (3 total: 2 Macro + 1 Scalp)
    max_macro_positions = int(os.getenv("KRONOS_MAX_MACRO_POSITIONS", "2"))
    if len(macro_positions) >= max_macro_positions:
        logger.info(
            "[STRATEGY ALLOCATION] Macro slots full (%d/%d occupied: %s). Holding for exit before new macro entry.",
            len(macro_positions),
            max_macro_positions,
            [p.get("symbol") for p in macro_positions]
        )
        return

    remaining_quota = (live_trade_cap - live_session_trades) if live_trade_cap is not None else 1
    macro_available = max_macro_positions - len(macro_positions)
    portfolio_available = max_portfolio_positions - len(active_positions)
    macro_entry_cap = min(remaining_quota, macro_available, portfolio_available)
    report = quant_bot.run_scan_cycle(
        account_equity=equity,
        lookback_data_map=lookbacks if lookbacks else None,
        execution_mode="LIVE",
        max_new_entries=macro_entry_cap
    )

    last_scan_utc = report.timestamp_utc
    next_scan_utc = now_u + datetime.timedelta(seconds=scan_interval_sec)

    for p in report.dispatched_trades:
        _record_live_trade_dispatch(p.symbol, "MACRO")

    dispatched = [p.symbol for p in report.dispatched_trades]
    logger.info(
        "Scan cycle complete. Regime: %s | Breadth: %.1f%% | Evaluated: %d | Dispatched: %s",
        report.macro_verdict.macro_regime,
        float(report.macro_verdict.breadth_ratio) * 100,
        len(report.decisions),
        dispatched if dispatched else "None (Veto gates held)"
    )

    with state_lock:
        fresh_account = quant_bot.executor.get_live_account_summary()
        last_cycle_summary = {
            "success": True,
            "timestamp": report.timestamp_utc.isoformat(),
            "macro_regime": report.macro_verdict.macro_regime,
            "breadth_pct": f"{float(report.macro_verdict.breadth_ratio)*100:.1f}%",
            "evaluated_count": len(report.decisions),
            "dispatched_count": len(report.dispatched_trades),
            "dispatched_trades": [
                {
                    "symbol": p.symbol,
                    "side": p.side,
                    "entry_price": float(p.entry_price),
                    "quantity": float(p.quantity)
                }
                for p in report.dispatched_trades
            ],
            "live_account": {
                "total_wallet_balance_usd": float(fresh_account.get("total_wallet_balance_usd", Decimal("0.00"))),
                "available_balance_usd": float(fresh_account.get("available_balance_usd", Decimal("0.00"))),
                "unrealized_pnl_usd": float(fresh_account.get("unrealized_pnl_usd", Decimal("0.00"))),
                "margin_ratio_pct": float(fresh_account.get("margin_ratio_pct", Decimal("0.00"))),
                "active_positions": fresh_account.get("positions", [])
            }
        }


SCALPER_CONFIG_PATH = os.path.join(WORKSPACE_ROOT, "data", "scalper_config.json")


def load_scalper_config() -> Dict[str, Any]:
    if os.path.exists(SCALPER_CONFIG_PATH):
        try:
            with open(SCALPER_CONFIG_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.debug("Failed reading scalper_config.json: %s", e)
    return {}


def _get_tiger_reserved_symbols() -> Set[str]:
    """
    Deconfliction Guard: Identifies symbols currently actively held, hunted, or cooling down
    by Stalking Tiger (Strategy #3) or reserved in RiskLedger.
    Guarantees Apex Scalper and Stalking Tiger never collide on the same asset.
    """
    reserved: Set[str] = set()

    # 1. Inspect Tiger State (active positions, pending breakout signals, cooldowns)
    data_dir = os.path.join(WORKSPACE_ROOT, "data")
    for sp in [
        os.path.join(data_dir, "tiger_state.json"),
        "/home/ec2-user/kronos-bot/data/tiger_state.json",
        "/home/ec2-user/data/tiger_state.json",
    ]:
        if os.path.exists(sp):
            try:
                with open(sp, "r", encoding="utf-8") as f:
                    t_state = json.load(f)
                for pos in t_state.get("active_positions", {}).values():
                    sym = pos.get("symbol")
                    if sym:
                        reserved.add(sym.strip().upper())
                for sig in t_state.get("pending_signals", {}).values():
                    sym = sig.get("symbol")
                    if sym:
                        reserved.add(sym.strip().upper())
                now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
                for sym, cd_exp in t_state.get("symbol_cooldowns", {}).items():
                    if cd_exp and cd_exp > now_iso:
                        reserved.add(sym.strip().upper())
                break
            except Exception:
                pass

    # 2. Inspect RiskLedger Atomic Reservations
    if hasattr(risk_engine, "ledger") and risk_engine.ledger is not None:
        try:
            active_res = risk_engine.ledger.active_reservations()
            for r in active_res:
                sym = r.get("symbol")
                if sym:
                    reserved.add(sym.strip().upper())
        except Exception:
            pass

    return reserved


def execute_apex_scalp_step():
    """High-frequency 5s order book screening and position management."""
    scalper_cfg = load_scalper_config()
    if scalper_cfg.get("enabled") is False:
        return

    now_utc = datetime.datetime.now(datetime.timezone.utc)
    exec_targets = scalper_cfg.get("execution_targets", {})
    guardrails = scalper_cfg.get("guardrails", {})

    max_duration_sec = int(exec_targets.get("max_duration_seconds", 600))
    ratchet_trigger_pct = Decimal(str(exec_targets.get("fast_profit_ratchet_pct", "0.80")))
    ringfenced_margin = Decimal(str(guardrails.get("ringfenced_margin_usd", "20.00")))

    # 1. Active scalp management
    if not apex_scalper.is_slot_available and apex_scalper.active_scalp:
        pos = apex_scalper.active_scalp
        try:
            klines = quant_bot.index_engine.fetch_recent_klines(pos.symbol, limit=2)
            if klines:
                curr_price = klines[-1]["close"]
                apex_scalper.update_in_trade_path(curr_price)

                duration_sec = int((now_utc - pos.entry_time_utc).total_seconds())
                if pos.side == "BUY":
                    unrealized_return_pct = ((curr_price - pos.entry_price) / pos.entry_price) * Decimal("100")
                else:
                    unrealized_return_pct = ((pos.entry_price - curr_price) / pos.entry_price) * Decimal("100")

                cfg = ALL_SUPPORTED_SYMBOLS.get(pos.symbol)
                friction_pct = (cfg.round_trip_taker_friction() * Decimal("100")) if cfg else Decimal("0.10")
                net_unrealized_pct = unrealized_return_pct - friction_pct

                # Institutional Two-Tier Ratchet: trail once >= +0.80% net expansion
                ratchet_triggered, new_sl = apex_scalper.evaluate_ratchet(
                    curr_price=curr_price,
                    expansion_threshold_pct=ratchet_trigger_pct,
                    profit_lock_pct=Decimal("0.25")
                )
                if ratchet_triggered and new_sl:
                    logger.info("Apex Scalp Ratchet Triggered: %s SL moved to %.4f", pos.symbol, float(new_sl))

                hit_tp = (pos.side == "BUY" and curr_price >= pos.take_profit) or (pos.side == "SELL" and curr_price <= pos.take_profit)
                hit_sl = (pos.side == "BUY" and curr_price <= pos.stop_loss) or (pos.side == "SELL" and curr_price >= pos.stop_loss)
                timed_out = duration_sec >= max_duration_sec
                is_stalled, stall_reason = apex_scalper.evaluate_stagnation(now_utc)

                if hit_tp or hit_sl or timed_out or is_stalled:
                    reason = "TAKE_PROFIT_HIT" if hit_tp else ("STOP_LOSS_HIT" if hit_sl else ("STAGNATION_EXPIRATION" if is_stalled else "TIME_EXPIRATION"))
                    fee_usd = pos.notional_usd * (friction_pct / Decimal("100"))

                    # Cancel algo orders and flatten if necessary
                    try:
                        quant_bot.executor._signed_request("DELETE", "/fapi/v1/algoOpenOrders", {"symbol": pos.symbol})
                    except Exception:
                        pass
                    if reason in ("TIME_EXPIRATION", "STAGNATION_EXPIRATION", "STOP_LOSS_HIT"):
                        try:
                            flat_side = "SELL" if pos.side == "BUY" else "BUY"
                            quant_bot.executor._signed_request("POST", "/fapi/v1/order", {
                                "symbol": pos.symbol,
                                "side": flat_side,
                                "type": "MARKET",
                                "quantity": str(pos.quantity),
                                "reduceOnly": "true"
                            })
                        except Exception as e:
                            logger.warning("Scalp market flatten error: %s", e)

                    telemetry = apex_scalper.close_scalp(
                        exit_price=curr_price,
                        close_reason=reason,
                        current_time_utc=now_utc,
                        exchange_fees_usd=fee_usd,
                        trade_mode="LIVE"
                    )
                    try:
                        from src.quant.scalper_distillation import ScalperDistillationEngine
                        ScalperDistillationEngine().record_scalp_forensic(telemetry)
                    except Exception as fe:
                        logger.debug("Failed saving scalp forensic: %s", fe)
                    quant_bot.executor.scalp_active_symbols.discard(pos.symbol)
                    logger.info("Apex Scalp Closed: %s (%s) Net Return: %.2f%% PnL: $%.2f", pos.symbol, reason, float(net_unrealized_pct), float(telemetry.net_pnl_usd))
                    global consecutive_stopouts
                    if reason == "STOP_LOSS_HIT":
                        consecutive_stopouts += 1
                        logger.info("Consecutive stop-outs: %d / 5", consecutive_stopouts)
                    elif reason == "TAKE_PROFIT_HIT":
                        consecutive_stopouts = 0
        except Exception as e:
            logger.debug("Apex Scalper Monitor: %s", e)
        return

    # 2. Slot is free: screen for top candidate
    try:
        live_acc = quant_bot.executor.get_live_account_summary()
        available_cash = Decimal(str(live_acc.get("available_balance_usd", "0.00")))
        if available_cash < Decimal("10.00"):
            return

        active_symbols = {p.get("symbol") for p in live_acc.get("positions", [])}

        # Global Concurrency Clamp: Max 3 positions total across portfolio
        max_portfolio_positions = int(os.getenv("KRONOS_MAX_CONCURRENT_POSITIONS", "3"))
        if len(active_symbols) >= max_portfolio_positions:
            return

        # Dedicated Strategy Allocation: Strictly 1 Scalp trade
        scalp_active_symbols = quant_bot.executor.scalp_active_symbols
        active_scalps = active_symbols.intersection(scalp_active_symbols)
        if len(active_scalps) >= 1 or not apex_scalper.is_slot_available:
            return

        # Dynamic Post-Exit Quarantine Reflex:
        # Detect any position that was active in the previous check and has now been closed/exited
        # (e.g. owner manually took profit on BTC/ETH on Binance, or exchange algo bracket triggered)
        global previous_live_symbols
        if previous_live_symbols:
            exited_symbols = previous_live_symbols - active_symbols
            for exited_sym in exited_symbols:
                if not apex_scalper.is_symbol_in_cooldown(exited_sym, now_utc):
                    apex_scalper.register_symbol_cooldown(
                        symbol=exited_sym,
                        current_time_utc=now_utc,
                        duration_seconds=900,
                        reason="MANUAL_OR_EXCHANGE_EXIT"
                    )
                    quant_bot.register_symbol_cooldown(
                        symbol=exited_sym,
                        current_time_utc=now_utc,
                        duration_seconds=900,
                        reason="MANUAL_OR_EXCHANGE_EXIT"
                    )
                    logger.info(
                        "[COOLDOWN] Position on %s closed/exited (manual or exchange fill). 15-minute post-exit quarantine activated to prevent churn & mean-reversion whipsaw.",
                        exited_sym
                    )
        previous_live_symbols = active_symbols

        quarantined_symbols = set(guardrails.get("quarantined_symbols", []))
        cooldown_dur = int(guardrails.get("post_exit_cooldown_seconds", 900))
        apex_scalper.cooldown_seconds = cooldown_dur

        # 1. Deconfliction & Candidate Eligibility Filter
        tiger_reserved = _get_tiger_reserved_symbols()
        eligible_symbols = []
        for sym in list(ALL_SUPPORTED_SYMBOLS.keys()):
            # Skip if currently holding on exchange
            if sym in active_symbols:
                continue
            # Skip if quarantined by Bayesian learning distillation
            if sym in quarantined_symbols:
                continue
            # Skip if Stalking Tiger is currently holding or hunting this symbol
            if sym in tiger_reserved:
                continue
            # Skip if in post-exit quarantine cooldown
            if apex_scalper.is_symbol_in_cooldown(sym, now_utc):
                continue
            eligible_symbols.append(sym)

        # 2. Parallel Batch Data Fetch (Candle-boundary TTL + 0ms WS Depth / Cached REST)
        batch_market_data = quant_bot.index_engine.batch_fetch_scalp_market_data(
            symbols=eligible_symbols,
            interval="5m",
            kline_limit=24,
            depth_limit=10
        )

        # 3. Microstructure Candidate Evaluation
        candidates = []
        for sym in eligible_symbols:
            if sym not in batch_market_data:
                continue
            klines, micro_data = batch_market_data[sym]
            if not klines or len(klines) < 12:
                continue
            if micro_data.best_bid <= Decimal("0") or micro_data.best_ask <= Decimal("0"):
                continue

            # Reference mid-price directly from live orderbook, fallback to last kline close
            curr_p = ((micro_data.best_bid + micro_data.best_ask) / Decimal("2")) if (micro_data.best_bid > Decimal("0") and micro_data.best_ask > Decimal("0")) else klines[-1]["close"]
            vp_snapshot = quant_bot.volume_profile_cache.get_previous_day_profile(sym, now_utc)

            cand = apex_scalper.evaluate_microstructure_candidate(
                symbol=sym,
                current_price=curr_p,
                best_bid=micro_data.best_bid,
                best_ask=micro_data.best_ask,
                order_book_imbalance=micro_data.obi,
                recent_klines=klines,
                bnb_discount=True,
                micro_skew_bps=micro_data.micro_skew_bps,
                micro_price=micro_data.micro_price,
                current_time_utc=now_utc,
                volume_profile=vp_snapshot
            )
            if cand:
                candidates.append(cand)

        apex = apex_scalper.select_apex_candidate(candidates)
        if apex:
            # Tsunami Storm Protocol Gate
            try:
                from src.quant.storm_protocol import StormProtocolManager
                storm_mgr = StormProtocolManager(normal_macro_cap=2, normal_scalp_cap=1)
                btc_cand_klines = quant_bot.index_engine.fetch_recent_klines("BTCUSDT", interval="5m", limit=3)
                storm_mgr.evaluate_market_wave(
                    btc_klines=btc_cand_klines,
                    recent_stopouts=consecutive_stopouts,
                    current_time_utc=now_utc
                )

                macro_count = len(active_symbols - quant_bot.executor.scalp_active_symbols)
                scalp_count = len(quant_bot.executor.scalp_active_symbols)
                score_pct = float(apex.score * Decimal("100")) if hasattr(apex, "score") else 70.0
                permitted, storm_reason = storm_mgr.is_entry_permitted(
                    is_scalp=True,
                    current_macro_count=macro_count,
                    current_scalp_count=scalp_count,
                    confidence_pct=score_pct,
                    current_time_utc=now_utc
                )
                if not permitted:
                    logger.info("Apex scalp blocked by Storm Protocol: %s", storm_reason)
                    return
            except Exception as se:
                logger.debug("Storm protocol check: %s", se)

            if not live_trading_enabled or not _has_trade_quota_remaining():
                return

            pos_id = f"SCALP-{now_utc.strftime('%H%M%S')}"
            margin_budget = min(ringfenced_margin, available_cash)
            new_pos = apex_scalper.open_scalp(apex, account_equity=margin_budget, position_id=pos_id, current_time_utc=now_utc, available_balance_usd=margin_budget)
            if new_pos:
                ticket = TradeTicket(
                    symbol=apex.symbol,
                    side="BUY" if apex.side in ("BUY", "LONG") else "SELL",
                    entry_price=apex.entry_price,
                    stop_loss=apex.stop_loss,
                    take_profit=apex.take_profit,
                    quantity=new_pos.quantity,
                    notional_usd=new_pos.notional_usd,
                    effective_leverage=new_pos.leverage,
                    risk_budget_usd=new_pos.initial_margin_usd,
                    reward_risk_ratio=apex.reward_risk_ratio,
                    net_expected_gain_pct=apex.expected_net_drift_pct,
                    is_scalp=True
                )
                p_state, m_snap = quant_bot.executor.fetch_live_risk_snapshots(
                    symbol=ticket.symbol,
                    fallback_price=ticket.entry_price,
                    realized_vol=(apex.atr_5m / apex.entry_price) if apex.entry_price > Decimal("0") else Decimal("0.015"),
                    atr_pct=(apex.atr_5m / apex.entry_price) if apex.entry_price > Decimal("0") else None,
                    live_summary=live_summary,
                )
                live_res = quant_bot.executor.submit_live_bracket_order(
                    ticket,
                    portfolio_state=p_state,
                    market_snapshot=m_snap,
                )
                if live_res.state == PositionState.REJECTED:
                    logger.warning("Apex scalp entry rejected: %s", live_res.close_reason)
                    apex_scalper.active_scalp = None
                    return
                if live_res.entry_order_id:
                    quant_bot.executor.record_scalp_order(live_res.entry_order_id)
                if live_res.take_profit_order_id:
                    quant_bot.executor.record_scalp_order(live_res.take_profit_order_id)
                if live_res.stop_loss_order_id:
                    quant_bot.executor.record_scalp_order(live_res.stop_loss_order_id)
                logger.info("Apex Scalp Dispatched: %s (%s) Lev: %dx Notional: $%.2f", apex.symbol, apex.side, new_pos.leverage, float(new_pos.notional_usd))
                _record_live_trade_dispatch(apex.symbol, "SCALP")
    except Exception as e:
        logger.debug("Apex scalper cycle: %s", e)


def check_system_antibloat():
    """Safety watchdog to prevent disk exhaustion and runaway log growth."""
    try:
        total, used, free = shutil.disk_usage("/")
        free_mb = free / (1024 * 1024)
        if free_mb < 600:
            logger.warning("[WATCHDOG-ALERT] Low disk space detected (%.1f MB free). Triggering emergency anti-bloat pass...", free_mb)
            antibloat_script = os.path.join(WORKSPACE_ROOT, "scripts", "auto_antibloat.sh")
            if os.path.isfile(antibloat_script):
                res = subprocess.run(["bash", antibloat_script], capture_output=True, text=True, timeout=30)
                logger.info("[WATCHDOG] Emergency anti-bloat pass executed: rc=%s", res.returncode)
    except Exception as e:
        logger.debug("Disk health watchdog check: %s", e)


def daemon_loop():
    """Main background loop coordinating macro cycles and high-frequency scalping."""
    logger.info("Background daemon active. Main scan every %ds, scalper tick every 5s.", scan_interval_sec)
    last_macro_time = 0.0
    last_antibloat_check = time.time()

    # Initial pre-flight check
    check_system_antibloat()

    while running:
        now_ts = time.time()

        # Routine health & disk bloat watchdog check every 30 minutes
        if now_ts - last_antibloat_check >= 1800:
            check_system_antibloat()
            last_antibloat_check = time.time()

        # Refresh Layer-3 Cancel-on-Disconnect heartbeat continuously on every daemon tick
        try:
            risk_engine.record_gateway_heartbeat()
        except Exception as hb_err:
            logger.debug("Heartbeat record error: %s", hb_err)

        if live_trading_enabled:
            # High-frequency scalper step
            try:
                execute_apex_scalp_step()
            except Exception as e:
                logger.debug("Scalper step exception: %s", e)

            # Macro scan cycle
            if now_ts - last_macro_time >= scan_interval_sec:
                try:
                    execute_live_cycle()
                    last_macro_time = time.time()
                except Exception as e:
                    logger.warning("Macro cycle exception: %s", e)

        time.sleep(5)


# ==============================================================================
# Ultra-Lean Lightweight Micro-Flask API (< 15 MB RAM overhead)
# ==============================================================================
from flask import Flask, jsonify, request

app = Flask(__name__)

# Suppress Flask request logs from spamming stdout
logging.getLogger("werkzeug").setLevel(logging.ERROR)

@app.route('/api/health', methods=['GET'])
def health():
    return jsonify({
        "status": "ok",
        "instance_tag": os.getenv("KRONOS_INSTANCE_TAG", "AWS"),
        "live_trading_enabled": live_trading_enabled,
        "bot_state": "ACTIVE" if live_trading_enabled else "STANDBY_PAUSED",
        "timestamp_utc": datetime.datetime.now(datetime.timezone.utc).isoformat()
    })

@app.route('/api/live/status', methods=['GET'])
def live_status():
    live_account = quant_bot.executor.get_live_account_summary()
    next_sec = 0
    if next_scan_utc:
        now_u = datetime.datetime.now(datetime.timezone.utc)
        next_sec = max(0, int((next_scan_utc - now_u).total_seconds()))

    return jsonify({
        "success": True,
        "connected": live_account.get("connected", False),
        "error": live_account.get("error"),
        "bot_state": "ACTIVE" if live_trading_enabled else "STANDBY_PAUSED",
        "execution_mode": "REAL LIVE TRADING (BINANCE FUTURES)",
        "distributed_guard": {
            "instance_tag": os.getenv("KRONOS_INSTANCE_TAG", "AWS"),
            "coordinator_url": "",
            "remote_cloud_active": False,
            "role": "ACTIVE_PRIMARY",
            "message": "AWS Cloud Instance is ACTIVE_PRIMARY"
        },
        "mutual_exclusion": {
            "live_trading_active": live_trading_enabled,
            "paper_trading_paused": True,
            "passive_observer": False
        },
        "live_account": {
            "total_wallet_balance_usd": float(live_account.get("total_wallet_balance_usd", Decimal("0.00"))),
            "available_balance_usd": float(live_account.get("available_balance_usd", Decimal("0.00"))),
            "unrealized_pnl_usd": float(live_account.get("unrealized_pnl_usd", Decimal("0.00"))),
            "margin_ratio_pct": float(live_account.get("margin_ratio_pct", Decimal("0.00"))),
            "bnb_balance": float(live_account.get("bnb_balance", Decimal("0.00"))),
            "bnb_fee_discount_active": bool(live_account.get("bnb_fee_discount_active", False)),
            "active_positions_count": len(live_account.get("positions", [])),
            "positions": live_account.get("positions", [])
        },
        "autopilot": {
            "enabled": live_trading_enabled,
            "interval_seconds": scan_interval_sec,
            "last_scan_utc": last_scan_utc.isoformat() if last_scan_utc else None,
            "next_scan_seconds": next_sec
        },
        "trade_quota": {
            "trade_cap": live_trade_cap,
            "session_trades": live_session_trades,
            "trades_remaining": max(0, live_trade_cap - live_session_trades) if live_trade_cap is not None else None,
            "cap_reached_utc": live_cap_reached_utc.isoformat() if live_cap_reached_utc else None,
            "max_concurrent_positions": int(os.getenv("KRONOS_MAX_CONCURRENT_POSITIONS", "3")),
            "allocation": {
                "macro": int(os.getenv("KRONOS_MAX_MACRO_POSITIONS", "2")),
                "scalp": 1
            }
        },
        "volume_profile_veto": {
            "enabled": quant_bot.enable_volume_profile_veto,
            "rules": ["VP_FIRING_INTO_POC", "VP_HVN_CHOP"],
            "cached_profiles": len(quant_bot.volume_profile_cache._cache),
        },
        "trade_history": quant_bot.executor.get_live_trade_history(limit=25) if live_account.get("connected") else [],
        "last_cycle": last_cycle_summary,
        "symbol_cooldowns": apex_scalper.get_cooldown_status()
    })

@app.route('/api/scalper/status', methods=['GET'])
def scalper_status():
    active = None
    if apex_scalper.active_scalp:
        pos = apex_scalper.active_scalp
        active = {
            "position_id": pos.position_id,
            "symbol": pos.symbol,
            "side": pos.side,
            "entry_price": float(pos.entry_price),
            "stop_loss": float(pos.stop_loss),
            "take_profit": float(pos.take_profit),
            "notional_usd": float(pos.notional_usd),
            "leverage": pos.leverage
        }
    return jsonify({
        "success": True,
        "is_slot_available": apex_scalper.is_slot_available,
        "active_scalp": active,
        "total_closed_scalps": len(apex_scalper.closed_scalp_records),
        "symbol_cooldowns": apex_scalper.get_cooldown_status()
    })

@app.route('/api/live/toggle', methods=['POST'])
def toggle_live():
    global live_trading_enabled, live_trade_cap, live_session_trades, live_cap_reached_utc
    data = request.get_json(silent=True) or {}
    with state_lock:
        if "trade_cap" in data:
            cap_val = data["trade_cap"]
            live_trade_cap = int(cap_val) if cap_val is not None and int(cap_val) > 0 else 50
        if data.get("reset_trade_count"):
            live_session_trades = 0
            live_cap_reached_utc = None
        if "enabled" in data:
            live_trading_enabled = bool(data["enabled"])
        else:
            live_trading_enabled = not live_trading_enabled
        if live_trading_enabled and live_trade_cap is not None and live_session_trades >= live_trade_cap:
            live_session_trades = 0
            live_cap_reached_utc = None
        _save_quota_state()
    return jsonify({
        "success": True,
        "live_trading_enabled": live_trading_enabled,
        "trade_cap": live_trade_cap,
        "session_trades": live_session_trades,
        "message": f"AWS Live Trading {'ACTIVATED' if live_trading_enabled else 'PAUSED'}"
                   + (f" (Auto-Pause Cap: {live_session_trades}/{live_trade_cap} trades)." if live_trade_cap else ".")
    })

@app.route('/api/live/flatten', methods=['POST'])
def flatten_live():
    res = quant_bot.executor.flatten_all_live_positions()
    now_u = datetime.datetime.now(datetime.timezone.utc)
    for p in res.get("closed_positions", []):
        sym = p.get("symbol")
        if sym:
            apex_scalper.register_symbol_cooldown(sym, now_u, duration_seconds=900, reason="MANUAL_API_FLATTEN")
            quant_bot.register_symbol_cooldown(sym, now_u, duration_seconds=900, reason="MANUAL_API_FLATTEN")
            logger.info("[COOLDOWN] Manual API flatten on %s: 15-minute quarantine activated.", sym)
    return jsonify(res)


@app.route('/api/tiger/radar', methods=['GET'])
def get_headless_tiger_radar():
    """Serves real-time tiger_radar.json for local PC tap."""
    data_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data')
    radar_path = os.path.join(data_dir, 'tiger_radar.json')
    for p in [radar_path, "/home/ec2-user/kronos-bot/data/tiger_radar.json", "/home/ec2-user/data/tiger_radar.json"]:
        if os.path.exists(p):
            try:
                with open(p, 'r', encoding='utf-8') as f:
                    radar_data = json.load(f)
                    if radar_data and radar_data.get("active_prey"):
                        return jsonify({
                            "success": True,
                            "radar": radar_data,
                            "advisory": {
                                "zero_mfe_abort_seconds": 30,
                                "zero_mfe_max_window_seconds": 180,
                                "min_buy_wick_ratio": 0.60,
                                "min_sell_wick_ratio": 0.45,
                                "min_24h_turnover_usd": 50000000.0,
                                "status": "ARMED_AND_STREAMING",
                                "reconnaissance_bridge": {
                                    "status": "ONLINE",
                                    "target": "Strategy #1 (Macro Storm Protocol)",
                                    "scouted_ranks": [1, 2],
                                    "confluence_multiplier": "1.20x (+20% Kelly)",
                                    "conflict_throttle": "0.70x (-30% Kelly)",
                                    "min_turnover_usd": 50000000.0
                                }
                            }
                        })
            except Exception:
                pass
    return jsonify({"success": False, "error": "radar not ready"}), 404


@app.route('/api/tiger/state', methods=['GET'])
def get_headless_tiger_state():
    """Serves real-time tiger_state.json for local PC tap."""
    data_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data')
    for p in [os.path.join(data_dir, 'tiger_state.json'), "/home/ec2-user/kronos-bot/data/tiger_state.json", "/home/ec2-user/data/tiger_state.json"]:
        if os.path.exists(p):
            try:
                with open(p, 'r', encoding='utf-8') as f:
                    return jsonify({"success": True, "state": json.load(f)})
            except Exception:
                pass
    return jsonify({"success": False, "error": "state not ready"}), 404


@app.route('/api/live/trades', methods=['GET'])
def live_trades():
    """Serves live executed trade history with whitelisted IP access."""
    try:
        limit = min(1000, max(1, int(request.args.get("limit", 100))))
        trades = quant_bot.executor.get_live_trade_history(limit=limit)
        return jsonify({"success": True, "trades": trades})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/live/scan', methods=['POST'])
def run_live_scan():
    """Trigger an immediate live scan cycle on AWS."""
    try:
        summary = _execute_live_cycle()
        return jsonify(summary)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/scalper/reset-slot', methods=['POST'])
def reset_scalper_slot():
    """Reset the scalper slot on AWS."""
    apex_scalper.active_scalp = None
    return jsonify({"success": True, "message": "Apex scalper slot reset successfully."})


@app.route('/api/system/anti-bloat', methods=['GET'])
def get_anti_bloat_telemetry():
    """Serves real-time bloat detection, RAM, disk, and cache hygiene telemetry."""
    try:
        status = anti_bloat.get_status()
        return jsonify({"success": True, "anti_bloat": status})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/system/anti-bloat/clean', methods=['POST'])
def trigger_anti_bloat_clean():
    """Triggers an immediate autonomous cleanse cycle on AWS."""
    try:
        summary = anti_bloat.execute_cleanse_cycle(force_deep_clean=True)
        return jsonify({"success": True, "clean_summary": summary})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


def shutdown_handler(signum, frame):
    global running
    logger.info("Shutdown signal received (%s). Exiting gracefully...", signum)
    running = False
    sys.exit(0)


def main():
    signal.signal(signal.SIGINT, shutdown_handler)
    signal.signal(signal.SIGTERM, shutdown_handler)

    logger.info("============================================================================")
    logger.info(" [Kronos] Headless Cloud Production Daemon Starting (Tag: %s)", os.getenv("KRONOS_INSTANCE_TAG", "AWS"))
    logger.info("============================================================================")

    # Initial server time synchronization
    quant_bot.executor._sync_server_time()
    acct = quant_bot.executor.get_live_account_summary()
    logger.info(
        "Binance Futures Connected: %s | Wallet: $%.2f USDT | Available: $%.2f USDT | Positions: %d",
        acct.get("connected"),
        float(acct.get("total_wallet_balance_usd", 0)),
        float(acct.get("available_balance_usd", 0)),
        len(acct.get("positions", []))
    )

    # Start autonomous trading thread
    t = threading.Thread(target=daemon_loop, daemon=True)
    t.start()

    # Start Micro-Flask API on port 7070 (host 0.0.0.0 for coordinator health access)
    port = int(os.getenv("PORT", "7070"))
    logger.info("Status & Coordinator API listening on http://0.0.0.0:%d", port)
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()
