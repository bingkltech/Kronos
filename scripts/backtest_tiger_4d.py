"""
scripts/backtest_tiger_4d.py — 4-Day Empirical Microstructure Backtest for Strategy #3 (Stalking Tiger).

Fetches continuous 1m Binance Futures candlestick data (5,760 bars per symbol = 4 days),
simulating orderflow absorption, 90s signal TTL, the 8-12-15m temporal decay ladder,
dual-regime brackets (+1.01%/-0.66% and +1.90%/-1.10%), and 5-loss circuit breaker.
Enforces strict AGENTS.md Invariant 1 (Zero Float Financial Math with Decimal).
"""

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
import json
import os
import sys
import time
from typing import Any, Dict, List, Optional, Tuple
import urllib.request
import urllib.error

# Add repository root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.quant.tiger_config import TigerMasterConfig, DEFAULT_TIGER_CONFIG

SYMBOLS = ["SOLUSDT", "DOGEUSDT", "BTCUSDT", "ETHUSDT"]
DAYS_TO_TEST = 4
BARS_NEEDED = DAYS_TO_TEST * 24 * 60  # 5,760 1-minute bars per symbol

INITIAL_EQUITY = Decimal("200.00")    # $200 standard test capital
MARGIN_PER_TRADE = Decimal("20.00")   # $20 margin per trade
LEVERAGE = Decimal("5")               # 5x leverage
NOTIONAL_PER_TRADE = MARGIN_PER_TRADE * LEVERAGE  # $100 notional
FEE_FRICTION_PCT = Decimal("0.0009")  # 0.09% roundtrip (VIP0 maker+taker+slippage)


@dataclass
class TradeRecord:
    symbol: str
    side: str
    entry_bar: int
    exit_bar: int
    duration_bars: int
    entry_price: Decimal
    exit_price: Decimal
    gross_pnl_pct: Decimal
    net_pnl_pct: Decimal
    net_pnl_usd: Decimal
    exit_reason: str
    is_win: bool
    is_slow_regime: bool


