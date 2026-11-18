"""
scripts/analyze_live_stats.py - Deep breakdown of real live trades from live_audit_summary.json
"""
import json
from decimal import Decimal

def main():
    with open("data/live_audit_summary.json", "r") as f:
        data = json.load(f)

    for strat, key in [("LIVE MACRO SWING", "macro_trades"), ("LIVE LIGHTNING SCALPER", "scalp_trades")]:
        trades = data[key]
        print("=" * 75)
        print(f"{strat}: STATISTICAL DECOMPOSITION ({len(trades)} REAL LIVE TRADES)")
        print("=" * 75)

        wins = [t for t in trades if Decimal(t["net_pnl"]) > 0]
        losses = [t for t in trades if Decimal(t["net_pnl"]) <= 0]

        tot_win_pnl = sum(Decimal(t["net_pnl"]) for t in wins)
        tot_loss_pnl = sum(Decimal(t["net_pnl"]) for t in losses)
        avg_win = (tot_win_pnl / len(wins)) if wins else Decimal("0")
        avg_loss = (tot_loss_pnl / len(losses)) if losses else Decimal("0")
        payout_ratio = (avg_win / abs(avg_loss)) if avg_loss != 0 else Decimal("0")
        wr = Decimal(len(wins)) / Decimal(len(trades)) if trades else Decimal("0")
        ev = (wr * avg_win) + ((Decimal("1") - wr) * avg_loss)

        gross_win = sum(Decimal(t["gross_pnl"]) for t in wins)
        gross_loss = sum(abs(Decimal(t["gross_pnl"])) for t in losses)
        profit_factor = (gross_win / gross_loss) if gross_loss > 0 else Decimal("999")

        print(f"Win Rate:              {wr * 100:.1f}% ({len(wins)} Wins / {len(losses)} Losses)")
        print(f"Profit Factor:         {profit_factor:.2f}x (Gross Gains: ${gross_win:.2f} / Gross Losses: ${gross_loss:.2f})")
        print(f"Average Win:           +${avg_win:.4f} USDT")
        print(f"Average Loss:          -${abs(avg_loss):.4f} USDT")
        print(f"Win/Loss Payout Ratio: {payout_ratio:.2f}x")
        print(f"Net EV per Trade:      +${ev:.4f} USDT (Net of all fees)")

        # Duration categories
        fast = [t for t in trades if t["duration_seconds"] <= 1800] # <= 30m
        med = [t for t in trades if 1800 < t["duration_seconds"] <= 43200] # 30m to 12h
        stale = [t for t in trades if t["duration_seconds"] > 43200] # > 12h

        print(f"\nDuration Decomposition:")
        print(f"  Fast (<=30m):   {len(fast):>3} trades | Net: ${sum(Decimal(t['net_pnl']) for t in fast):>7.4f} | WR: {len([t for t in fast if Decimal(t['net_pnl']) > 0])/len(fast)*100 if fast else 0:.1f}%")
        print(f"  Medium (30m-12h): {len(med):>3} trades | Net: ${sum(Decimal(t['net_pnl']) for t in med):>7.4f} | WR: {len([t for t in med if Decimal(t['net_pnl']) > 0])/len(med)*100 if med else 0:.1f}%")
        print(f"  Stale (>12h):   {len(stale):>3} trades | Net: ${sum(Decimal(t['net_pnl']) for t in stale):>7.4f} | WR: {len([t for t in stale if Decimal(t['net_pnl']) > 0])/len(stale)*100 if stale else 0:.1f}%")

        # Symbol breakdown
        sym_pnl = {}
        for t in trades:
            s = t["symbol"]
            if s not in sym_pnl:
                sym_pnl[s] = {"count": 0, "wins": 0, "net": Decimal("0"), "gross": Decimal("0"), "fee": Decimal("0")}
            sym_pnl[s]["count"] += 1
            if Decimal(t["net_pnl"]) > 0:
                sym_pnl[s]["wins"] += 1
            sym_pnl[s]["net"] += Decimal(t["net_pnl"])
            sym_pnl[s]["gross"] += Decimal(t["gross_pnl"])
            sym_pnl[s]["fee"] += Decimal(t["fee"])

        print(f"\nAsset Alpha Ranking:")
        for s, v in sorted(sym_pnl.items(), key=lambda x: x[1]["net"], reverse=True):
            wr_s = (v["wins"] / v["count"] * 100) if v["count"] else 0
            fee_ratio = (v["fee"] / v["gross"] * 100) if v["gross"] > 0 else Decimal("0")
            print(f"  {s:<12}: Net: ${v['net']:>7.4f} | Gross: ${v['gross']:>7.4f} | Fees: ${v['fee']:>6.4f} ({fee_ratio:>4.1f}% fee drag) | WR: {wr_s:>5.1f}% (N={v['count']})")

        # Top Winners & Losers
        sorted_by_net = sorted(trades, key=lambda x: Decimal(x["net_pnl"]), reverse=True)
        print(f"\nTop 3 Real Money Winners:")
        for t in sorted_by_net[:3]:
            dur_h = t["duration_seconds"] / 3600
            print(f"  +${Decimal(t['net_pnl']):.4f} | {t['symbol']:<10} {t['side']:<4} | Gross: ${Decimal(t['gross_pnl']):.4f} Fee: ${Decimal(t['fee']):.4f} | Dur: {dur_h:>4.1f}h | Entry: {float(t['entry_price']):.4f} -> Exit: {float(t['exit_price']):.4f}")

        print(f"Top 3 Real Money Losers:")
        for t in sorted_by_net[-3:]:
            dur_h = t["duration_seconds"] / 3600
            print(f"  -${abs(Decimal(t['net_pnl'])):.4f} | {t['symbol']:<10} {t['side']:<4} | Gross: ${Decimal(t['gross_pnl']):.4f} Fee: ${Decimal(t['fee']):.4f} | Dur: {dur_h:>4.1f}h | Entry: {float(t['entry_price']):.4f} -> Exit: {float(t['exit_price']):.4f}")
        print("\n")

if __name__ == "__main__":
    main()
