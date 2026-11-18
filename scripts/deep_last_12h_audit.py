import json
import datetime
from decimal import Decimal

def analyze_last_12h():
    with open("data/live_audit_summary.json", "r") as f:
        data = json.load(f)

    # Current time is roughly 2026-11-16 15:15:00 UTC
    now_utc = datetime.datetime(2026, 11, 16, 15, 15, 0, tzinfo=datetime.timezone.utc)
    twelve_hours_ago = now_utc - datetime.timedelta(hours=12)
    twenty_four_hours_ago = now_utc - datetime.timedelta(hours=24)

    print(f"Current Audit Time UTC: {now_utc.isoformat()}")
    print(f"12-Hour Cutoff UTC:     {twelve_hours_ago.isoformat()}")
    print(f"24-Hour Cutoff UTC:     {twenty_four_hours_ago.isoformat()}\n")

    for strat_name, key in [("MACRO SWING", "macro_trades"), ("LIGHTNING SCALP", "scalp_trades")]:
        trades = data[key]
        print("=" * 80)
        print(f"STRATEGY: {strat_name} (Total Historical: {len(trades)} trades)")
        print("=" * 80)

        # Parse close times
        # trades have "exit_time"
        for window_name, cutoff in [("LAST 12 HOURS", twelve_hours_ago), ("LAST 24 HOURS", twenty_four_hours_ago)]:
            window_trades = []
            for t in trades:
                t_exit_str = t.get("exit_time")
                if not t_exit_str:
                    continue
                try:
                    t_exit = datetime.datetime.fromisoformat(t_exit_str)
                    if t_exit >= cutoff:
                        window_trades.append(t)
                except Exception as e:
                    pass

            print(f"\n--- {window_name} (Closed: {len(window_trades)}) ---")
            if not window_trades:
                print("  No trades closed in this window.")
                continue

            wins = [t for t in window_trades if Decimal(str(t["net_pnl"])) > 0]
            losses = [t for t in window_trades if Decimal(str(t["net_pnl"])) <= 0]

            tot_net = sum(Decimal(str(t["net_pnl"])) for t in window_trades)
            tot_gross = sum(Decimal(str(t["gross_pnl"])) for t in window_trades)
            tot_fees = sum(Decimal(str(t["fee"])) for t in window_trades)

            wr = (Decimal(len(wins)) / Decimal(len(window_trades))) * 100 if window_trades else Decimal(0)
            avg_win = (sum(Decimal(str(t["net_pnl"])) for t in wins) / len(wins)) if wins else Decimal(0)
            avg_loss = (sum(Decimal(str(t["net_pnl"])) for t in losses) / len(losses)) if losses else Decimal(0)

            print(f"  Closed Trades:   {len(window_trades)}")
            print(f"  Wins / Losses:   {len(wins)} / {len(losses)} (Win Rate: {wr:.1f}%)")
            print(f"  Gross PnL:       ${tot_gross:+.4f} USDT")
            print(f"  Fees Paid:       ${tot_fees:.4f} USDT")
            print(f"  Net PnL:         ${tot_net:+.4f} USDT")
            print(f"  Avg Win / Loss:  +${avg_win:.4f} / -${abs(avg_loss):.4f}")

            # Symbol breakdown
            syms = {}
            for t in window_trades:
                s = t["symbol"]
                if s not in syms:
                    syms[s] = {"net": Decimal(0), "gross": Decimal(0), "fee": Decimal(0), "count": 0, "wins": 0}
                syms[s]["count"] += 1
                if Decimal(str(t["net_pnl"])) > 0:
                    syms[s]["wins"] += 1
                syms[s]["net"] += Decimal(str(t["net_pnl"]))
                syms[s]["gross"] += Decimal(str(t["gross_pnl"]))
                syms[s]["fee"] += Decimal(str(t["fee"]))

            print("  Asset Breakdown:")
            for s, stats in sorted(syms.items(), key=lambda x: x[1]["net"]):
                s_wr = (stats["wins"] / stats["count"]) * 100
                print(f"    {s:<12}: Net ${stats['net']:>+7.4f} (Gross ${stats['gross']:>+7.4f}, Fees ${stats['fee']:>6.4f}) | WR: {s_wr:4.1f}% ({stats['wins']}/{stats['count']})")

            # Trade list chronologically
            print("  Chronological Trade Log:")
            for t in sorted(window_trades, key=lambda x: x["exit_time"]):
                t_exit = t["exit_time"][11:19]
                side = t["side"]
                sym = t["symbol"]
                net = Decimal(str(t["net_pnl"]))
                fee = Decimal(str(t["fee"]))
                gross = Decimal(str(t["gross_pnl"]))
                print(f"    [{t_exit}] {sym:<10} {side:<4} | Gross: ${gross:>+6.4f} | Fee: ${fee:>6.4f} | Net: ${net:>+6.4f}")

if __name__ == "__main__":
    analyze_last_12h()
