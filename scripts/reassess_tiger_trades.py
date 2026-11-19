"""
scripts/reassess_tiger_trades.py — Full Forensic Assessment of Stalking Tiger Scalper by Advisory Consultant.
"""

import sqlite3
from decimal import Decimal
from collections import defaultdict
from datetime import datetime

def run_tiger_assessment():
    conn = sqlite3.connect('data/tiger_trades.db')
    c = conn.cursor()
    cols = [r[1] for r in c.execute('PRAGMA table_info(tiger_trades)').fetchall()]
    rows = [dict(zip(cols, r)) for r in c.execute('SELECT * FROM tiger_trades ORDER BY closed_at_utc ASC').fetchall()]

    if not rows:
        print("No tiger trades found in tiger_trades.db")
        return

    total = len(rows)
    wins = [r for r in rows if r['is_win'] == 1 or Decimal(str(r['net_pnl_usd'])) > 0]
    losses = [r for r in rows if r not in wins]

    net_pnl = sum(Decimal(str(r['net_pnl_usd'])) for r in rows)
    win_pnl = sum(Decimal(str(r['net_pnl_usd'])) for r in wins)
    loss_pnl = sum(abs(Decimal(str(r['net_pnl_usd']))) for r in losses)
    pf = (win_pnl / loss_pnl) if loss_pnl > 0 else Decimal('0')

    print("=" * 80)
    print(" KRONOS ADVISORY CONSULTANT: STALKING TIGER FORENSIC AUDIT")
    print("=" * 80)
    print(f"Total Tiger Trades Recorded : {total}")
    print(f"Wins / Losses               : {len(wins)} Wins ({len(wins)/total*100:.1f}%) / {len(losses)} Losses")
    print(f"Net Realized PnL            : ${net_pnl:+.4f} USDT")
    print(f"Gross Winning PnL           : ${win_pnl:+.4f} USDT")
    print(f"Gross Losing PnL            : ${loss_pnl:+.4f} USDT")
    print(f"Profit Factor               : {pf:.2f}")

    # Directional Breakdown
    print("\n[1] DIRECTIONAL ASYMMETRY (BUY VS SELL)")
    by_side = defaultdict(list)
    for r in rows:
        by_side[r['side']].append(r)

    for side, s_trades in by_side.items():
        s_wins = [r for r in s_trades if r['is_win'] == 1 or Decimal(str(r['net_pnl_usd'])) > 0]
        s_pnl = sum(Decimal(str(r['net_pnl_usd'])) for r in s_trades)
        s_win_pnl = sum(Decimal(str(r['net_pnl_usd'])) for r in s_wins)
        s_loss_pnl = sum(abs(Decimal(str(r['net_pnl_usd']))) for r in s_trades if r not in s_wins)
        s_pf = (s_win_pnl / s_loss_pnl) if s_loss_pnl > 0 else Decimal('0')
        wr = len(s_wins) / len(s_trades) * 100
        print(f"Side {side:<5}: {len(s_trades):2d} trades | Win Rate: {wr:5.1f}% | Net PnL: ${s_pnl:+7.4f} USDT | PF: {s_pf:4.2f}")

    # Asset Performance
    print("\n[2] ASSET-SPECIFIC ATTRIBUTION")
    by_sym = defaultdict(list)
    for r in rows:
        by_sym[r['symbol']].append(r)

    sorted_syms = sorted(by_sym.items(), key=lambda x: sum(Decimal(str(r['net_pnl_usd'])) for r in x[1]), reverse=True)
    print(f"{'Symbol':<14} {'Trades':<8} {'Win Rate':<10} {'Net PnL':<12} {'PF':<8} {'Avg Dur':<10}")
    print("-" * 65)
    for sym, s_trades in sorted_syms:
        s_wins = [r for r in s_trades if r['is_win'] == 1 or Decimal(str(r['net_pnl_usd'])) > 0]
        s_pnl = sum(Decimal(str(r['net_pnl_usd'])) for r in s_trades)
        s_win_pnl = sum(Decimal(str(r['net_pnl_usd'])) for r in s_wins)
        s_loss_pnl = sum(abs(Decimal(str(r['net_pnl_usd']))) for r in s_trades if r not in s_wins)
        s_pf = (s_win_pnl / s_loss_pnl) if s_loss_pnl > 0 else Decimal('0')
        avg_dur = sum(r['duration_seconds'] for r in s_trades) / len(s_trades)
        wr = len(s_wins) / len(s_trades) * 100
        print(f"{sym:<14} {len(s_trades):<8} {wr:5.1f}%     ${s_pnl:+9.4f}  {s_pf:5.2f}    {avg_dur/60:5.1f}m")

    # Autopsy Breakdown
    print("\n[3] ROOT-CAUSE AUTOPSY BREAKDOWN")
    by_code = defaultdict(list)
    for r in rows:
        by_code[r.get('autopsy_code', 'UNKNOWN')].append(r)

    for code, c_trades in sorted(by_code.items(), key=lambda x: len(x[1]), reverse=True):
        c_pnl = sum(Decimal(str(r['net_pnl_usd'])) for r in c_trades)
        print(f"  {code:<22}: {len(c_trades):2d} trades | Impact: ${c_pnl:+7.4f} USDT")

    # Temporal Duration Buckets
    print("\n[4] TEMPORAL HOLDING DURATION AUDIT")
    buckets = [
        ("< 1 min (Instant Stop/Flushes)", 0, 60),
        ("1 - 5 min (Fast Reaction)", 60, 300),
        ("5 - 8 min (Velocity Sieve)", 300, 480),
        ("8 - 12 min (Plateau / Stall)", 480, 720),
        ("12 - 15 min (Hard Cutoff)", 720, 900),
        ("> 15 min (Over-Hold Violations)", 900, 1000000),
    ]
    print(f"{'Duration Bucket':<35} {'Trades':<8} {'Win Rate':<10} {'Net PnL':<12}")
    print("-" * 68)
    for name, low, high in buckets:
        b_trades = [r for r in rows if low <= r['duration_seconds'] < high]
        if not b_trades:
            continue
        b_wins = [r for r in b_trades if r['is_win'] == 1 or Decimal(str(r['net_pnl_usd'])) > 0]
        b_pnl = sum(Decimal(str(r['net_pnl_usd'])) for r in b_trades)
        wr = len(b_wins) / len(b_trades) * 100
        print(f"{name:<35} {len(b_trades):<8} {wr:5.1f}%     ${b_pnl:+9.4f}")

    # Evolution: Early Phase vs Upgraded Phase
    print("\n[5] EVOLUTION TIMELINE (EARLY CANARY VS CALIBRATED STALKING TIGER)")
    early = rows[:16]
    recent = rows[16:]

    def stats(subset, label):
        w = [r for r in subset if r['is_win'] == 1 or Decimal(str(r['net_pnl_usd'])) > 0]
        p = sum(Decimal(str(r['net_pnl_usd'])) for r in subset)
        wp = sum(Decimal(str(r['net_pnl_usd'])) for r in w)
        lp = sum(abs(Decimal(str(r['net_pnl_usd']))) for r in subset if r not in w)
        factor = (wp / lp) if lp > 0 else Decimal('0')
        print(f"  {label:<30}: {len(subset):2d} trades | Win Rate: {len(w)/len(subset)*100:5.1f}% | Net: ${p:+7.4f} USDT | PF: {factor:.2f}")

    stats(early, "Phase 1: Early Canary Setup")
    stats(recent, "Phase 2: Post-Calibration Upgraded")

if __name__ == '__main__':
    run_tiger_assessment()
