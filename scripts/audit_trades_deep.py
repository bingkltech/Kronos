"""
audit_trades_deep.py - Deep extraction and assessment of Macro and Scalper trades.
"""
import json
import sqlite3
import os
from decimal import Decimal

def audit_macro_trades():
    print("=" * 80)
    print("MACRO STRATEGY TRADES ASSESSMENT")
    print("=" * 80)
    if not os.path.exists("data/paper_trading_state.json"):
        print("data/paper_trading_state.json not found")
        return

    with open("data/paper_trading_state.json", "r") as f:
        data = json.load(f)

    closed = data.get("closed_trades", [])
    print(f"Total Macro Closed Trades in state: {len(closed)}")
    
    total_gross = Decimal("0")
    total_net = Decimal("0")
    total_fees = Decimal("0")
    total_slip = Decimal("0")
    total_funding = Decimal("0")
    wins = 0
    losses = 0

    for i, t in enumerate(closed, 1):
        pnl = Decimal(str(t.get("realized_pnl_usd", 0)))
        gross = Decimal(str(t.get("gross_pnl_usd", 0)))
        fee = Decimal(str(t.get("fee_usd", 0)))
        slip = Decimal(str(t.get("slippage_usd", 0)))
        fund = Decimal(str(t.get("funding_usd", 0)))
        ret = t.get("return_pct", 0)
        dur = t.get("duration_minutes", 0)
        res = t.get("result", "")
        reason = t.get("reason", "")
        sym = t.get("symbol", "")
        side = t.get("side", "")
        notional = t.get("notional_usd", 0)
        entry_t = t.get("entry_time", "")
        close_t = t.get("close_time", "")

        total_gross += gross
        total_net += pnl
        total_fees += fee
        total_slip += slip
        total_funding += fund
        if pnl > 0:
            wins += 1
        else:
            losses += 1

        print(f"[{i:02d}] {sym:<9} {side:<4} | Net: ${pnl:>7.2f} ({ret:>5.2f}%) | Notional: ${notional:>6.2f} | Gross: ${gross:>6.2f} Fee: ${fee:>4.2f} Slip: ${slip:>4.2f} Fund: ${fund:>4.2f} | Dur: {dur:>4}m ({dur/60:>4.1f}h) | {reason}")

    win_rate = (wins / len(closed) * 100) if closed else 0
    print("-" * 80)
    print(f"Macro Summary: Total Trades: {len(closed)} | Wins: {wins} | Losses: {losses} | Win Rate: {win_rate:.1f}%")
    print(f"Total Net PnL: ${total_net:.2f} | Total Gross: ${total_gross:.2f} | Total Fees: ${total_fees:.2f} | Total Slip: ${total_slip:.2f} | Total Funding: ${total_funding:.2f}")

    # Check trade_outcomes in lessons.db for any additional live trades
    if os.path.exists("data/lessons.db"):
        conn = sqlite3.connect("data/lessons.db")
        c = conn.cursor()
        c.execute("SELECT trade_id, symbol, side, realized_hit, realized_pnl_usd, exit_reason, execution_mode, created_at FROM trade_outcomes WHERE execution_mode='LIVE'")
        live_trades = c.fetchall()
        print(f"\nLive Macro Trades in lessons.db: {len(live_trades)}")
        for lt in live_trades:
            print(f"  LIVE: {lt[0]} | {lt[1]} {lt[2]} | Hit: {lt[3]} | PnL: ${lt[4]} | Reason: {lt[5]} | Date: {lt[7]}")
        conn.close()

def audit_tiger_scalper_trades():
    print("\n" + "=" * 80)
    print("LIGHTNING / TIGER SCALPER TRADES ASSESSMENT")
    print("=" * 80)
    if not os.path.exists("data/tiger_trades.db"):
        print("data/tiger_trades.db not found")
        return

    conn = sqlite3.connect("data/tiger_trades.db")
    c = conn.cursor()
    c.execute("SELECT trade_id, symbol, side, entry_price, exit_price, notional_usd, net_pnl_usd, net_pnl_pct, duration_seconds, exit_reason, is_win, mfe_pct, mae_pct, autopsy_code, created_at_utc, closed_at_utc FROM tiger_trades")
    trades = c.fetchall()
    print(f"Total Tiger Scalper Trades in DB: {len(trades)}")

    total_net = Decimal("0")
    wins = 0
    losses = 0

    for i, t in enumerate(trades, 1):
        tid, sym, side, entry, exit_p, notional, net_pnl, net_pct, dur_sec, reason, is_win, mfe, mae, autopsy, created, closed = t
        net_dec = Decimal(str(net_pnl))
        total_net += net_dec
        if is_win:
            wins += 1
        else:
            losses += 1
        mfe_val = float(mfe) * 100
        mae_val = float(mae) * 100
        pct_val = float(net_pct) * 100
        print(f"[{i:02d}] {sym:<10} {side:<4} | Net: ${net_dec:>6.2f} ({pct_val:>5.2f}%) | Notional: ${float(notional):>6.2f} | Dur: {dur_sec:>3}s | MFE: +{mfe_val:>4.2f}% MAE: -{mae_val:>4.2f}% | Autopsy: {autopsy:<22} | Reason: {reason}")

    win_rate = (wins / len(trades) * 100) if trades else 0
    print("-" * 80)
    print(f"Tiger Scalper Summary: Total Trades: {len(trades)} | Wins: {wins} | Losses: {losses} | Win Rate: {win_rate:.1f}%")
    print(f"Total Realized Net PnL: ${total_net:.2f}")
    conn.close()

def audit_scalper_forensics():
    print("\n" + "=" * 80)
    print("SCALPER FORENSICS & BENCHMARK SUITE (lessons.db)")
    print("=" * 80)
    if not os.path.exists("data/lessons.db"):
        return
    conn = sqlite3.connect("data/lessons.db")
    c = conn.cursor()
    c.execute("SELECT root_cause_diagnosis, count(*), avg(CAST(net_pnl_usd AS FLOAT)), sum(CAST(net_pnl_usd AS FLOAT)), sum(CAST(exchange_fees_usd AS FLOAT)) FROM scalper_forensics GROUP BY root_cause_diagnosis")
    rows = c.fetchall()
    print(f"{'Root Cause':<25} | {'Count':<5} | {'Avg PnL':<10} | {'Sum PnL':<10} | {'Fees Drag':<10}")
    print("-" * 75)
    for r in rows:
        print(f"{r[0]:<25} | {r[1]:<5} | ${r[2]:>8.2f} | ${r[3]:>8.2f} | ${r[4]:>8.2f}")
    conn.close()

if __name__ == "__main__":
    audit_macro_trades()
    audit_tiger_scalper_trades()
    audit_scalper_forensics()
