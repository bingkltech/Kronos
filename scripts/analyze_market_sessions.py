"""
scripts/analyze_market_sessions.py - Deep analysis of session opens/closes (Asia, EU, US) on 276 live trades.
"""
import json
import datetime
from decimal import Decimal

def categorize_session(dt_utc):
    h = dt_utc.hour
    m = dt_utc.minute
    t_min = h * 60 + m

    # Asia: 00:00 - 08:00 UTC (0 - 480)
    # Europe: 08:00 - 13:30 UTC (480 - 810)
    # US/EU Overlap: 13:30 - 16:30 UTC (810 - 990)
    # US Afternoon: 16:30 - 21:00 UTC (990 - 1260)
    # Post-Close/Quiet: 21:00 - 24:00 UTC (1260 - 1440)

    if 0 <= t_min < 480:
        session = "1_ASIA (00-08 UTC)"
    elif 480 <= t_min < 810:
        session = "2_EUROPE (08-13:30 UTC)"
    elif 810 <= t_min < 990:
        session = "3_US_EU_OVERLAP (13:30-16:30 UTC)"
    elif 990 <= t_min < 1260:
        session = "4_US_AFTERNOON (16:30-21 UTC)"
    else:
        session = "5_POST_US_CLOSE (21-24 UTC)"

    # Check proximity to major opens (within +/- 45 mins)
    # Asia open: 00:00 UTC
    # EU open: 08:00 UTC (480 min)
    # US open: 14:30 UTC (870 min)
    # US close: 21:00 UTC (1260 min)
    open_window = "NORMAL_HOURS"
    if t_min <= 45 or t_min >= 1395:
        open_window = "ASIA_OPEN (00:00 UTC)"
    elif abs(t_min - 480) <= 45:
        open_window = "EU_OPEN (08:00 UTC)"
    elif abs(t_min - 870) <= 45:
        open_window = "US_CASH_OPEN (14:30 UTC)"
    elif abs(t_min - 1260) <= 45:
        open_window = "US_CLOSE (21:00 UTC)"

    return session, open_window

def main():
    with open("data/live_audit_summary.json", "r") as f:
        data = json.load(f)

    all_trades = []
    for t in data["macro_trades"]:
        t["strat"] = "MACRO"
        all_trades.append(t)
    for t in data["scalp_trades"]:
        t["strat"] = "SCALP"
        all_trades.append(t)

    print(f"Loaded {len(all_trades)} total live real-money trades.")

    # 1. Hourly Breakdown (0-23 UTC)
    hourly = {h: {"count": 0, "wins": 0, "net": Decimal("0"), "gross": Decimal("0"), "fee": Decimal("0")} for h in range(24)}
    
    # 2. Session Breakdown
    sessions = {}
    
    # 3. Market Open Windows
    windows = {}

    for t in all_trades:
        e_time = datetime.datetime.fromisoformat(t["entry_time"])
        h = e_time.hour
        hourly[h]["count"] += 1
        net = Decimal(t["net_pnl"])
        gross = Decimal(t["gross_pnl"])
        fee = Decimal(t["fee"])
        is_win = net > 0

        if is_win:
            hourly[h]["wins"] += 1
        hourly[h]["net"] += net
        hourly[h]["gross"] += gross
        hourly[h]["fee"] += fee

        sess, win = categorize_session(e_time)
        if sess not in sessions:
            sessions[sess] = {"count": 0, "wins": 0, "net": Decimal("0"), "gross": Decimal("0"), "fee": Decimal("0")}
        sessions[sess]["count"] += 1
        if is_win:
            sessions[sess]["wins"] += 1
        sessions[sess]["net"] += net
        sessions[sess]["gross"] += gross
        sessions[sess]["fee"] += fee

        if win not in windows:
            windows[win] = {"count": 0, "wins": 0, "net": Decimal("0"), "gross": Decimal("0"), "fee": Decimal("0")}
        windows[win]["count"] += 1
        if is_win:
            windows[win]["wins"] += 1
        windows[win]["net"] += net
        windows[win]["gross"] += gross
        windows[win]["fee"] += fee

    print("\n" + "=" * 80)
    print("SESSION PERFORMANCE BREAKDOWN (UTC)")
    print("=" * 80)
    print(f"{'Session Name':<32} | {'Trades':<6} | {'WinRate':<7} | {'Gross PnL':<10} | {'Fees':<8} | {'Net PnL':<10} | {'ProfitFac':<9}")
    print("-" * 92)
    for sess, s_data in sorted(sessions.items()):
        wr = (s_data["wins"] / s_data["count"] * 100) if s_data["count"] else 0
        pf = (s_data["gross"] / (s_data["fee"] + abs(min(Decimal("0"), s_data["gross"])))) if s_data["fee"] else Decimal("0")
        print(f"{sess:<32} | {s_data['count']:<6} | {wr:>6.1f}% | ${s_data['gross']:>8.4f} | ${s_data['fee']:>6.4f} | ${s_data['net']:>8.4f} | {pf:>8.2f}x")

    print("\n" + "=" * 80)
    print("MARKET OPEN / CLOSE WINDOW IMPACT (+/- 45 Minutes of Session Belts)")
    print("=" * 80)
    print(f"{'Market Belt Window':<32} | {'Trades':<6} | {'WinRate':<7} | {'Gross PnL':<10} | {'Fees':<8} | {'Net PnL':<10}")
    print("-" * 85)
    for win, w_data in sorted(windows.items(), key=lambda x: x[1]["net"], reverse=True):
        wr = (w_data["wins"] / w_data["count"] * 100) if w_data["count"] else 0
        print(f"{win:<32} | {w_data['count']:<6} | {wr:>6.1f}% | ${w_data['gross']:>8.4f} | ${w_data['fee']:>6.4f} | ${w_data['net']:>8.4f}")

    print("\n" + "=" * 80)
    print("HOURLY HEATMAP (UTC Hours 00 to 23)")
    print("=" * 80)
    print("Hour | Trades | WinRate | Gross PnL  | Fees     | Net PnL    | Alpha Status")
    print("-" * 75)
    for h in range(24):
        h_data = hourly[h]
        if h_data["count"] == 0:
            continue
        wr = (h_data["wins"] / h_data["count"] * 100) if h_data["count"] else 0
        status = "ALPHA SURGE" if h_data["net"] > Decimal("1.0") else ("PROFITABLE" if h_data["net"] > Decimal("0") else "BLEED")
        print(f"{h:02d}:00 | {h_data['count']:>6} | {wr:>6.1f}% | ${h_data['gross']:>9.4f} | ${h_data['fee']:>8.4f} | ${h_data['net']:>9.4f} | {status}")

if __name__ == "__main__":
    main()
