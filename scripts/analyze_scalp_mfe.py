import json
from decimal import Decimal

with open("data/live_audit_summary.json") as f:
    data = json.load(f)

print("=== SCALP TRADES MFE / MAE ANALYSIS (LAST 12 HOURS) ===")
# scalp trades in last 12h
for t in data["scalp_trades"][-12:]:
    gross = Decimal(str(t["gross_pnl"]))
    net = Decimal(str(t["net_pnl"]))
    entry = Decimal(str(t["entry_price"]))
    exit_p = Decimal(str(t["exit_price"]))
    side = t["side"]
    dur_m = t.get("duration_seconds", 0) / 60
    
    # Calculate price return
    if side == "BUY":
        ret_pct = (exit_p - entry) / entry * 100
    else:
        ret_pct = (entry - exit_p) / entry * 100
        
    print(f"[{t['exit_time'][11:19]}] {t['symbol']:<12} {side:<4} | Entry: {entry} -> Exit: {exit_p} | Ret: {ret_pct:>+6.2f}% | Dur: {dur_m:>4.1f}m | Gross: ${gross:>+6.4f} | Fee: ${t['fee']} | Net: ${net:>+6.4f}")
