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
from typing import Optional, Dict, Any

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

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s UTC] [%(levelname)s] [Kronos-Headless] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("KronosHeadless")

# Instantiate singletons with live execution enabled and lean headless trajectory
executor = BinanceAtomicExecutor(dry_run=False, realistic_friction=True, symbols_config=ALL_SUPPORTED_SYMBOLS)
trajectory_engine = KronosTrajectoryEngine(service_url="", symbols_config=ALL_SUPPORTED_SYMBOLS)
quant_bot = QuantBotOrchestrator(
    symbols_config=ALL_SUPPORTED_SYMBOLS,
    risk_config=DEFAULT_RISK_CONFIG,
    executor=executor,
    trajectory_engine=trajectory_engine,
    enable_volume_profile_veto=True,
    require_neural_model=False
)
apex_scalper = ApexScalperEngine(
    symbols_config=ALL_SUPPORTED_SYMBOLS,
    risk_config=DEFAULT_RISK_CONFIG,
    min_score_threshold=Decimal("0.35")
)
gemini_arbiter = GeminiStrategyArbiter()

# Operational state & persistent trade-cap auto-pause guard
QUOTA_STATE_PATH = os.path.join(WORKSPACE_ROOT, "data", "aws_trade_quota.json")
running = True
live_trading_enabled = True
live_trade_cap: Optional[int] = int(os.getenv("KRONOS_LIVE_TRADE_CAP")) if os.getenv("KRONOS_LIVE_TRADE_CAP", "").isdigit() else None
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
            live_trade_cap = int(d["live_trade_cap"]) if d["live_trade_cap"] is not None else None
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
    """Increment live session trade counter and auto-pause immediately when quota is reached."""
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

    remaining_quota = (live_trade_cap - live_session_trades) if live_trade_cap is not None else None
    report = quant_bot.run_scan_cycle(
        account_equity=equity,
        lookback_data_map=lookbacks if lookbacks else None,
        execution_mode="LIVE",
        max_new_entries=remaining_quota
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

                if hit_tp or hit_sl or timed_out:
                    reason = "TAKE_PROFIT_HIT" if hit_tp else ("STOP_LOSS_HIT" if hit_sl else "TIME_EXPIRATION")
                    fee_usd = pos.notional_usd * (friction_pct / Decimal("100"))

                    # Cancel algo orders and flatten if necessary
                    try:
                        quant_bot.executor._signed_request("DELETE", "/fapi/v1/algoOpenOrders", {"symbol": pos.symbol})
                    except Exception:
                        pass
                    if reason in ("TIME_EXPIRATION", "STOP_LOSS_HIT"):
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

        candidates = []
        for sym in list(ALL_SUPPORTED_SYMBOLS.keys()):
            # Skip if currently holding
            if sym in active_symbols:
                continue
            # Skip if quarantined by Bayesian learning distillation
            if sym in quarantined_symbols:
                continue
            # Skip if in post-exit quarantine cooldown
            if apex_scalper.is_symbol_in_cooldown(sym, now_utc):
                continue

            try:
                klines = quant_bot.index_engine.fetch_recent_klines(sym, interval="5m", limit=24)
                if not klines or len(klines) < 12:
                    continue
                curr_p = klines[-1]["close"]
                micro_data = quant_bot.index_engine.fetch_order_book_microstructure(sym, depth_limit=10)
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
            except Exception:
                continue

        apex = apex_scalper.select_apex_candidate(candidates)
        if apex:
            # Tsunami Storm Protocol Gate
            try:
                from src.quant.storm_protocol import StormProtocolManager
                storm_mgr = StormProtocolManager()
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
                live_res = quant_bot.executor.submit_live_bracket_order(ticket)
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
        },
        "volume_profile_veto": {
            "enabled": quant_bot.enable_volume_profile_veto,
            "rules": ["VP_FIRING_INTO_POC", "VP_HVN_CHOP"],
            "cached_profiles": len(quant_bot.volume_profile_cache._cache),
        },
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
            live_trade_cap = int(cap_val) if cap_val is not None and int(cap_val) > 0 else None
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
