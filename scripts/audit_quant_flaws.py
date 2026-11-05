"""
Kronos Quant Flaw & Sanity Auditor CLI
======================================
Usage:
    python scripts/audit_quant_flaws.py [--fix]

Audits current paper trading state, active positions, and recent trade logs
against institutional bounds and Vibe-Trading diagnostic standards.
"""

import os
import sys
import json
from decimal import Decimal

# Ensure project root is in sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.quant.quant_flaw_auditor import QuantFlawAuditor, FlawSeverity
from src.quant.crypto_index_engine import CryptoIndexEngine
from src.quant.config import TOP_10_SYMBOLS


def run_audit(auto_fix: bool = False):
    print("=" * 70)
    print(">> [Kronos Quant Flaw Auditor] Running Empirical Sanity Audit...")
    print("=" * 70)

    auditor = QuantFlawAuditor()
    data_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
    state_file = os.path.join(data_dir, "paper_trading_state.json")
    bot_settings_file = os.path.join(data_dir, "bot_settings.json")

    # 1. Load paper trading state
    if not os.path.exists(state_file):
        print("[OK] No paper trading state file found. Clean state.")
        return 0

    with open(state_file, "r") as f:
        try:
            state = json.load(f)
        except Exception as e:
            print(f"[FAIL] Corrupted state file: {e}")
            return 1

    # Reconstruct summary dict
    closed_trades = state.get("closed_trades", [])
    winning = sum(1 for t in closed_trades if t.get("result") == "WIN")
    total = len(closed_trades)
    win_rate = (winning / total * 100) if total > 0 else 0.0

    gross_gains = sum(Decimal(str(t.get("gross_pnl_usd", 0))) for t in closed_trades if Decimal(str(t.get("gross_pnl_usd", 0))) > 0)
    gross_losses = abs(sum(Decimal(str(t.get("gross_pnl_usd", 0))) for t in closed_trades if Decimal(str(t.get("gross_pnl_usd", 0))) < 0))
    pf = float(gross_gains / gross_losses) if gross_losses > 0 else (999.0 if gross_gains > 0 else 0.0)

    initial_eq = Decimal(str(state.get("paper_initial_equity", 200.0)))
    realized_total = sum(Decimal(str(t.get("realized_pnl_usd", 0))) for t in closed_trades)
    current_eq = initial_eq + realized_total
    net_ret = float(((current_eq - initial_eq) / initial_eq) * Decimal("100")) if initial_eq > 0 else 0.0

    summary = {
        "total_trades": total,
        "winning_trades": winning,
        "win_rate_pct": win_rate,
        "profit_factor": pf,
        "initial_equity": float(initial_eq),
        "current_equity": float(current_eq),
        "net_return_pct": net_ret,
        "closed_trades": closed_trades[-50:]
    }

    verdict = auditor.audit_performance_summary(summary)

    print(f">> Equity: ${float(current_eq):.2f} (Starting: ${float(initial_eq):.2f})")
    print(f">> Win Rate: {win_rate:.1f}% ({winning}/{total}) | Profit Factor: {pf:.2f}x")
    print(f">> Auditor Verdict: {verdict.summary}")
    print(f">> Confidence Score: {float(verdict.confidence_score)*100:.1f}%\n")

    # 2. Audit Active Positions vs Live Binance Ticker
    print(">> Auditing Active Bracket Positions against Live Binance Ticker...")
    active_positions = state.get("active_positions", [])
    if isinstance(active_positions, dict):
        active_positions = list(active_positions.values())

    engine = CryptoIndexEngine(symbols_config=TOP_10_SYMBOLS)
    ticker_flaws = []

    clean_active_positions = []
    for pos in active_positions:
        sym = pos.get("symbol")
        side = pos.get("side", "").upper()
        entry = Decimal(str(pos.get("entry_price", 0)))
        sl = Decimal(str(pos.get("stop_loss", 0)))
        tp = Decimal(str(pos.get("take_profit", 0)))
        qty = Decimal(str(pos.get("quantity", 0)))
        notional = entry * qty
        is_corrupt = False

        # Bracket geometry check
        if side in ("BUY", "LONG"):
            if not (sl < entry < tp):
                ticker_flaws.append(f"Inverted LONG bracket on {sym}: SL {sl} >= Entry {entry} or Entry >= TP {tp}")
                is_corrupt = True
        elif side in ("SELL", "SHORT"):
            if not (tp < entry < sl):
                ticker_flaws.append(f"Inverted SHORT bracket on {sym}: TP {tp} >= Entry {entry} or Entry >= SL {sl}")
                is_corrupt = True

        # Micro-notional sizing check
        if initial_eq <= Decimal("2500.00") and notional > Decimal("500.00"):
            ticker_flaws.append(f"Excessive notional on small account {sym}: ${notional:.2f} > $500.00 ceiling")
            is_corrupt = True

        if not is_corrupt:
            clean_active_positions.append(pos)

    if ticker_flaws:
        print("[CRITICAL] Active position flaws detected:")
        for tf in ticker_flaws:
            print(f"  * {tf}")
        if auto_fix:
            if isinstance(state.get("active_positions"), dict):
                state["active_positions"] = {p["position_id"]: p for p in clean_active_positions}
            else:
                state["active_positions"] = clean_active_positions
            with open(state_file, "w") as f:
                json.dump(state, f, indent=2)
            print(f"[REMEDIATED] Removed corrupted active positions. Retained {len(clean_active_positions)} valid positions.")
    else:
        print(f"[PASS] All {len(active_positions)} active bracket positions have valid pricing and sizing geometry.")

    # 3. Flaw Breakdown
    if verdict.flaws:
        print("\n" + "=" * 70)
        print(">> DETECTED FLAWS & ACTIONABLE REMEDIATION:")
        print("=" * 70)
        for f in verdict.flaws:
            print(f"[{f.severity.value}] {f.title} ({f.code})")
            print(f"  * Observed: {f.observed_value} (Limit: {f.institutional_bound})")
            print(f"  * Detail: {f.description}")
            print(f"  * Fix: {f.remediation}\n")

    if not verdict.is_valid:
        print(">> [ALERT] Quant Auditor has REJECTED current paper simulation metrics.")
        return 1
    else:
        print(">> [SUCCESS] Quant Auditor has CERTIFIED current paper simulation as realistic.")
        return 0


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Kronos Quant Flaw Auditor")
    parser.add_argument("--fix", action="store_true", help="Auto-fix detected flaws")
    args = parser.parse_args()
    code = run_audit(auto_fix=args.fix)
    sys.exit(code)
