import sqlite3
import json
from decimal import Decimal

conn = sqlite3.connect('data/tiger_trades.db')
conn.row_factory = sqlite3.Row
trades = conn.execute('SELECT * FROM tiger_trades ORDER BY rowid ASC').fetchall()

print(f"Total trades in DB: {len(trades)}")
print("-" * 120)
print(f"{'#':<3} | {'Symbol':<10} | {'Side':<4} | {'Entry':<10} | {'Exit':<10} | {'Net USD':<8} | {'Ret %':<7} | {'W/L':<3} | {'Dur(s)':<6} | {'Autopsy':<18} | {'Reason'}")
print("-" * 120)

total_net_usd = Decimal("0")
wins = 0
losses = 0
gross_win_usd = Decimal("0")
gross_loss_usd = Decimal("0")

patch_split = 14  # Trades 1-14 (initial build/iterations), 15-23 (post latest patches)

pre_net_usd = Decimal("0")
pre_wins = 0
post_net_usd = Decimal("0")
post_wins = 0
post_trades = 0

autopsies = {}

for i, t in enumerate(trades, 1):
    d = dict(t)
    net_usd = Decimal(str(d["net_pnl_usd"]))
    ret_pct = Decimal(str(d["net_pnl_pct"])) * Decimal("100")
    is_win = bool(d["is_win"])
    total_net_usd += net_usd
    
    if is_win:
        wins += 1
        gross_win_usd += net_usd
    else:
        losses += 1
        gross_loss_usd += abs(net_usd)

    if i <= patch_split:
        pre_net_usd += net_usd
        if is_win:
            pre_wins += 1
    else:
        post_trades += 1
        post_net_usd += net_usd
        if is_win:
            post_wins += 1

    auto = d.get("autopsy_code") or "UNKNOWN"
    autopsies[auto] = autopsies.get(auto, 0) + 1

    print(f"{i:<3} | {d['symbol']:<10} | {d['side']:<4} | {d['entry_price']:<10} | {d['exit_price']:<10} | {net_usd:>8.2f} | {ret_pct:>6.2f}% | {'WIN' if is_win else 'LOSS':<4} | {d['duration_seconds']:<6} | {auto:<18} | {d['exit_reason']}")

print("-" * 120)
print(f"ALL-TIME METRICS (Trades 1 to {len(trades)}):")
print(f"Total Net PnL: ${total_net_usd:.2f}")
win_rate = (Decimal(wins) / Decimal(len(trades))) * Decimal("100") if trades else Decimal("0")
print(f"Win Rate: {win_rate:.1f}% ({wins} W / {losses} L)")
pf = (gross_win_usd / gross_loss_usd) if gross_loss_usd > Decimal("0") else Decimal("0")
print(f"Profit Factor: {pf:.2f} (Gross Win: ${gross_win_usd:.2f} | Gross Loss: ${gross_loss_usd:.2f})")
ev = total_net_usd / Decimal(len(trades)) if trades else Decimal("0")
print(f"Net EV per trade: ${ev:.2f}")

print("\n" + "=" * 60)
print(f"PHASE 1: Early Architecture (Trades 1 to {patch_split}):")
print(f"Trades: {patch_split} | Wins: {pre_wins} ({pre_wins/patch_split*100:.1f}%) | Net PnL: ${pre_net_usd:.2f}")

print("\n" + "=" * 60)
print(f"PHASE 2: Latest Patches (Trades {patch_split + 1} to {len(trades)}):")
if post_trades > 0:
    print(f"Trades: {post_trades} | Wins: {post_wins} ({post_wins/post_trades*100:.1f}%) | Net PnL: ${post_net_usd:.2f}")
    print(f"Phase 2 Net EV per trade: ${post_net_usd / Decimal(post_trades):.2f}")

print("\n" + "=" * 60)
print("AUTOPSY BREAKDOWN:")
for code, count in sorted(autopsies.items(), key=lambda x: -x[1]):
    print(f"  {code:<22}: {count} ({count/len(trades)*100:.1f}%)")
