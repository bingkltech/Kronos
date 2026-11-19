"""
scripts/reassess_scalp_trades.py — Full Forensic Reassessment of Live Scalp Trades by Advisory Consultant.
"""

import json
from decimal import Decimal, ROUND_HALF_UP
from collections import defaultdict
from typing import List, Dict, Any

def run_reassessment():
    with open('data/live_audit_summary.json', 'r') as f:
        data = json.load(f)

    trades = data.get('scalp_trades', [])
    if not trades:
        print("No live scalp trades found.")
        return

    total = len(trades)
    wins = [t for t in trades if Decimal(str(t['net_pnl'])) > 0]
    losses = [t for t in trades if Decimal(str(t['net_pnl'])) <= 0]

    gross_pnl = sum(Decimal(str(t['gross_pnl'])) for t in trades)
    total_fees = sum(Decimal(str(t['fee'])) for t in trades)
    net_pnl = sum(Decimal(str(t['net_pnl'])) for t in trades)

    win_gross = sum(Decimal(str(t['gross_pnl'])) for t in wins)
    loss_gross = sum(abs(Decimal(str(t['gross_pnl']))) for t in losses)
    profit_factor = (win_gross / loss_gross) if loss_gross > 0 else Decimal('0')

    win_fees = sum(Decimal(str(t['fee'])) for t in wins)
    loss_fees = sum(Decimal(str(t['fee'])) for t in losses)

    avg_win = (sum(Decimal(str(t['net_pnl'])) for t in wins) / len(wins)) if wins else Decimal('0')
    avg_loss = (sum(Decimal(str(t['net_pnl'])) for t in losses) / len(losses)) if losses else Decimal('0')

    print("=" * 80)
    print(" KRONOS ADVISORY CONSULTANT: FULL LIVE SCALP FORENSIC REASSESSMENT")
    print("=" * 80)
    print(f"Total Scalp Trades Analyzed : {total}")
    print(f"Winning Trades              : {len(wins)} ({len(wins)/total*100:.1f}%)")
    print(f"Losing Trades               : {len(losses)} ({len(losses)/total*100:.1f}%)")
    print(f"Gross PnL (Pre-Fee)         : ${gross_pnl:+.4f} USDT")
    print(f"Exchange Fees Paid (VIP0)   : ${total_fees:.4f} USDT ({(total_fees/win_gross*100):.1f}% of gross wins)")
    print(f"Net Realized PnL            : ${net_pnl:+.4f} USDT")
    print(f"Profit Factor               : {profit_factor:.2f}")
    print(f"Average Win (Net)           : ${avg_win:+.4f} USDT")
    print(f"Average Loss (Net)          : ${avg_loss:+.4f} USDT")
    print(f"Win/Loss Payoff Ratio       : {abs(avg_win / avg_loss) if avg_loss != 0 else 0:.2f}:1")
    print("-" * 80)

    # 1. Holding Duration & Stagnation Analysis
    durations = [t['duration_seconds'] for t in trades]
    avg_duration = sum(durations) / len(durations)
    median_duration = sorted(durations)[len(durations) // 2]
    
    print("\n[1] TEMPORAL HOLDING DURATION & STAGNATION DECAY AUDIT")
    print(f"Mean Duration               : {avg_duration/60:.1f} minutes ({avg_duration:.0f}s)")
    print(f"Median Duration             : {median_duration/60:.1f} minutes ({median_duration:.0f}s)")
    print(f"Shortest Trade              : {min(durations)/60:.1f}m ({min(durations)}s)")
    print(f"Longest Trade               : {max(durations)/60:.1f}m ({max(durations)}s)")

    buckets = [
        ("< 10 min (Fast Scalp)", 0, 600),
        ("10 - 15 min (Target Sweetspot)", 600, 900),
        ("15 - 30 min (Caution / Alpha Decay)", 900, 1800),
        ("30 - 60 min (Severe Stagnation)", 1800, 3600),
        ("> 60 min (Trapped Position)", 3600, 1000000),
    ]

    print(f"\n{'Duration Bucket':<35} {'Trades':<8} {'Win Rate':<10} {'Gross PnL':<12} {'Fees':<10} {'Net PnL':<12}")
    print("-" * 87)
    for name, low, high in buckets:
        b_trades = [t for t in trades if low <= t['duration_seconds'] < high]
        if not b_trades:
            continue
        b_wins = [t for t in b_trades if Decimal(str(t['net_pnl'])) > 0]
        b_gross = sum(Decimal(str(t['gross_pnl'])) for t in b_trades)
        b_fees = sum(Decimal(str(t['fee'])) for t in b_trades)
        b_net = sum(Decimal(str(t['net_pnl'])) for t in b_trades)
        wr = len(b_wins) / len(b_trades) * 100
        print(f"{name:<35} {len(b_trades):<8} {wr:5.1f}%     ${b_gross:+9.4f}  ${b_fees:8.4f}  ${b_net:+9.4f}")

    # 2. Symbol Breakdown
    print("\n[2] ASSET-SPECIFIC ATTRIBUTION (PROFIT DRIVERS VS BLEED ASSETS)")
    by_sym = defaultdict(list)
    for t in trades:
        by_sym[t['symbol']].append(t)

    sorted_syms = sorted(by_sym.items(), key=lambda x: sum(Decimal(str(t['net_pnl'])) for t in x[1]), reverse=True)
    print(f"{'Symbol':<14} {'Trades':<8} {'Win Rate':<10} {'Gross PnL':<12} {'Fees':<10} {'Net PnL':<12} {'Avg Dur':<10}")
    print("-" * 76)
    for sym, s_trades in sorted_syms:
        s_wins = [t for t in s_trades if Decimal(str(t['net_pnl'])) > 0]
        s_gross = sum(Decimal(str(t['gross_pnl'])) for t in s_trades)
        s_fees = sum(Decimal(str(t['fee'])) for t in s_trades)
        s_net = sum(Decimal(str(t['net_pnl'])) for t in s_trades)
        s_avg_dur = sum(t['duration_seconds'] for t in s_trades) / len(s_trades)
        wr = len(s_wins) / len(s_trades) * 100
        print(f"{sym:<14} {len(s_trades):<8} {wr:5.1f}%     ${s_gross:+9.4f}  ${s_fees:8.4f}  ${s_net:+9.4f} {s_avg_dur/60:5.1f}m")

    # 3. Directional Bias
    print("\n[3] DIRECTIONAL ATTRIBUTION (BUY VS SELL)")
    by_side = defaultdict(list)
    for t in trades:
        by_side[t['side']].append(t)

    for side, side_trades in by_side.items():
        s_wins = [t for t in side_trades if Decimal(str(t['net_pnl'])) > 0]
        s_gross = sum(Decimal(str(t['gross_pnl'])) for t in side_trades)
        s_fees = sum(Decimal(str(t['fee'])) for t in side_trades)
        s_net = sum(Decimal(str(t['net_pnl'])) for t in side_trades)
        wr = len(s_wins) / len(side_trades) * 100
        print(f"Side {side:<6}: {len(side_trades):2d} trades | Win Rate: {wr:5.1f}% | Gross: ${s_gross:+9.4f} | Fees: ${s_fees:8.4f} | Net: ${s_net:+9.4f}")

    # 4. Extreme Trades (Top 3 Wins & Worst 3 Losses)
    sorted_by_net = sorted(trades, key=lambda x: Decimal(str(x['net_pnl'])), reverse=True)
    print("\n[4] TOP 3 WINNING TRADES")
    for i, t in enumerate(sorted_by_net[:3], 1):
        print(f"  #{i}: {t['symbol']} {t['side']} | Net: ${Decimal(str(t['net_pnl'])):+.4f} | Duration: {t['duration_seconds']/60:.1f}m | Entry: {t['entry_price']} -> Exit: {t['exit_price']}")

    print("\n[5] WORST 3 LOSING TRADES")
    for i, t in enumerate(sorted_by_net[-3:], 1):
        print(f"  #{i}: {t['symbol']} {t['side']} | Net: ${Decimal(str(t['net_pnl'])):+.4f} | Duration: {t['duration_seconds']/60:.1f}m | Entry: {t['entry_price']} -> Exit: {t['exit_price']}")

    # 5. False Wins Eaten By Fees (Trades where Gross > 0 but Net <= 0)
    fee_eaten = [t for t in trades if Decimal(str(t['gross_pnl'])) > 0 and Decimal(str(t['net_pnl'])) <= 0]
    print(f"\n[6] FEE DRAG VICTIMS (Gross Profitable but Net Negative): {len(fee_eaten)} trades")
    for t in fee_eaten:
        print(f"  - {t['symbol']} {t['side']}: Gross ${Decimal(str(t['gross_pnl'])):+.4f} - Fee ${Decimal(str(t['fee'])):.4f} = Net ${Decimal(str(t['net_pnl'])):+.4f} (Duration: {t['duration_seconds']/60:.1f}m)")

if __name__ == '__main__':
    run_reassessment()
