import json
from decimal import Decimal

with open("data/live_audit_summary.json", "r") as f:
    data = json.load(f)

# Inspect the last 10 macro trades and last 10 scalp trades in detail
print("=== RECENT MACRO TRADES (LAST 8) ===")
for t in data["macro_trades"][-8:]:
    dur_m = t.get("duration_seconds", 0) / 60
    print(f"[{t['exit_time']}] {t['symbol']} {t['side']} | Entry: {t['entry_price']} Exit: {t['exit_price']} | Dur: {dur_m:.1f}m | Gross: ${Decimal(str(t['gross_pnl'])):+.4f} | Fee: ${Decimal(str(t['fee'])):.4f} | Net: ${Decimal(str(t['net_pnl'])):+.4f}")

print("\n=== RECENT SCALP TRADES (LAST 8) ===")
for t in data["scalp_trades"][-8:]:
    dur_m = t.get("duration_seconds", 0) / 60
    print(f"[{t['exit_time']}] {t['symbol']} {t['side']} | Entry: {t['entry_price']} Exit: {t['exit_price']} | Dur: {dur_m:.1f}m | Gross: ${Decimal(str(t['gross_pnl'])):+.4f} | Fee: ${Decimal(str(t['fee'])):.4f} | Net: ${Decimal(str(t['net_pnl'])):+.4f}")
