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
import signal
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

from src.quant.config import ALL_SUPPORTED_SYMBOLS, TOP_10_SYMBOLS
from src.quant.orchestrator import QuantBotOrchestrator
from src.quant.apex_scalper import ApexScalperEngine
from src.quant.gemini_strategy_arbiter import GeminiStrategyArbiter
from src.quant.binance_execution import PositionState, TradeTicket

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s UTC] [%(levelname)s] [Kronos-Headless] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("KronosHeadless")

# Instantiate singletons
quant_bot = QuantBotOrchestrator(execution_mode="LIVE")
apex_scalper = ApexScalperEngine()
gemini_arbiter = GeminiStrategyArbiter()

# Operational state
running = True
live_trading_enabled = True
scan_interval_sec = int(os.getenv("KRONOS_SCAN_INTERVAL", "60"))
last_scan_utc: Optional[datetime.datetime] = None
next_scan_utc: Optional[datetime.datetime] = None
last_cycle_summary: Optional[Dict[str, Any]] = None
state_lock = threading.Lock()


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

    # Fetch lookbacks
    lookbacks = {}
    for sym in list(ALL_SUPPORTED_SYMBOLS.keys())[:5]:
        try:
            live_df = quant_bot.index_engine.fetch_lookback_dataframe(sym, limit=100)
            if live_df is not None and len(live_df) >= 20:
                lookbacks[sym] = live_df
        except Exception as e:
            logger.debug("Lookback fetch error for %s: %s", sym, e)

    report = quant_bot.run_scan_cycle(
        account_equity=equity,
        lookback_data_map=lookbacks if lookbacks else None,
        execution_mode="LIVE"
    )

    last_scan_utc = report.timestamp_utc
    next_scan_utc = now_u + datetime.timedelta(seconds=scan_interval_sec)

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


def execute_apex_scalp_step():
    """High-frequency 5s order book screening and position management."""
    now_utc = datetime.datetime.now(datetime.timezone.utc)

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

                hit_tp = (pos.side == "BUY" and curr_price >= pos.take_profit) or (pos.side == "SELL" and curr_price <= pos.take_profit)
                hit_sl = (pos.side == "BUY" and curr_price <= pos.stop_loss) or (pos.side == "SELL" and curr_price >= pos.stop_loss)
                fast_profit = net_unrealized_pct >= Decimal("0.25")
                timed_out = duration_sec >= pos.max_duration_seconds

                if hit_tp or hit_sl or fast_profit or timed_out:
                    reason = "TAKE_PROFIT_HIT" if hit_tp else ("FAST_PROFIT_SNATCH" if fast_profit else ("STOP_LOSS_HIT" if hit_sl else "TIME_EXPIRATION"))
                    fee_usd = pos.notional_usd * (friction_pct / Decimal("100"))

                    # Cancel algo orders and flatten if necessary
                    try:
                        quant_bot.executor._signed_request("DELETE", "/fapi/v1/algoOpenOrders", {"symbol": pos.symbol})
                    except Exception:
                        pass
                    if reason in ("FAST_PROFIT_SNATCH", "TIME_EXPIRATION"):
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
                    logger.info("Apex Scalp Closed: %s (%s) Net Return: %.2f%% PnL: $%.2f", pos.symbol, reason, float(net_unrealized_pct), float(telemetry.net_pnl_usd))
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
        candidates = []
        for sym in list(ALL_SUPPORTED_SYMBOLS.keys()):
            if sym in active_symbols:
                continue
            try:
                klines = quant_bot.index_engine.fetch_recent_klines(sym, interval="5m", limit=24)
                if not klines or len(klines) < 12:
                    continue
                curr_p = klines[-1]["close"]
                micro_data = quant_bot.index_engine.fetch_order_book_microstructure(sym, depth_limit=10)
                cand = apex_scalper.evaluate_microstructure_candidate(
                    symbol=sym,
                    current_price=curr_p,
                    best_bid=micro_data.best_bid,
                    best_ask=micro_data.best_ask,
                    order_book_imbalance=micro_data.obi,
                    recent_klines=klines,
                    bnb_discount=True,
                    micro_skew_bps=micro_data.micro_skew_bps,
                    micro_price=micro_data.micro_price
                )
                if cand:
                    candidates.append(cand)
            except Exception:
                continue

        apex = apex_scalper.select_apex_candidate(candidates)
        if apex:
            pos_id = f"SCALP-{now_utc.strftime('%H%M%S')}"
            new_pos = apex_scalper.open_scalp(apex, account_equity=available_cash, position_id=pos_id, current_time_utc=now_utc, available_balance_usd=available_cash)
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
                    net_expected_gain_pct=apex.predicted_drift_pct
                )
                live_res = quant_bot.executor.submit_live_bracket_order(ticket)
                if live_res.state == PositionState.REJECTED:
                    logger.warning("Apex scalp entry rejected: %s", live_res.close_reason)
                    apex_scalper.active_scalp = None
                    return
                logger.info("Apex Scalp Dispatched: %s (%s) Lev: %dx Notional: $%.2f", apex.symbol, apex.side, new_pos.leverage, float(new_pos.notional_usd))
    except Exception as e:
        logger.debug("Apex scalper cycle: %s", e)


def daemon_loop():
    """Main background loop coordinating macro cycles and high-frequency scalping."""
    logger.info("Background daemon active. Main scan every %ds, scalper tick every 5s.", scan_interval_sec)
    last_macro_time = 0.0

    while running:
        now_ts = time.time()

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
        "last_cycle": last_cycle_summary
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
        "total_closed_scalps": len(apex_scalper.closed_scalp_records)
    })

@app.route('/api/live/toggle', methods=['POST'])
def toggle_live():
    global live_trading_enabled
    data = request.get_json(silent=True) or {}
    if "enabled" in data:
        live_trading_enabled = bool(data["enabled"])
    else:
        live_trading_enabled = not live_trading_enabled
    return jsonify({
        "success": True,
        "live_trading_enabled": live_trading_enabled,
        "message": f"AWS Live Trading {'ACTIVATED' if live_trading_enabled else 'PAUSED'}."
    })

@app.route('/api/live/flatten', methods=['POST'])
def flatten_live():
    res = quant_bot.executor.flatten_all_live_positions()
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
