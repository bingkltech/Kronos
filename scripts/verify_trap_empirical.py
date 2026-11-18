import json
from decimal import Decimal

with open("data/live_audit_summary.json") as f:
    d = json.load(f)

print("=== TRADES STOPPED OUT AT 15:06-15:07 UTC ===")
for t in d["macro_trades"]:
    if "2026-11-16T15:0" in t["exit_time"]:
        print(f"Symbol: {t['symbol']} | Side: {t['side']}")
        print(f"  Entry Time: {t['entry_time']} @ Price: {t['entry_price']}")
        print(f"  Exit Time:  {t['exit_time']} @ Price: {t['exit_price']}")
        print(f"  Duration:   {t['duration_seconds']}s ({t['duration_seconds']/60:.1f}m)")
        print(f"  Gross PnL:  ${Decimal(str(t['gross_pnl'])):+.4f} | Fee: ${Decimal(str(t['fee'])):.4f} | Net: ${Decimal(str(t['net_pnl'])):+.4f}")
        print()

print("=== TRADES STOPPED OUT AT 14:13-14:33 UTC ===")
for t in d["macro_trades"]:
    if "2026-11-16T14:" in t["exit_time"]:
        print(f"Symbol: {t['symbol']} | Side: {t['side']}")
        print(f"  Entry Time: {t['entry_time']} @ Price: {t['entry_price']}")
        print(f"  Exit Time:  {t['exit_time']} @ Price: {t['exit_price']}")
        print(f"  Duration:   {t['duration_seconds']}s ({t['duration_seconds']/60:.1f}m)")
        print(f"  Gross PnL:  ${Decimal(str(t['gross_pnl'])):+.4f} | Fee: ${Decimal(str(t['fee'])):.4f} | Net: ${Decimal(str(t['net_pnl'])):+.4f}")
        print()