def fetch_historical_1m_klines(symbol: str, total_bars: int = BARS_NEEDED) -> List[List[Any]]:
    """
    Fetches continuous historical 1m klines backwards from Binance USD(S)-M public REST API.
    Uses 1,500 limit pagination.
    """
    all_klines: List[List[Any]] = []
    end_time = int(time.time() * 1000)
    batches_needed = (total_bars // 1500) + 1

    for _ in range(batches_needed):
        url = f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval=1m&limit=1500&endTime={end_time}"
        req = urllib.request.Request(url, headers={"User-Agent": "Kronos-TigerBacktest/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                batch = json.loads(resp.read().decode("utf-8"))
                if not batch:
                    break
                all_klines = batch + all_klines
                end_time = batch[0][0] - 1
                if len(all_klines) >= total_bars:
                    break
        except Exception as e:
            print(f"  [WARN] Failed to fetch batch for {symbol}: {e}")
            break
        time.sleep(0.1)  # Gentle 100ms throttle

    # Slice exact required tail
    return all_klines[-total_bars:]


def run_tiger_simulation(symbol: str, klines: List[List[Any]], cfg: TigerMasterConfig) -> Tuple[List[TradeRecord], List[TradeRecord]]:
    """
    Runs the 4-day backtest simulation on continuous 1m bars.
    Returns:
        (tiger_trades, naive_trades)
    """
    tiger_trades: List[TradeRecord] = []
    naive_trades: List[TradeRecord] = []

    opens = [Decimal(str(k[1])) for k in klines]
    highs = [Decimal(str(k[2])) for k in klines]
    lows = [Decimal(str(k[3])) for k in klines]
    closes = [Decimal(str(k[4])) for k in klines]
    volumes = [Decimal(str(k[5])) for k in klines]

    n_bars = len(closes)
    if n_bars < 100:
        return tiger_trades, naive_trades

    # State trackers
    in_tiger_trade = False
    tiger_pos_side = ""
    tiger_entry_price = Decimal("0")
    tiger_tp_price = Decimal("0")
    tiger_sl_price = Decimal("0")
    tiger_entry_bar = 0
    tiger_is_slow = True
    tiger_be_ratcheted = False
    consecutive_losses = 0
    pause_until_bar = 0

    in_naive_trade = False
    naive_pos_side = ""
    naive_entry_price = Decimal("0")
    naive_tp_price = Decimal("0")
    naive_sl_price = Decimal("0")
    naive_entry_bar = 0
    naive_is_slow = True

    # Pending signal TTL tracker
    pending_signal: Optional[Dict[str, Any]] = None

    for i in range(30, n_bars - 15):
        current_open = opens[i]
        current_high = highs[i]
        current_low = lows[i]
        current_close = closes[i]
        current_vol = volumes[i]

        # 1. Rolling 15m ATR % calculation
        tr_list = [max(highs[j] - lows[j], abs(highs[j] - closes[j-1]), abs(lows[j] - closes[j-1])) for j in range(i-14, i+1)]
        atr_15 = sum(tr_list) / Decimal("15")
        atr_pct = atr_15 / current_close if current_close > Decimal("0") else Decimal("0")
        is_slow = atr_pct < cfg.brackets.slow_vol_atr_threshold_pct

        # Active brackets
        tp_pct = cfg.brackets.slow_vol_tp_price_pct if is_slow else cfg.brackets.fast_vol_tp_price_pct
        sl_pct = cfg.brackets.slow_vol_sl_price_pct if is_slow else cfg.brackets.fast_vol_sl_price_pct

        # ----------------------------------------------------------------------
        # A. MANAGE ACTIVE TIGER POSITION (The 8-12-15m Temporal Ladder)
        # ----------------------------------------------------------------------
        if in_tiger_trade:
            duration = i - tiger_entry_bar
            exit_reason = None
            exit_price = current_close

            # Gross PnL %
            if tiger_pos_side == "BUY":
                pnl_pct = (current_close - tiger_entry_price) / tiger_entry_price
                # Check TP
                if current_high >= tiger_tp_price:
                    exit_reason = "TAKE_PROFIT"
                    exit_price = tiger_tp_price
                # Check SL
                elif current_low <= tiger_sl_price:
                    exit_reason = "STOP_LOSS"
                    exit_price = tiger_sl_price
            else:
                pnl_pct = (tiger_entry_price - current_close) / tiger_entry_price
                # Check TP
                if current_low <= tiger_tp_price:
                    exit_reason = "TAKE_PROFIT"
                    exit_price = tiger_tp_price
                # Check SL
                elif current_high >= tiger_sl_price:
                    exit_reason = "STOP_LOSS"
                    exit_price = tiger_sl_price

            # Temporal Decay Ladder:
            if not exit_reason:
                # Minute 8: Velocity check (Ratchet to breakeven + fees)
                if duration >= cfg.temporal.velocity_check_minutes and not tiger_be_ratcheted:
                    if pnl_pct >= cfg.temporal.velocity_min_gain_pct:
                        if tiger_pos_side == "BUY":
                            tiger_sl_price = tiger_entry_price * (Decimal("1") + FEE_FRICTION_PCT)
                        else:
                            tiger_sl_price = tiger_entry_price * (Decimal("1") - FEE_FRICTION_PCT)
                        tiger_be_ratcheted = True

                # Minute 12: Stall / Chop Scratch Exit
                if duration >= cfg.temporal.stall_scratch_minutes:
                    if cfg.temporal.stall_band_low_pct <= pnl_pct <= cfg.temporal.stall_band_high_pct:
                        exit_reason = "STALL_SCRATCH"
                        exit_price = current_close

                # Minute 15: Hard Temporal Kill
                if duration >= cfg.temporal.hard_temporal_expiry_minutes:
                    exit_reason = "HARD_KILL"
                    exit_price = current_close

            # Process exit
            if exit_reason:
                if tiger_pos_side == "BUY":
                    gross_ret = (exit_price - tiger_entry_price) / tiger_entry_price
                else:
                    gross_ret = (tiger_entry_price - exit_price) / tiger_entry_price

                net_ret = gross_ret - FEE_FRICTION_PCT
                net_usd = NOTIONAL_PER_TRADE * net_ret
                is_win = net_usd > Decimal("0")

                if is_win:
                    consecutive_losses = 0
                else:
                    consecutive_losses += 1
                    if consecutive_losses >= cfg.brackets.consecutive_loss_pause_count:
                        pause_until_bar = i + cfg.brackets.consecutive_loss_cooldown_minutes

                tiger_trades.append(TradeRecord(
                    symbol=symbol, side=tiger_pos_side, entry_bar=tiger_entry_bar,
                    exit_bar=i, duration_bars=duration, entry_price=tiger_entry_price,
                    exit_price=exit_price, gross_pnl_pct=gross_ret, net_pnl_pct=net_ret,
                    net_pnl_usd=net_usd, exit_reason=exit_reason, is_win=is_win,
                    is_slow_regime=tiger_is_slow
                ))
                in_tiger_trade = False

        # ----------------------------------------------------------------------
        # B. MANAGE BENCHMARK NAIVE POSITION (No Time-Stop, holds until TP or SL)
        # ----------------------------------------------------------------------
        if in_naive_trade:
            duration_n = i - naive_entry_bar
            exit_reason_n = None
            exit_price_n = current_close

            if naive_pos_side == "BUY":
                if current_high >= naive_tp_price:
                    exit_reason_n = "TAKE_PROFIT"
                    exit_price_n = naive_tp_price
                elif current_low <= naive_sl_price:
                    exit_reason_n = "STOP_LOSS"
                    exit_price_n = naive_sl_price
            else:
                if current_low <= naive_tp_price:
                    exit_reason_n = "TAKE_PROFIT"
                    exit_price_n = naive_tp_price
                elif current_high >= naive_sl_price:
                    exit_reason_n = "STOP_LOSS"
                    exit_price_n = naive_sl_price

            if exit_reason_n:
                if naive_pos_side == "BUY":
                    gross_ret_n = (exit_price_n - naive_entry_price) / naive_entry_price
                else:
                    gross_ret_n = (naive_entry_price - exit_price_n) / naive_entry_price

                net_ret_n = gross_ret_n - FEE_FRICTION_PCT
                net_usd_n = NOTIONAL_PER_TRADE * net_ret_n

                naive_trades.append(TradeRecord(
                    symbol=symbol, side=naive_pos_side, entry_bar=naive_entry_bar,
                    exit_bar=i, duration_bars=duration_n, entry_price=naive_entry_price,
                    exit_price=exit_price_n, gross_pnl_pct=gross_ret_n, net_pnl_pct=net_ret_n,
                    net_pnl_usd=net_usd_n, exit_reason=exit_reason_n, is_win=net_usd_n > Decimal("0"),
                    is_slow_regime=naive_is_slow
                ))
                in_naive_trade = False

        # ----------------------------------------------------------------------
        # C. PROCESS PENDING SIGNAL TTL (90s / 1-2 bars)
        # ----------------------------------------------------------------------
        if pending_signal and not in_tiger_trade:
            # Check if 90s TTL exceeded (2 bars)
            if i - pending_signal["bar"] > 2:
                pending_signal = None  # Signal expired, prey escaped!
            else:
                # Check for fill at trigger price
                trigger_price = pending_signal["trigger_price"]
                fill = False
                if pending_signal["side"] == "SELL" and current_low <= trigger_price:
                    fill = True
                elif pending_signal["side"] == "BUY" and current_high >= trigger_price:
                    fill = True

                if fill and i >= pause_until_bar:
                    # Tiger enters position!
                    in_tiger_trade = True
                    tiger_pos_side = pending_signal["side"]
                    tiger_entry_price = trigger_price
                    tiger_tp_price = pending_signal["tp_price"]
                    tiger_sl_price = pending_signal["sl_price"]
                    tiger_entry_bar = i
                    tiger_is_slow = pending_signal["is_slow"]
                    tiger_be_ratcheted = False

                    # Also enter Naive benchmark
                    if not in_naive_trade:
                        in_naive_trade = True
                        naive_pos_side = pending_signal["side"]
                        naive_entry_price = trigger_price
                        naive_tp_price = pending_signal["tp_price"]
                        naive_sl_price = pending_signal["sl_price"]
                        naive_entry_bar = i
                        naive_is_slow = pending_signal["is_slow"]

                    pending_signal = None

        # ----------------------------------------------------------------------
        # D. THE STALKING TIGER PREY DETECTION (Orderflow Absorption Climax)
        # ----------------------------------------------------------------------
        if not in_tiger_trade and not pending_signal and i >= pause_until_bar:
            avg_vol_20 = sum(volumes[i-20:i]) / Decimal("20")
            prev_swing_high = max(highs[i-15:i])
            prev_swing_low = min(lows[i-15:i])
            bar_range = current_high - current_low

            if bar_range > Decimal("0") and avg_vol_20 > Decimal("0"):
                vol_multiple = current_vol / avg_vol_20
                body = abs(current_close - current_open)
                body_ratio = body / bar_range

                # Anti-Steamroller Guard (Institutional freight train veto)
                is_steamroller = (vol_multiple >= cfg.orderflow.steamroller_vol_multiplier and body_ratio >= Decimal("0.80"))

                if not is_steamroller and vol_multiple >= Decimal("1.80"):
                    # Case 1: Trapped Bulls (Swing High Sweep + Upper Rejection Wick >= 40%)
                    upper_wick = current_high - max(current_open, current_close)
                    upper_wick_ratio = upper_wick / bar_range

                    if current_high >= prev_swing_high and upper_wick_ratio >= cfg.orderflow.absorption_wick_min_ratio:
                        # Setup Short
                        pending_signal = {
                            "bar": i,
                            "side": "SELL",
                            "trigger_price": current_low,
                            "tp_price": current_low * (Decimal("1") - tp_pct),
                            "sl_price": current_low * (Decimal("1") + sl_pct),
                            "is_slow": is_slow
                        }

                    # Case 2: Trapped Bears (Swing Low Sweep + Lower Rejection Wick >= 40%)
                    lower_wick = min(current_open, current_close) - current_low
                    lower_wick_ratio = lower_wick / bar_range

                    if current_low <= prev_swing_low and lower_wick_ratio >= cfg.orderflow.absorption_wick_min_ratio:
                        # Setup Long
                        pending_signal = {
                            "bar": i,
                            "side": "BUY",
                            "trigger_price": current_high,
                            "tp_price": current_high * (Decimal("1") + tp_pct),
                            "sl_price": current_high * (Decimal("1") - sl_pct),
                            "is_slow": is_slow
                        }

    return tiger_trades, naive_trades


def summarize_trades(trades: List[TradeRecord], label: str) -> Dict[str, Any]:
    """Computes comprehensive quantitative performance statistics."""
    if not trades:
        return {
            "label": label, "total_trades": 0, "win_rate": 0.0, "net_pnl_usd": Decimal("0"),
            "profit_factor": Decimal("0"), "avg_duration_min": 0.0, "tp_count": 0,
            "sl_count": 0, "scratch_count": 0, "hard_kill_count": 0
        }

    total = len(trades)
    wins = [t for t in trades if t.is_win]
    losses = [t for t in trades if not t.is_win]

    win_rate = (len(wins) / total) * 100.0
    total_net_usd = sum(t.net_pnl_usd for t in trades)

    gross_wins = sum(t.net_pnl_usd for t in wins)
    gross_losses = abs(sum(t.net_pnl_usd for t in losses))
    profit_factor = (gross_wins / gross_losses) if gross_losses > Decimal("0") else Decimal("99.99")

    avg_duration = sum(t.duration_bars for t in trades) / total

    tp_count = sum(1 for t in trades if t.exit_reason == "TAKE_PROFIT")
    sl_count = sum(1 for t in trades if t.exit_reason == "STOP_LOSS")
    scratch_count = sum(1 for t in trades if t.exit_reason == "STALL_SCRATCH")
    hard_kill_count = sum(1 for t in trades if t.exit_reason == "HARD_KILL")

    return {
        "label": label,
        "total_trades": total,
        "win_rate": round(win_rate, 1),
        "total_wins": len(wins),
        "total_losses": len(losses),
        "net_pnl_usd": total_net_usd.quantize(Decimal("0.01")),
        "profit_factor": profit_factor.quantize(Decimal("0.01")),
        "avg_duration_min": round(avg_duration, 1),
        "tp_count": tp_count,
        "sl_count": sl_count,
        "scratch_count": scratch_count,
        "hard_kill_count": hard_kill_count
    }


def main():
    print("\n" + "=" * 92)
    print(f"  STRATEGY #3 (STALKING TIGER) — 4-DAY CONTINUOUS EMPIRICAL BACKTEST")
    print(f"  Data Resolution: 1-Minute Candlesticks | Lookback: {DAYS_TO_TEST} Days ({BARS_NEEDED} Bars/Coin)")
    print(f"  Starting Capital: ${INITIAL_EQUITY} | Margin/Trade: ${MARGIN_PER_TRADE} | Leverage: {LEVERAGE}x")
    print("=" * 92)

    cfg = DEFAULT_TIGER_CONFIG
    all_tiger_trades: List[TradeRecord] = []
    all_naive_trades: List[TradeRecord] = []

    for sym in SYMBOLS:
        print(f"[*] Fetching {BARS_NEEDED} live 1m bars for {sym} from Binance Futures API...")
        klines = fetch_historical_1m_klines(sym, BARS_NEEDED)
        print(f"    Loaded {len(klines)} bars spanning {len(klines)/60:.1f} hours.")

        t_trades, n_trades = run_tiger_simulation(sym, klines, cfg)
        all_tiger_trades.extend(t_trades)
        all_naive_trades.extend(n_trades)
        print(f"    -> {sym} complete: {len(t_trades)} Stalking Tiger trades generated.")

    # Generate comparative statistical summaries
    tiger_summary = summarize_trades(all_tiger_trades, "Strategy #3: Stalking Tiger (8-12-15m Time-Stop)")
    naive_summary = summarize_trades(all_naive_trades, "Baseline: Naive Scalper (No Time-Stop)")

    print("\n" + "=" * 92)
    print("  4-DAY STATISTICAL PERFORMANCE SUMMARY")
    print("=" * 92)
    print(f" {'METRIC':<32} | {'STRATEGY #3: STALKING TIGER':<26} | {'BASELINE: NAIVE SCALPER':<26}")
    print("-" * 92)
    print(f" {'Total Trades Taken':<32} | {tiger_summary['total_trades']:<26} | {naive_summary['total_trades']:<26}")
    print(f" {'Win Rate (%)':<32} | {tiger_summary['win_rate']}% ({tiger_summary['total_wins']}W / {tiger_summary['total_losses']}L) | {naive_summary['win_rate']}% ({naive_summary['total_wins']}W / {naive_summary['total_losses']}L)")
    print(f" {'Net Realized PnL ($)':<32} | ${tiger_summary['net_pnl_usd']:<25} | ${naive_summary['net_pnl_usd']:<25}")
    roi_tiger = (tiger_summary['net_pnl_usd'] / INITIAL_EQUITY) * Decimal("100")
    roi_naive = (naive_summary['net_pnl_usd'] / INITIAL_EQUITY) * Decimal("100")
    print(f" {'Net Account ROI (%)':<32} | {roi_tiger:+.2f}%{'':<20} | {roi_naive:+.2f}%{'':<20}")
    print(f" {'Profit Factor':<32} | {tiger_summary['profit_factor']:<26} | {naive_summary['profit_factor']:<26}")
    print(f" {'Average Hold Duration':<32} | {tiger_summary['avg_duration_min']} minutes{'':<17} | {naive_summary['avg_duration_min']} minutes{'':<17}")
    print("-" * 92)
    print("  EXIT BREAKDOWN (THE 8-12-15 TEMPORAL DISCIPLINE):")
    print(f"   - Take-Profit Hits (+1.01% / +1.90%):    {tiger_summary['tp_count']}")
    print(f"   - Stop-Loss Hits (-0.66% / -1.10%):      {tiger_summary['sl_count']}")
    print(f"   - Minute 12 Stall / Chop Scratches:     {tiger_summary['scratch_count']} (Capital saved from decaying into full SL)")
    print(f"   - Minute 15 Hard Temporal Kills:         {tiger_summary['hard_kill_count']} (Positions flattened at horizon ceiling)")
    print("=" * 92 + "\n")


if __name__ == "__main__":
    main()
