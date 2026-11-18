import os
import sqlite3
import json
import datetime
from decimal import Decimal

def inspect_tiger():
    conn = sqlite3.connect("data/tiger_trades.db")
    cursor = conn.cursor()

    # Get all trades
    cursor.execute("SELECT * FROM tiger_trades ORDER BY closed_at_utc ASC")
    col_names = [description[0] for description in cursor.description]
    all_rows = cursor.fetchall()

    now_utc = datetime.datetime.now(datetime.timezone.utc)
    cutoff_12h = now_utc - datetime.timedelta(hours=12)
    cutoff_24h = now_utc - datetime.timedelta(hours=24)

    print("=" * 80)
    print(f"TIGER SCALPER DATABASE FORENSICS (Total Recorded Trades: {len(all_rows)})")
    print(f"Current UTC Time: {now_utc.isoformat()}")
    print(f"12-Hour Cutoff:   {cutoff_12h.isoformat()}")
    print("=" * 80)

    trades = [dict(zip(col_names, r)) for r in all_rows]

    for window_name, cutoff in [("LAST 12 HOURS", cutoff_12h), ("LAST 24 HOURS", cutoff_24h), ("FULL PAPER RUN", None)]:
        if cutoff:
            w_trades = [t for t in trades if datetime.datetime.fromisoformat(t["closed_at_utc"]) >= cutoff]
        else:
            w_trades = trades

        print(f"\n--- {window_name} (Trades: {len(w_trades)}) ---")
        if not w_trades:
            print("  No trades in this window.")
            continue

        wins = [t for t in w_trades if t["is_win"] == 1]
        losses = [t for t in w_trades if t["is_win"] == 0]

        tot_pnl = sum(Decimal(str(t["net_pnl_usd"])) for t in w_trades)
        gross_wins = sum(Decimal(str(t["net_pnl_usd"])) for t in wins)
        gross_losses = sum(abs(Decimal(str(t["net_pnl_usd"]))) for t in losses)

        wr = (Decimal(len(wins)) / Decimal(len(w_trades))) * 100 if w_trades else Decimal(0)
        pf = (gross_wins / gross_losses) if gross_losses > 0 else Decimal("999")
        avg_win = (gross_wins / len(wins)) if wins else Decimal(0)
        avg_loss = (gross_losses / len(losses)) if losses else Decimal(0)
        payoff = (avg_win / avg_loss) if avg_loss > 0 else Decimal(0)

        avg_mfe = sum(Decimal(str(t["mfe_pct"])) for t in w_trades) / len(w_trades) * 100
        avg_mae = sum(Decimal(str(t["mae_pct"])) for t in w_trades) / len(w_trades) * 100

        print(f"  Win Rate:       {wr:.1f}% ({len(wins)} Wins / {len(losses)} Losses)")
        print(f"  Profit Factor:  {pf:.2f}x (Gross Gains: ${gross_wins:+.2f} / Gross Losses: -${gross_losses:.2f})")
        print(f"  Net Realized:   ${tot_pnl:+.4f} USDT")
        print(f"  Avg Win / Loss: +${avg_win:.4f} / -${avg_loss:.4f} (Payoff Ratio: {payoff:.2f}x)")
        print(f"  Avg MFE / MAE:  +{avg_mfe:.2f}% / -{avg_mae:.2f}%")

        # Autopsy decomposition
        autopsies = {}
        for t in w_trades:
            code = t.get("autopsy_code") or "UNKNOWN"
            if code not in autopsies:
                autopsies[code] = {"count": 0, "net": Decimal(0)}
            autopsies[code]["count"] += 1
            autopsies[code]["net"] += Decimal(str(t["net_pnl_usd"]))

        print("  Autopsy Code Decomposition:")
        for code, data in sorted(autopsies.items(), key=lambda x: x[1]["net"]):
            print(f"    {code:<25}: {data['count']:>2} trades | Net PnL: ${data['net']:>+7.2f} USDT")

        print("  Individual Trades Log:")
        for t in w_trades:
            t_close = t["closed_at_utc"][11:19]
            sym = t["symbol"]
            side = t["side"]
            pnl = Decimal(str(t["net_pnl_usd"]))
            mfe = Decimal(str(t["mfe_pct"])) * 100
            mae = Decimal(str(t["mae_pct"])) * 100
            dur = t["duration_seconds"]
            reason = t["exit_reason"]
            code = t["autopsy_code"]
            print(f"    [{t_close}] {sym:<10} {side:<4} | PnL: ${pnl:>+6.2f} | MFE: +{mfe:>4.2f}% MAE: -{mae:>4.2f}% | Dur: {dur:>3}s | {code:<20} | {reason}")

    # Inspect Quarantines
    cursor.execute("SELECT symbol, quarantined_at_utc, expiry_utc, reason, strike_count, status FROM tiger_quarantines")
    quarantines = cursor.fetchall()
    print("\n" + "=" * 80)
    print(f"ACTIVE TIGER QUARANTINES ({len(quarantines)} entries):")
    for q in quarantines:
        print(f"  Symbol: {q[0]:<12} | Status: {q[5]} | Strikes: {q[4]} | Reason: {q[3]} | Expires: {q[2]}")

    # Inspect Distilled Rules
    if os.path.exists("data/tiger_distilled_rules.json"):
        with open("data/tiger_distilled_rules.json") as f:
            rules = json.load(f)
        print("\n" + "=" * 80)
        print("TIGER DISTILLED RULES:")
        print(json.dumps(rules, indent=2))

if __name__ == "__main__":
    inspect_tiger()
