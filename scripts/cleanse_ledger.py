"""
scripts/cleanse_ledger.py — Cleanse test contamination from paper_trading_state.json.
Removes trades with notional > $1,000 (test fixtures) and recalculates true equity.
"""

import json
import os
from decimal import Decimal

STATE_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "paper_trading_state.json")

def cleanse_ledger():
    if not os.path.exists(STATE_FILE):
        print(f"File not found: {STATE_FILE}")
        return

    with open(STATE_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    original_trades = data.get("closed_trades", [])
    initial_equity = Decimal(str(data.get("initial_equity", "200.00")))

    # Keep only genuine micro trades (notional <= $1,000 on a $200 account with 5x leverage)
    valid_trades = [t for t in original_trades if t.get("notional_usd", 0) <= 1000]

    total_realized_pnl = sum(Decimal(str(t.get("realized_pnl_usd", "0.0"))) for t in valid_trades)
    current_equity = initial_equity + total_realized_pnl

    data["closed_trades"] = valid_trades
    data["total_trades"] = len(valid_trades)
    data["current_equity"] = str(current_equity)
    data["last_paper_trade"] = valid_trades[-1] if valid_trades else None

    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

    print(f"Cleaned {len(original_trades) - len(valid_trades)} test trades.")
    print(f"Remaining valid micro trades: {len(valid_trades)}")
    print(f"Cleaned Realized PnL: ${total_realized_pnl:.2f}")
    print(f"Cleaned Paper Equity: ${current_equity:.2f}")

if __name__ == "__main__":
    cleanse_ledger()
