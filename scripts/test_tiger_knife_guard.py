import sqlite3
from decimal import Decimal

conn = sqlite3.connect("data/tiger_trades.db")
cursor = conn.cursor()
cursor.execute("SELECT * FROM tiger_trades ORDER BY closed_at_utc ASC")
cols = [d[0] for d in cursor.description]
trades = [dict(zip(cols, r)) for r in cursor.fetchall()]

print(f"Total Tiger Trades: {len(trades)}")

# Baseline stats
wins_base = [t for t in trades if t["is_win"] == 1]
tot_net_base = sum(Decimal(str(t["net_pnl_usd"])) for t in trades)
gross_win_base = sum(Decimal(str(t["net_pnl_usd"])) for t in wins_base)
gross_loss_base = sum(abs(Decimal(str(t["net_pnl_usd"]))) for t in trades if t["is_win"] == 0)
pf_base = gross_win_base / gross_loss_base if gross_loss_base > 0 else Decimal(999)

print(f"BASELINE: {len(trades)} Trades | Wins: {len(wins_base)} | WR: {len(wins_base)/len(trades)*100:.1f}% | Net: ${tot_net_base:+.2f} | PF: {pf_base:.2f}x")

# Counterfactual test:
# Veto BUY trades with ZERO_MFE_LIQ_FLUSH or STEAMROLLER_OUTLIER
vetoed = []
accepted = []

for t in trades:
    # If the trade was a BUY that suffered ZERO_MFE_LIQ_FLUSH or STEAMROLLER_OUTLIER in < 60s
    dur = t["duration_seconds"]
    code = t.get("autopsy_code")
    side = t["side"]
    
    # Falling Knife Guard:
    # A true falling knife drops immediately within <= 60s with 0 MFE
    is_falling_knife = (side == "BUY" and dur <= 60 and Decimal(str(t["mfe_pct"])) == Decimal("0"))
    
    if is_falling_knife:
        vetoed.append(t)
    else:
        accepted.append(t)

wins_patch = [t for t in accepted if t["is_win"] == 1]
tot_net_patch = sum(Decimal(str(t["net_pnl_usd"])) for t in accepted)
gross_win_patch = sum(Decimal(str(t["net_pnl_usd"])) for t in wins_patch)
gross_loss_patch = sum(abs(Decimal(str(t["net_pnl_usd"]))) for t in accepted if t["is_win"] == 0)
pf_patch = gross_win_patch / gross_loss_patch if gross_loss_patch > 0 else Decimal(999)

print(f"\nPATCHED (FALLING KNIFE GUARD):")
print(f"  Vetoed: {len(vetoed)} trades")
for vt in vetoed:
    print(f"    Vetoed: {vt['symbol']} {vt['side']} | PnL: ${Decimal(str(vt['net_pnl_usd'])):+.2f} | Dur: {vt['duration_seconds']}s | {vt['autopsy_code']}")

print(f"\n  Accepted: {len(accepted)} Trades | Wins: {len(wins_patch)} | WR: {len(wins_patch)/len(accepted)*100:.1f}%")
print(f"  Gross Gains: ${gross_win_patch:+.2f} | Gross Losses: -${gross_loss_patch:.2f}")
print(f"  Net Realized: ${tot_net_patch:+.2f} USDT (vs ${tot_net_base:+.2f} USDT)")
print(f"  Profit Factor: {pf_patch:.2f}x (vs {pf_base:.2f}x)")
print(f"  >> ALPHA GAIN: ${tot_net_patch - tot_net_base:+.2f} USDT")
