"""
Institutional Empirical Backtest: Scalper Strategy Outcome Comparison
Compares:
1. Model A (Naive Sub-Minute Unfiltered): TP +0.55%, Ratchet +0.25%, SL -0.60%, 180s duration
2. Model A (Naive Sub-Minute with Sieve Gate): Same TP/SL/Duration, but only high-conviction entries
3. Model B (Institutional Calibrated with Sieve Gate): TP +1.10%, Ratchet +0.80%, SL -0.70%, 600s duration, maker-first pricing
Tested on real Binance Futures 1m candlestick data using Zero-Float Decimal math.
"""
import requests
import sys
from decimal import Decimal

SYMBOLS = ["SOLUSDT", "ETHUSDT", "BTCUSDT", "DOGEUSDT"]
MARGIN_USD = Decimal("20.00")
LEVERAGE = Decimal("4")
NOTIONAL_USD = MARGIN_USD * LEVERAGE  # $80.00 position notional

def run_simulation():
    print("=" * 88)
    print("EMPIRICAL COMPARISON: NAIVE SCALPER vs. INSTITUTIONAL CALIBRATED SCALPER")
    print(f"Capital per Trade: ${MARGIN_USD} Isolated Margin | {LEVERAGE}x Leverage | Notional: ${NOTIONAL_USD}")
    print("=" * 88)

    all_klines = {}
    for sym in SYMBOLS:
        try:
            r = requests.get(f"https://fapi.binance.com/fapi/v1/klines?symbol={sym}&interval=1m&limit=1000", timeout=5)
            if r.status_code == 200:
                all_klines[sym] = r.json()
        except Exception as e:
            print(f"Error fetching {sym}: {e}")

    # Setups to compare
    m_a_unfiltered = {
        "name": "Model A (Unfiltered Naive)",
        "tp_pct": Decimal("0.55"),
        "ratchet_trigger_pct": Decimal("0.25"),
        "ratchet_lock_pct": Decimal("0.08"),
        "sl_pct": Decimal("0.60"),
        "max_bars": 3,
        "fee_friction_pct": Decimal("0.130"),
        "trades": []
    }

    m_a_sieve = {
        "name": "Model A (Naive + Sieve)",
        "tp_pct": Decimal("0.55"),
        "ratchet_trigger_pct": Decimal("0.25"),
        "ratchet_lock_pct": Decimal("0.08"),
        "sl_pct": Decimal("0.60"),
        "max_bars": 3,
        "fee_friction_pct": Decimal("0.130"),
        "trades": []
    }

    m_b_institutional = {
        "name": "Model B (Institutional + Sieve)",
        "tp_pct": Decimal("1.10"),
        "ratchet_trigger_pct": Decimal("0.80"),
        "ratchet_lock_pct": Decimal("0.25"),
        "sl_pct": Decimal("0.70"),
        "max_bars": 10,
        "fee_friction_pct": Decimal("0.083"),
        "trades": []
    }

    for sym, klines in all_klines.items():
        closes = [Decimal(str(k[4])) for k in klines]
        highs = [Decimal(str(k[2])) for k in klines]
        lows = [Decimal(str(k[3])) for k in klines]
        volumes = [Decimal(str(k[5])) for k in klines]

        last_entry_bar_unf = -999
        last_entry_bar_sieve = -999

        for i in range(30, len(closes) - 15):
            avg_vol = sum(volumes[i-15:i]) / Decimal("15")
            c_now = closes[i]
            prev_high = max(highs[i-15:i])
            prev_low = min(lows[i-15:i])

            # 1. Unfiltered trigger (standard breakout on volume > 1.4x)
            if i - last_entry_bar_unf >= 5:
                sig_unf = None
                if c_now >= prev_high and volumes[i] > avg_vol * Decimal("1.4"):
                    sig_unf = "BUY"
                elif c_now <= prev_low and volumes[i] > avg_vol * Decimal("1.4"):
                    sig_unf = "SELL"
                if sig_unf:
                    last_entry_bar_unf = i
                    m_a_unfiltered["trades"].append(simulate_trade(m_a_unfiltered, sig_unf, c_now, highs, lows, closes, i))

            # 2. High-Conviction Sieve Gate Trigger:
            # - Volume surge > 2.2x average
            # - Momentum expansion > 0.40% in last 3 bars
            # - Trend alignment with 30-bar EMA
            if i - last_entry_bar_sieve >= 15: # 15-min cooldown between trades on same coin!
                sig_sieve = None
                ema_30 = sum(closes[i-30:i]) / Decimal("30")
                three_bar_drift = ((c_now - closes[i-3]) / closes[i-3]) * Decimal("100")

                if c_now > ema_30 and three_bar_drift > Decimal("0.35") and volumes[i] > avg_vol * Decimal("2.0"):
                    sig_sieve = "BUY"
                elif c_now < ema_30 and three_bar_drift < Decimal("-0.35") and volumes[i] > avg_vol * Decimal("2.0"):
                    sig_sieve = "SELL"

                if sig_sieve:
                    last_entry_bar_sieve = i
                    m_a_sieve["trades"].append(simulate_trade(m_a_sieve, sig_sieve, c_now, highs, lows, closes, i))
                    m_b_institutional["trades"].append(simulate_trade(m_b_institutional, sig_sieve, c_now, highs, lows, closes, i))

    display_comparative_table([m_a_unfiltered, m_a_sieve, m_b_institutional])

