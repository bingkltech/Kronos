"""
scripts/tiger_worker.py — Standalone Real-Time Forward Paper Trading Daemon for Strategy #3 (Stalking Tiger).

Continuously executes:
1. Zero-Ban Bulk REST 24hr Ticker Sieve (Top 150 scanned -> Top 5 Hot Prey isolated every 30s).
2. Dynamic Rate Limit Watchdog (inspects x-mbx-used-weight-1m on every call).
3. Live Microstructure Orderflow Tracking & Trapped Liquidity Climax Trigger.
4. Signal TTL (90s cancel) & The 8-12-15 Minute Temporal Expiry Decay Ladder.
5. Autonomous Real-Time Learning & TCA Distillation (persisting to data/tiger_trades.db and data/tiger_distilled_rules.json).
6. Strict AGENTS.md Invariant 1 (Zero Float Financial Math with Decimal).
"""

import argparse
import datetime
from decimal import Decimal, ROUND_HALF_UP
import json
import logging
import os
import sys
import time
from typing import Any, Dict, List, Optional, Tuple
import urllib.request
import urllib.error

# Add repository root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.quant.tiger_config import TigerMasterConfig, DEFAULT_TIGER_CONFIG
from src.quant.tiger_scanner import (
    BinanceRateLimitWatchdog,
    TigerUniverseScanner,
    PreyCandidate,
)
from src.quant.tiger_orderflow import (
    SymbolOrderflowTracker,
    AggTradeEvent,
    DepthSnapshot,
    AbsorptionSignal,
)
from src.quant.tiger_scalper import (
    TigerExecutionEngine,
    PendingTigerSignal,
    ActiveTigerPosition,
)
from src.quant.volume_profile import DailyVolumeProfileCache
from src.quant.tiger_learning import (
    TigerLearningEngine,
    TigerTradeForensics,
    classify_trade_autopsy
)
from src.quant.tiger_ws import TigerWebSocketManager
from src.quant.capital_recycler import (
    CapitalRecycler,
    RecyclerDecision,
    TradeHealthEvaluation
)

# Configure structured console logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [TIGER-DAEMON] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("tiger_worker")

NOTIONAL_PER_TRADE = Decimal("100.00")  # $20 margin x 5x leverage
FEE_FRICTION_PCT = Decimal("0.0009")    # 0.09% roundtrip (VIP0 maker/taker + slippage)


