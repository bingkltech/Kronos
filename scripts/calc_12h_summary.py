import json
from decimal import Decimal
import datetime

with open("data/live_audit_summary.json", "r") as f:
    data = json.load(f)

# Sort all fills / trades chronologically to compute cumulative PnL curve
all_trades = []
for t in data["macro_trades"]:
    t["strat"] = "MACRO"
    all_trades.append(t)
for t in data["scalp_trades"]:
    t["strat"] = "SCALP"
    all_trades.append(t)

all_trades.sort(key=lambda x: x["exit_time"])

now_utc = datetime.datetime(2026, 11, 16, 15, 15, 0, tzinfo=datetime.timezone.utc)
cutoff_12h = now_utc - datetime.timedelta(hours=12)
cutoff_24h = now_utc - datetime.timedelta(hours=24)

trades_12h = [t for t in all_trades if datetime.datetime.fromisoformat(t["exit_time"]) >= cutoff_12h]
trades_24h = [t for t in all_trades if datetime.datetime.fromisoformat(t["exit_time"]) >= cutoff_24h]

print(f"Total historical trades: {len(all_trades)}")
print(f"Trades in last 12h: {len(trades_12h)}")
print(f"Trades in last 24h: {len(trades_24h)}")

gross_12h = sum(Decimal(str(t["gross_pnl"])) for t in trades_12h)
fee_12h = sum(Decimal(str(t["fee"])) for t in trades_12h)
net_12h = sum(Decimal(str(t["net_pnl"])) for t in trades_12h)

gross_24h = sum(Decimal(str(t["gross_pnl"])) for t in trades_24h)
fee_24h = sum(Decimal(str(t["fee"])) for t in trades_24h)
net_24h = sum(Decimal(str(t["net_pnl"])) for t in trades_24h)

print(f"\nLAST 12 HOURS:")
print(f"  Gross PnL: ${gross_12h:+.4f}")
print(f"  Fees:      ${fee_12h:.4f}")
print(f"  Net PnL:   ${net_12h:+.4f}")

print(f"\nLAST 24 HOURS:")
print(f"  Gross PnL: ${gross_24h:+.4f}")
print(f"  Fees:      ${fee_24h:.4f}")
print(f"  Net PnL:   ${net_24h:+.4f}")