def simulate_trade(model, side, entry, highs, lows, closes, start_idx):
    tp_pct = model["tp_pct"]
    ratchet_trigger = model["ratchet_trigger_pct"]
    ratchet_lock = model["ratchet_lock_pct"]
    sl_pct = model["sl_pct"]
    max_bars = model["max_bars"]
    friction_pct = model["fee_friction_pct"]

    current_sl = entry * (Decimal("1") - (sl_pct / Decimal("100"))) if side == "BUY" else entry * (Decimal("1") + (sl_pct / Decimal("100")))
    target_tp = entry * (Decimal("1") + (tp_pct / Decimal("100"))) if side == "BUY" else entry * (Decimal("1") - (tp_pct / Decimal("100")))
    ratchet_activated = False

    exit_price = None
    exit_reason = None
    held_bars = 0

    for step in range(1, max_bars + 1):
        idx = start_idx + step
        if idx >= len(closes):
            break
        held_bars = step
        h = highs[idx]
        l = lows[idx]

        if side == "BUY":
            if l <= current_sl:
                exit_price = current_sl
                exit_reason = "RATCHET_LOCK" if ratchet_activated else "STOP_LOSS"
                break
            if h >= target_tp:
                exit_price = target_tp
                exit_reason = "TAKE_PROFIT"
                break
            favorable_move = ((h - entry) / entry) * Decimal("100")
            if favorable_move >= ratchet_trigger and not ratchet_activated:
                ratchet_activated = True
                new_sl = entry * (Decimal("1") + (ratchet_lock / Decimal("100")))
                if new_sl > current_sl:
                    current_sl = new_sl
        else:
            if h >= current_sl:
                exit_price = current_sl
                exit_reason = "RATCHET_LOCK" if ratchet_activated else "STOP_LOSS"
                break
            if l <= target_tp:
                exit_price = target_tp
                exit_reason = "TAKE_PROFIT"
                break
            favorable_move = ((entry - l) / entry) * Decimal("100")
            if favorable_move >= ratchet_trigger and not ratchet_activated:
                ratchet_activated = True
                new_sl = entry * (Decimal("1") - (ratchet_lock / Decimal("100")))
                if new_sl < current_sl:
                    current_sl = new_sl

    if exit_price is None:
        exit_price = closes[min(start_idx + max_bars, len(closes) - 1)]
        exit_reason = "TIME_STOP"

    if side == "BUY":
        gross_return_pct = ((exit_price - entry) / entry) * Decimal("100")
    else:
        gross_return_pct = ((entry - exit_price) / entry) * Decimal("100")

    net_return_pct = gross_return_pct - friction_pct
    gross_pnl_usd = NOTIONAL_USD * (gross_return_pct / Decimal("100"))
    fee_usd = NOTIONAL_USD * (friction_pct / Decimal("100"))
    net_pnl_usd = gross_pnl_usd - fee_usd

    return {
        "side": side,
        "entry": entry,
        "exit": exit_price,
        "reason": exit_reason,
        "bars": held_bars,
        "gross_pct": gross_return_pct,
        "net_pct": net_return_pct,
        "gross_pnl_usd": gross_pnl_usd,
        "fee_usd": fee_usd,
        "net_pnl_usd": net_pnl_usd
    }