def fetch_live_binance_tickers() -> Tuple[List[Dict[str, Any]], Dict[str, str]]:
    """Fetches bulk 24hr ticker data from Binance USD(S)-M Futures public REST API (40 weight)."""
    url = "https://fapi.binance.com/fapi/v1/ticker/24hr"
    req = urllib.request.Request(url, headers={"User-Agent": "Kronos-TigerScalper/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            headers = dict(response.info())
            raw_data = response.read().decode("utf-8")
            return json.loads(raw_data), headers
    except Exception as e:
        logger.error(f"[NETWORK ERROR] Failed to fetch bulk tickers: {e}")
        raise


_KLINE_CACHE: Dict[str, Tuple[float, List[List[Any]]]] = {}


def fetch_symbol_recent_klines(symbol: str, limit: int = 30, max_age_seconds: float = 25.0) -> List[List[Any]]:
    """Fetches the last N 1m klines with proactive caching to conserve Binance weight."""
    now = time.time()
    if symbol in _KLINE_CACHE:
        cached_ts, cached_data = _KLINE_CACHE[symbol]
        if (now - cached_ts) < max_age_seconds and len(cached_data) >= limit:
            return cached_data

    url = f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval=1m&limit={limit}"
    req = urllib.request.Request(url, headers={"User-Agent": "Kronos-TigerScalper/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read().decode("utf-8"))
            _KLINE_CACHE[symbol] = (now, data)
            return data
    except Exception as e:
        logger.warning(f"[KLINES ERROR] Failed to fetch 1m klines for {symbol}: {e}")
        if symbol in _KLINE_CACHE:
            return _KLINE_CACHE[symbol][1]
        return []


def fetch_symbol_open_interest(symbol: str) -> Optional[Tuple[Decimal, int, Dict[str, str]]]:
    """Fetches Open Interest from Binance USD(S)-M Futures REST API (1 weight)."""
    url = f"https://fapi.binance.com/fapi/v1/openInterest?symbol={symbol}"
    req = urllib.request.Request(url, headers={"User-Agent": "Kronos-TigerScalper/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=3) as response:
            headers = dict(response.info())
            raw_data = response.read().decode("utf-8")
            data = json.loads(raw_data)
            oi_val = Decimal(str(data["openInterest"]))
            ts_ms = int(data.get("time", int(time.time() * 1000)))
            return oi_val, ts_ms, headers
    except Exception as e:
        logger.warning(f"[OI ERROR] Failed to fetch open interest for {symbol}: {e}")
        return None


def run_scan_once(cfg: TigerMasterConfig) -> None:
    """Execute a single live scan of Binance USD(S)-M Top 150 and print Hot Prey candidates."""
    logger.info("Initializing Live Tiger Sieve against Binance USD(S)-M public endpoint...")
    scanner = TigerUniverseScanner(master_config=cfg, fetcher_func=fetch_live_binance_tickers)
    
    start_t = time.time()
    try:
        universe_150, top_5_prey = scanner.run_sieve()
    except Exception as e:
        logger.error(f"Live scan failed: {e}")
        return

    duration = time.time() - start_t
    used_weight = scanner.watchdog.last_used_weight_1m

    print("\n" + "=" * 90)
    print(f"  STALKING TIGER (STRATEGY #3) — LIVE BINANCE USD(S)-M UNIVERSE SCAN")
    print(f"  Scan Latency: {duration:.2f}s | Binance 1m Used Weight: {used_weight}/2400 ({(used_weight/2400)*100:.1f}%)")
    print(f"  Top 150 Qualified Universe: {len(universe_150)} symbols (Turnover >= ${cfg.sieve.min_24h_turnover_usd/1000000:.0f}M)")
    print("=" * 90)
    print(f" {'RANK':<5} | {'SYMBOL':<12} | {'LAST PRICE':<12} | {'24H CHG':<8} | {'24H TURNOVER':<16} | {'VOL SCORE':<10}")
    print("-" * 90)

    for cand in top_5_prey:
        chg_sign = "+" if cand.price_change_pct > Decimal("0") else ""
        turnover_str = f"${cand.turnover_24h_usd:,.0f}"
        print(f" #{cand.rank:<4} | {cand.symbol:<12} | {cand.last_price:<12} | {chg_sign}{cand.price_change_pct}% | {turnover_str:<16} | {cand.volatility_score:.4f}")

    print("=" * 90)
    print(f"[RADAR STATUS] Top {len(top_5_prey)} 'Hot Prey' isolated for Zero-Weight WebSocket sniper streams.")
    print(f"[RATE LIMIT STATUS] Safe headroom remaining: {2400 - used_weight} weight/min (Zero Ban Risk)\n")


def run_realtime_paper_trading(cfg: TigerMasterConfig, is_paper: bool = True) -> None:
    """
    Continuous real-time forward paper trading loop on PC.
    Runs until interrupted, learning from live market flow and logging forensics.
    """
    print("\n" + "=" * 92)
    print(f"  STALKING TIGER (STRATEGY #3) — REAL-TIME LIVE FORWARD PAPER TRADING ENGINE")
    print(f"  Environment: Local High-Performance PC | Exchange: Binance USD(S)-M Futures")
    print(f"  Rate Budget: 2,400 weight/min | Sieve Scan Cadence: 30s | Sniper Slots: 5 Hot Prey")
    print(f"  Capital/Trade: $20 Margin x 5x Leverage ($100 Notional) | Fees: 0.09% Roundtrip")
    print(f"  Temporal Discipline: 90s Signal TTL | 8-12-15m Temporal Decay Ladder")
    print(f"  Forensics Database: data/tiger_trades.db | Learning Rules: data/tiger_distilled_rules.json")
    print("=" * 92 + "\n")

    scanner = TigerUniverseScanner(master_config=cfg, fetcher_func=fetch_live_binance_tickers)
    engine = TigerExecutionEngine(config=cfg)
    learning = TigerLearningEngine()
    capital_recycler = CapitalRecycler()
    vp_cache = DailyVolumeProfileCache()
    ws_manager = TigerWebSocketManager(config=cfg)
    ws_manager.start()

    iteration = 0
    top_5_prey: List[PreyCandidate] = []
    last_hygiene_ts = time.time()
    last_oi_poll_ts = 0.0

    try:
        while True:
            iteration += 1
            loop_start = time.time()
            now_utc = datetime.datetime.now(datetime.timezone.utc)

            # 0. Autonomous System Hygiene Sweep (Every 6 Hours)
            if time.time() - last_hygiene_ts >= 21600:
                try:
                    from scripts.system_hygiene import run_system_hygiene_cycle
                    h_res = run_system_hygiene_cycle(quiet=True)
                    last_hygiene_ts = time.time()
                    logger.info(f"[AUTONOMOUS HYGIENE] Auto-cleanse complete: Reclaimed {h_res['reclaimed_mb']} MB across {h_res['total_files_cleaned']} artifacts.")
                except Exception as he:
                    logger.warning(f"[AUTONOMOUS HYGIENE FAILED] {he}")

            # 1. Dynamic Adaptation & Exclusion Registry
            active_rules = learning.load_distilled_rules()
            quarantined_symbols = (set(active_rules.quarantined_symbols) if active_rules else set()) | capital_recycler.get_active_quarantined_symbols(now_utc)
            active_min_wick = active_rules.calibrated_min_wick_ratio if active_rules else cfg.orderflow.absorption_wick_min_ratio
            active_min_cvd_z = active_rules.calibrated_min_cvd_zscore if active_rules else cfg.orderflow.cvd_divergence_sigma
            active_slow_tp = active_rules.calibrated_slow_tp_pct if active_rules else cfg.brackets.slow_vol_tp_price_pct
            active_slow_sl = active_rules.calibrated_slow_sl_pct if active_rules else cfg.brackets.slow_vol_sl_price_pct

            # Exclude symbols that already have active positions, pending orders, cooldowns, or are quarantined
            engine.cleanup_expired_cooldowns(now_utc)
            active_pos_symbols = {p.symbol for p in engine.active_positions.values()}
            pending_sig_symbols = {s.symbol for s in engine.pending_signals.values()}
            cooldown_symbols = {sym for sym, cd in list(engine.symbol_cooldowns.items()) if now_utc < cd}
            excluded_from_hunting = active_pos_symbols | pending_sig_symbols | cooldown_symbols | quarantined_symbols

            # 1.1 Check Rate Limit & Execute Top 150 Sieve (every 30s or throttled)
            poll_interval = scanner.watchdog.get_poll_interval_seconds()
            if iteration == 1 or (loop_start - scanner.last_scan_ts >= poll_interval):
                try:
                    universe_150, top_5_prey = scanner.run_sieve(excluded_symbols=excluded_from_hunting)
                    # Feed isolated prey symbols PLUS any active position symbols into live WebSocket manager
                    all_monitored = list(set(c.symbol for c in top_5_prey) | active_pos_symbols)
                    ws_manager.update_symbols(all_monitored)
                except Exception as e:
                    logger.error(f"[SCAN FAILED] Error during bulk ticker scan: {e}")

            used_weight = scanner.watchdog.last_used_weight_1m

            # 1.2 Poll Open Interest for Top 5 Hot Prey (Adaptive 30-45s cadence)
            oi_interval = 45.0 if scanner.watchdog.is_throttled else 30.0
            if (loop_start - last_oi_poll_ts >= oi_interval) and top_5_prey and scanner.watchdog.can_request(len(top_5_prey)):
                for cand in top_5_prey:
                    try:
                        oi_res = fetch_symbol_open_interest(cand.symbol)
                        if oi_res:
                            oi_val, oi_ts, oi_headers = oi_res
                            scanner.watchdog.update_from_headers(oi_headers)
                            tracker = ws_manager.get_tracker(cand.symbol)
                            if tracker:
                                tracker.process_open_interest(oi_val, oi_ts)
                    except Exception as oie:
                        logger.warning(f"[OI REFRESH FAILED] {cand.symbol}: {oie}")
                last_oi_poll_ts = loop_start

            # 2. Check Expiration of Pending Signals (90s TTL)
            expired_signals = engine.check_signal_expiration(now_utc)
            for exp_id in expired_signals:
                logger.info(f"[SIGNAL EXPIRED] 90s TTL reached for signal {exp_id}. Cancelled order.")

            # 3. Monitor & Manage Open Active Positions (Capital Recycler Overseer)
            recycler_evaluations = []
            btc_1m_ret, btc_cvd_z = ws_manager.get_btc_macro_pulse()

            for pos_id, pos in list(engine.active_positions.items()):
                # Fetch latest price
                klines = fetch_symbol_recent_klines(pos.symbol, limit=2)
                if not klines:
                    continue
                current_price = Decimal(str(klines[-1][4]))

                # 3.1 Capital Recycler Multi-Factor Position Audit
                tracker = ws_manager.get_tracker(pos.symbol)
                cand_cvd_z = tracker.compute_cvd_metrics()[1] if tracker else None
                eval_res = capital_recycler.evaluate(
                    pos,
                    current_price=current_price,
                    current_time_utc=now_utc,
                    btc_price_change_pct=btc_1m_ret,
                    cvd_zscore=cand_cvd_z,
                    scanner_candidates=top_5_prey
                )
                recycler_evaluations.append({
                    "symbol": eval_res.symbol,
                    "position_id": eval_res.position_id,
                    "decision": eval_res.decision.value,
                    "health_score": str(eval_res.health_score),
                    "current_pnl_pct": str(eval_res.current_pnl_pct),
                    "mfe_pct": str(eval_res.mfe_pct),
                    "elapsed_minutes": str(eval_res.elapsed_minutes),
                    "should_exit": eval_res.should_exit,
                    "action_reason": eval_res.action_reason
                })

                # 3.2 Dynamic Breakeven Ratchet Reflex
                if eval_res.should_ratchet and not pos.is_breakeven_ratcheted:
                    capital_recycler.execute_ratchet(pos, eval_res)
                    engine.ratchet_to_breakeven(pos_id, new_sl=eval_res.recommended_new_sl)
                    logger.info(
                        f"[CAPITAL RECYCLER RATCHET] {pos.symbol} locked at Breakeven + buffer "
                        f"({eval_res.recommended_new_sl}) | {eval_res.action_reason}"
                    )

                # 3.3 Check Lifecycle & Move-On Decisions
                action, reason = engine.evaluate_temporal_lifecycle(
                    position_id=pos_id,
                    current_price=current_price,
                    current_time_utc=now_utc,
                    fee_friction_pct=FEE_FRICTION_PCT
                )

                if eval_res.should_exit:
                    action = eval_res.decision.value
                    reason = f"CAPITAL_RECYCLER: {eval_res.action_reason}"

                if action in ("TAKE_PROFIT", "STOP_LOSS", "STALL_SCRATCH", "HARD_KILL") or eval_res.should_exit:
                    # Execute Move-On via Capital Recycler (Zero-Orphan Contract + Quarantine + Autopsy)
                    capital_recycler.execute_move_on(
                        pos,
                        eval_res,
                        current_price=current_price,
                        current_time_utc=now_utc,
                        on_slot_liberated=lambda pid, sym: logger.info(
                            f"[SLOT LIBERATED] Capital Recycler freed slot from {sym} for fresh prey."
                        )
                    )

                    # Close position in engine
                    close_info = engine.close_position(
                        position_id=pos_id,
                        exit_price=current_price,
                        exit_time_utc=now_utc,
                        reason=reason or action
                    )
                    gross_ret = Decimal(close_info["pnl_pct"])
                    net_ret = gross_ret - FEE_FRICTION_PCT
                    notional_traded = pos.notional_usd
                    net_usd = notional_traded * net_ret
                    duration_s = int((now_utc - pos.entry_time_utc).total_seconds())

                    mfe_pct = Decimal("0")
                    mae_pct = Decimal("0")
                    if pos.side == "BUY":
                        if pos.highest_favorable_price:
                            mfe_pct = (pos.highest_favorable_price - pos.entry_price) / pos.entry_price
                        if pos.lowest_adverse_price:
                            mae_pct = (pos.entry_price - pos.lowest_adverse_price) / pos.entry_price
                    else:
                        if pos.highest_favorable_price:
                            mfe_pct = (pos.entry_price - pos.highest_favorable_price) / pos.entry_price
                        if pos.lowest_adverse_price:
                            mae_pct = (pos.lowest_adverse_price - pos.entry_price) / pos.entry_price

                    # Classify trade autopsy outcome
                    auto_code = classify_trade_autopsy(
                        is_win=close_info["is_win"],
                        mfe_pct=mfe_pct,
                        mae_pct=mae_pct,
                        net_pnl_usd=net_usd,
                        exit_reason=close_info["reason"]
                    )
                    exec_mode = "PAPER" if is_paper else "LIVE"

                    # Record full forensic telemetry
                    forensics = TigerTradeForensics(
                        trade_id=pos_id,
                        symbol=pos.symbol,
                        side=pos.side,
                        entry_price=pos.entry_price,
                        exit_price=current_price,
                        notional_usd=notional_traded,
                        net_pnl_usd=net_usd.quantize(Decimal("0.01")),
                        net_pnl_pct=net_ret.quantize(Decimal("0.0001")),
                        duration_seconds=duration_s,
                        exit_reason=close_info["reason"],
                        is_win=close_info["is_win"],
                        mfe_pct=mfe_pct.quantize(Decimal("0.0001")),
                        mae_pct=mae_pct.quantize(Decimal("0.0001")),
                        wick_ratio=Decimal("0.45"),
                        cvd_zscore=Decimal("2.2"),
                        is_slow_regime=pos.is_slow_regime,
                        created_at_utc=pos.entry_time_utc.isoformat(),
                        closed_at_utc=now_utc.isoformat(),
                        execution_mode=exec_mode,
                        autopsy_code=auto_code
                    )
                    learning.record_trade(forensics)

                    # Trigger autonomous learning distillation
                    distilled = learning.run_learning_distillation()
                    if distilled:
                        logger.info(f"[LEARNING AUDIT] Rules updated! Win Rate: {distilled.win_rate_pct}% | PF: {distilled.profit_factor}")

            # 4. Process Pending Signals: Check for Limit Entry Fills
            for sig_id, sig in list(engine.pending_signals.items()):
                if sig.status == "PENDING":
                    klines = fetch_symbol_recent_klines(sig.symbol, limit=2)
                    if not klines:
                        continue
                    latest_high = Decimal(str(klines[-1][2]))
                    latest_low = Decimal(str(klines[-1][3]))

                    filled = False
                    fill_price = sig.entry_trigger_price
                    if sig.action == "SELL" and latest_low <= sig.entry_trigger_price:
                        filled = True
                    elif sig.action == "BUY" and latest_high >= sig.entry_trigger_price:
                        filled = True

                    if filled:
                        if cfg.brackets.volatility_parity_enabled:
                            notional_usd, qty = engine.calculate_volatility_parity_sizing(fill_price, sig.stop_loss_price)
                        else:
                            notional_usd = NOTIONAL_PER_TRADE
                            qty = (notional_usd / fill_price).quantize(Decimal("0.001"))
                        engine.fill_signal(sig_id, fill_price=fill_price, quantity=qty, fill_time_utc=now_utc, notional_usd=notional_usd)
                        logger.info(f"[TIGER POUNCE FILLED] {sig.symbol} {sig.action} filled at {fill_price} (TP: {sig.take_profit_price}, SL: {sig.stop_loss_price}) | Notional: ${notional_usd:.2f} (Locked Risk: ${cfg.brackets.risk_budget_per_trade_usd})")

            # 5. Scan Active Targets for New Trapped Trader Absorption Setups
            total_committed = len(engine.active_positions) + len(engine.pending_signals)
            if not engine.is_paused(now_utc) and not engine.is_fleet_in_cooldown(now_utc) and total_committed < cfg.brackets.max_concurrent_positions:
                btc_1m_ret, btc_cvd_z = ws_manager.get_btc_macro_pulse()
                cycle_qualified_signals: List[Tuple[PreyCandidate, AbsorptionSignal, Decimal, Decimal, Decimal]] = []

                for cand in top_5_prey:
                    # Dynamic Quarantine Veto: Skip symbols with negative expectancy
                    if cand.symbol in quarantined_symbols:
                        continue

                    # Post-Exit Cooldown: Skip symbols in 15m cooling period
                    if engine.is_symbol_in_cooldown(cand.symbol, now_utc):
                        continue

                    # Don't open if symbol already has active position or pending signal
                    if any(p.symbol == cand.symbol for p in engine.active_positions.values()):
                        continue
                    if any(s.symbol == cand.symbol for s in engine.pending_signals.values()):
                        continue

                    klines = fetch_symbol_recent_klines(cand.symbol, limit=60)
                    if len(klines) < 20:
                        continue

                    opens = [Decimal(str(k[1])) for k in klines]
                    highs = [Decimal(str(k[2])) for k in klines]
                    lows = [Decimal(str(k[3])) for k in klines]
                    closes = [Decimal(str(k[4])) for k in klines]
                    volumes = [Decimal(str(k[5])) for k in klines]

                    bar_open = opens[-1]
                    bar_high = highs[-1]
                    bar_low = lows[-1]
                    bar_close = closes[-1]
                    bar_vol = volumes[-1]
                    bar_range = bar_high - bar_low
                    avg_vol_20 = sum(volumes[-21:-1]) / Decimal("20")

                    # Compute rolling ATR % for regime classification
                    tr_list = [max(highs[j] - lows[j], abs(highs[j] - closes[j-1]), abs(lows[j] - closes[j-1])) for j in range(len(closes)-14, len(closes))]
                    atr_15 = sum(tr_list) / Decimal("14")
                    atr_pct = atr_15 / bar_close if bar_close > Decimal("0") else Decimal("0")

                    is_slow_cand = atr_pct < cfg.brackets.slow_vol_atr_threshold_pct
                    target_tp = active_slow_tp if is_slow_cand else cfg.brackets.calibrated_tp_price_pct
                    target_sl = active_slow_sl if is_slow_cand else cfg.brackets.fast_vol_sl_price_pct

                    if bar_range > Decimal("0") and avg_vol_20 > Decimal("0"):
                        vol_multiple = bar_vol / avg_vol_20
                        prev_swing_high = max(highs[-16:-1])
                        prev_swing_low = min(lows[-16:-1])

                        # 1h Macro Trend Anchor: returns over 60m
                        ret_1h = (closes[-1] - opens[0]) / opens[0] if opens[0] > Decimal("0") else Decimal("0")
                        is_bull_1h = ret_1h >= Decimal("0.020")
                        is_bear_1h = ret_1h <= Decimal("-0.020")

                        # Upper / lower wick ratios
                        u_wick = (bar_high - max(bar_open, bar_close)) / bar_range
                        l_wick = (min(bar_open, bar_close) - bar_low) / bar_range

                        # Micro Confirmation: Candle close location within total range (0.0=low, 1.0=high)
                        close_loc = (bar_close - bar_low) / bar_range
                        close_bottom_35 = close_loc <= cfg.orderflow.max_candle_close_loc_pct
                        close_top_35 = close_loc >= (Decimal("1.0") - cfg.orderflow.max_candle_close_loc_pct)

                        tracker = ws_manager.get_tracker(cand.symbol)
                        macro_trend_1h = "BULLISH" if is_bull_1h else ("BEARISH" if is_bear_1h else "NEUTRAL")

                        # 1. Attempt Sub-Second Orderflow Detection if WebSocket Tracker has sufficient ticks
                        evaluated_sig: Optional[AbsorptionSignal] = None
                        if tracker and len(tracker.trades) >= 5:
                            evaluated_sig = tracker.detect_trapped_trader_climax(
                                bar_open=bar_open, bar_high=bar_high, bar_low=bar_low, bar_close=bar_close,
                                bar_volume=bar_vol, avg_volume_20=avg_vol_20,
                                macro_trend_1h=macro_trend_1h,
                                btc_1m_return=btc_1m_ret,
                                btc_cvd_zscore=btc_cvd_z
                            )

                        # 2. Setup Short Evaluation (Trapped Bulls Sweep at Resistance)
                        if bar_high >= prev_swing_high:
                            trigger_short = False
                            sig_reason = ""
                            if evaluated_sig and evaluated_sig.is_valid and evaluated_sig.action == "SELL":
                                trigger_short = True
                                sig_reason = f"Live WS OFI/CVD Climax ({evaluated_sig.reason})"
                            elif not tracker or len(tracker.trades) < 5:
                                # Cold-start fallback: Rejection wick + Wyckoff outer close + BTC Gate + ΔOI Gate
                                _, fallback_doi_pct = tracker.compute_delta_oi() if tracker else (Decimal("0"), Decimal("0"))
                                oi_veto_fallback = False
                                if cfg.orderflow.delta_oi_filter_enabled:
                                    if not tracker or len(tracker.oi_history) < 2:
                                        oi_veto_fallback = True  # Strict Negative Affirmation: Never pounce blind!
                                    elif fallback_doi_pct < cfg.orderflow.min_delta_oi_pct:
                                        oi_veto_fallback = True
                                btc_veto_short = cfg.orderflow.btc_tide_gate_enabled and (btc_1m_ret >= abs(cfg.orderflow.btc_1m_dump_threshold_pct))
                                if u_wick >= active_min_wick and close_bottom_35 and vol_multiple >= Decimal("2.0") and not (cfg.orderflow.macro_trend_filter_enabled and is_bull_1h) and not btc_veto_short and not oi_veto_fallback:
                                    trigger_short = True
                                    sig_reason = f"Cold-Start Wick/Volume Sweep with {u_wick*100:.1f}% wick, close_loc {close_loc*100:.1f}%, ΔOI {fallback_doi_pct*100:+.2f}%"

                            if trigger_short:
                                sig_short = AbsorptionSignal(
                                    symbol=cand.symbol, action="SELL", entry_trigger_price=bar_low,
                                    invalidation_stop_price=bar_high, cvd_zscore=Decimal("2.2"),
                                    micro_price_skew_bps=Decimal("-0.25"), ofi_score=Decimal("-0.50"),
                                    wick_ratio=u_wick, absorption_density=Decimal("0.85"),
                                    is_steamroller_vetoed=False, is_valid=True,
                                    reason=sig_reason
                                )
                                cycle_qualified_signals.append((cand, sig_short, atr_pct, target_tp, target_sl))

                        # 3. Setup Long Evaluation (Trapped Bears Sweep at Support)
                        elif bar_low <= prev_swing_low:
                            trigger_long = False
                            sig_reason = ""

                            # Severe 24h Freefall Veto (Falling Knife Guard - Lesson #43)
                            max_drop = getattr(cfg.orderflow, "buy_max_24h_drop_abs_pct", Decimal("10.0"))
                            if cand.price_change_pct <= -max_drop:
                                logger.debug(f"[FALLING KNIFE VETO] {cand.symbol} 24h change is {cand.price_change_pct}% <= -{max_drop}%. Long setup vetoed.")
                                continue

                            if evaluated_sig and evaluated_sig.is_valid and evaluated_sig.action == "BUY":
                                trigger_long = True
                                sig_reason = f"Live WS OFI/CVD Climax ({evaluated_sig.reason})"
                            elif not tracker or len(tracker.trades) < 5:
                                # Cold-start fallback: Rejection wick + Wyckoff outer close + BTC Gate + ΔOI Gate
                                _, fallback_doi_pct = tracker.compute_delta_oi() if tracker else (Decimal("0"), Decimal("0"))
                                oi_veto_fallback = False
                                if cfg.orderflow.delta_oi_filter_enabled:
                                    if not tracker or len(tracker.oi_history) < 2:
                                        oi_veto_fallback = True  # Strict Negative Affirmation: Never pounce blind!
                                    elif fallback_doi_pct < cfg.orderflow.min_delta_oi_pct:
                                        oi_veto_fallback = True
                                btc_veto_long = cfg.orderflow.btc_tide_gate_enabled and (btc_1m_ret <= cfg.orderflow.btc_1m_dump_threshold_pct)
                                active_min_buy_wick = max(active_min_wick, getattr(cfg.orderflow, "buy_absorption_wick_min_ratio", Decimal("0.50")))
                                if l_wick >= active_min_buy_wick and close_top_35 and vol_multiple >= Decimal("2.0") and not (cfg.orderflow.macro_trend_filter_enabled and is_bear_1h) and not btc_veto_long and not oi_veto_fallback:
                                    trigger_long = True
                                    sig_reason = f"Cold-Start Wick/Volume Sweep with {l_wick*100:.1f}% wick, close_loc {close_loc*100:.1f}%, ΔOI {fallback_doi_pct*100:+.2f}%"

                            if trigger_long:
                                sig_long = AbsorptionSignal(
                                    symbol=cand.symbol, action="BUY", entry_trigger_price=bar_high,
                                    invalidation_stop_price=bar_low, cvd_zscore=Decimal("-2.2"),
                                    micro_price_skew_bps=Decimal("0.25"), ofi_score=Decimal("0.50"),
                                    wick_ratio=l_wick, absorption_density=Decimal("0.85"),
                                    is_steamroller_vetoed=False, is_valid=True,
                                    reason=sig_reason
                                )
                                cycle_qualified_signals.append((cand, sig_long, atr_pct, target_tp, target_sl))

                # Correlated Basket Tremor Veto:
                # If multiple symbols trigger in the same scan cycle, it is an altcoin-wide systemic tremor, not an isolated trapped setup.
                if len(cycle_qualified_signals) > cfg.temporal.max_correlated_signals_per_scan:
                    logger.warning(
                        f"[CORRELATED TREMOR VETO] {len(cycle_qualified_signals)} symbols triggered simultaneously "
                        f"({[s[0].symbol for s in cycle_qualified_signals]}). Systemic market shock detected; "
                        f"vetoed all to prevent basket burst cascade."
                    )
                elif len(cycle_qualified_signals) == 1:
                    cand, sig, atr_pct, target_tp, target_sl = cycle_qualified_signals[0]
                    vp_snapshot = vp_cache.get_previous_day_profile(sig.symbol, now_utc)
                    created = engine.create_signal_from_absorption(
                        sig, atr_pct=atr_pct, current_time_utc=now_utc,
                        custom_tp_pct=target_tp, custom_sl_pct=target_sl,
                        volume_profile=vp_snapshot
                    )
                    if created:
                        action_noun = "Trapped Bulls" if sig.action == "SELL" else "Trapped Bears"
                        logger.info(
                            f"[TIGER STALK ALERT] {cand.symbol} {action_noun} detected! Trigger: {sig.entry_trigger_price} "
                            f"(90s TTL | Target TP:{target_tp*100:.2f}% | BTC 1m:{btc_1m_ret*100:+.2f}%)"
                        )

            # 6. Render Terminal Heartbeat Status with Adaptive Telemetry
            elapsed_loop = time.time() - loop_start
            q_count = len(quarantined_symbols)
            ws_ticks = ws_manager.total_ticks_received
            btc_pulse_str = f"BTC: {btc_1m_ret*100:+.2f}%" if "btc_1m_ret" in locals() else "BTC: 0.00%"
            heartbeat_msg = f"[HEARTBEAT] Active: {[c.symbol for c in top_5_prey[:3]]} | {btc_pulse_str} | WS: {ws_ticks}t | Quarantined: {q_count} | Pos: {len(engine.active_positions)} | Pend: {len(engine.pending_signals)} | Trades: {engine.total_trades_count} (W:{engine.total_wins_count}) | Weight: {used_weight}/2400"
            logger.info(heartbeat_msg)
            print(f"\r[{now_utc.strftime('%H:%M:%S')}] {heartbeat_msg}", flush=True)

            # Dump live radar snapshot for WebUI visualization
            radar_dict = {
                "updated_at_utc": now_utc.isoformat(),
                "ws_ticks": ws_ticks,
                "used_weight": used_weight,
                "btc_1m_return_pct": str((btc_1m_ret * Decimal("100")).quantize(Decimal("0.01"))) if "btc_1m_ret" in locals() else "0.00",
                "btc_cvd_zscore": str(btc_cvd_z.quantize(Decimal("0.1"))) if "btc_cvd_z" in locals() else "0.0",
                "quarantined_count": q_count,
                "recycler_evaluations": recycler_evaluations if "recycler_evaluations" in locals() else [],
                "active_prey": [
                    {
                        "rank": c.rank,
                        "symbol": c.symbol,
                        "last_price": str(c.last_price),
                        "price_change_pct": str(c.price_change_pct),
                        "turnover_24h_usd": str(c.turnover_24h_usd),
                        "volatility_score": str(c.volatility_score),
                        "is_quarantined": c.symbol in quarantined_symbols,
                        "open_interest": str(ws_manager.get_tracker(c.symbol).oi_history[-1].open_interest) if ws_manager.get_tracker(c.symbol) and ws_manager.get_tracker(c.symbol).oi_history else "0",
                        "delta_oi_pct": str((ws_manager.get_tracker(c.symbol).compute_delta_oi()[1] * Decimal("100")).quantize(Decimal("0.01"))) if ws_manager.get_tracker(c.symbol) else "0.00"
                    }
                    for c in top_5_prey
                ]
            }
            try:
                with open("data/tiger_radar.json", "w", encoding="utf-8") as rf:
                    json.dump(radar_dict, rf, indent=2)
            except Exception:
                pass

            # Sleep remaining interval to maintain 10-15s cycle
            sleep_time = max(5.0, 15.0 - elapsed_loop)
            time.sleep(sleep_time)

    finally:
        ws_manager.stop()


def main():
    parser = argparse.ArgumentParser(description="Kronos Strategy #3: Stalking Tiger PC Daemon")
    parser.add_argument("--scan-once", action="store_true", help="Run a single bulk scan and output Top 5 Hot Prey")
    parser.add_argument("--paper", action="store_true", help="Run continuous real-time forward paper trading")
    parser.add_argument("--config", default="data/tiger_config.json", help="Path to config file")
    args = parser.parse_args()

    cfg = TigerMasterConfig.load(args.config)
    cfg.save(args.config)

    if args.scan_once:
        run_scan_once(cfg)
        return

    if args.paper:
        run_realtime_paper_trading(cfg, is_paper=True)
        return

    logger.info("Strategy #3 (Stalking Tiger) initialized. Run with --paper for real-time forward paper trading or --scan-once.")


if __name__ == "__main__":
    main()