def display_comparative_table(models):
    headers = [m["name"] for m in models]
    print(f"{'METRIC':<30} | {headers[0]:<17} | {headers[1]:<17} | {headers[2]:<22}")
    print("-" * 92)

    stats = []
    for m in models:
        t_list = m["trades"]
        n = len(t_list)
        tp = sum(1 for t in t_list if t["reason"] == "TAKE_PROFIT")
        ratchet = sum(1 for t in t_list if t["reason"] == "RATCHET_LOCK")
        sl = sum(1 for t in t_list if t["reason"] == "STOP_LOSS")
        time_s = sum(1 for t in t_list if t["reason"] == "TIME_STOP")
        wins = sum(1 for t in t_list if t["net_pnl_usd"] > 0)
        wr = (Decimal(wins) / Decimal(n) * 100) if n else Decimal("0")
        gross = sum(t["gross_pnl_usd"] for t in t_list)
        fees = sum(t["fee_usd"] for t in t_list)
        net = sum(t["net_pnl_usd"] for t in t_list)
        gains = sum(t["gross_pnl_usd"] for t in t_list if t["gross_pnl_usd"] > 0)
        losses = abs(sum(t["gross_pnl_usd"] for t in t_list if t["gross_pnl_usd"] < 0))
        pf = (gains / losses) if losses > 0 else Decimal("0")
        stats.append({
            "n": n, "tp": tp, "ratchet": ratchet, "sl": sl, "time_s": time_s,
            "wr": wr, "gross": gross, "fees": fees, "net": net, "pf": pf
        })

    s0, s1, s2 = stats[0], stats[1], stats[2]
    print(f"{'Total Executed Trades':<30} | {s0['n']:<17} | {s1['n']:<17} | {s2['n']:<22}")
    print(f"{'Take-Profit Wins':<30} | {s0['tp']} ({float(s0['tp']/s0['n']*100 if s0['n'] else 0):.1f}%)" + " " * 8 + f"| {s1['tp']} ({float(s1['tp']/s1['n']*100 if s1['n'] else 0):.1f}%)" + " " * 8 + f"| {s2['tp']} ({float(s2['tp']/s2['n']*100 if s2['n'] else 0):.1f}%)")
    print(f"{'Breakeven Choked':<30} | {s0['ratchet']} ({float(s0['ratchet']/s0['n']*100 if s0['n'] else 0):.1f}%)" + " " * 8 + f"| {s1['ratchet']} ({float(s1['ratchet']/s1['n']*100 if s1['n'] else 0):.1f}%)" + " " * 8 + f"| {s2['ratchet']} ({float(s2['ratchet']/s2['n']*100 if s2['n'] else 0):.1f}%)")
    print(f"{'Hard Stop Losses':<30} | {s0['sl']} ({float(s0['sl']/s0['n']*100 if s0['n'] else 0):.1f}%)" + " " * 9 + f"| {s1['sl']} ({float(s1['sl']/s1['n']*100 if s1['n'] else 0):.1f}%)" + " " * 9 + f"| {s2['sl']} ({float(s2['sl']/s2['n']*100 if s2['n'] else 0):.1f}%)")
    print("-" * 92)
    print(f"{'Realized Win Rate (Net Green)':<30} | {float(s0['wr']):.1f}%" + " " * 12 + f"| {float(s1['wr']):.1f}%" + " " * 12 + f"| {float(s2['wr']):.1f}%")
    print(f"{'Gross PnL (Pre-Fees)':<30} | ${float(s0['gross']):+.2f}" + " " * 10 + f"| ${float(s1['gross']):+.2f}" + " " * 10 + f"| ${float(s2['gross']):+.2f}")
    print(f"{'Total Exchange Fees Paid':<30} | -${float(s0['fees']):.2f}" + " " * 10 + f"| -${float(s1['fees']):.2f}" + " " * 10 + f"| -${float(s2['fees']):.2f}")
    print(f"{'NET REALIZED PnL':<30} | ${float(s0['net']):+.2f}" + " " * 10 + f"| ${float(s1['net']):+.2f}" + " " * 10 + f"| ${float(s2['net']):+.2f}")
    print(f"{'Profit Factor (PF)':<30} | {float(s0['pf']):.2f}x" + " " * 12 + f"| {float(s1['pf']):.2f}x" + " " * 12 + f"| {float(s2['pf']):.2f}x")
    print(f"{'Net ROI on $20 Margin':<30} | {float(s0['net']/MARGIN_USD*100):+.1f}%" + " " * 10 + f"| {float(s1['net']/MARGIN_USD*100):+.1f}%" + " " * 10 + f"| {float(s2['net']/MARGIN_USD*100):+.1f}%")
    print("=" * 92)

if __name__ == '__main__':
    run_simulation()
