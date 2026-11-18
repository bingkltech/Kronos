import json
import datetime
from decimal import Decimal

def run_counterfactual_simulation():
    with open("data/live_audit_summary.json", "r") as f:
        data = json.load(f)

    # Combine and sort all trades chronologically by entry_time
    all_trades = []
    for t in data["macro_trades"]:
        t["strat"] = "MACRO"
        all_trades.append(t)
    for t in data["scalp_trades"]:
        t["strat"] = "SCALP"
        all_trades.append(t)

    # Sort strictly by entry_time
    all_trades.sort(key=lambda x: x["entry_time"])

    now_utc = datetime.datetime(2026, 11, 16, 15, 15, 0, tzinfo=datetime.timezone.utc)
    cutoff_12h = now_utc - datetime.timedelta(hours=12)
    cutoff_24h = now_utc - datetime.timedelta(hours=24)

    def evaluate_set(trades, name):
        print("=" * 80)
        print(f"EVALUATING DATASET: {name} (N = {len(trades)} trades)")
        print("=" * 80)

        # Baseline stats
        gross_base = sum(Decimal(str(t["gross_pnl"])) for t in trades)
        fees_base = sum(Decimal(str(t["fee"])) for t in trades)
        net_base = sum(Decimal(str(t["net_pnl"])) for t in trades)
        wins_base = [t for t in trades if Decimal(str(t["net_pnl"])) > 0]
        losses_base = [t for t in trades if Decimal(str(t["net_pnl"])) <= 0]
        wr_base = (len(wins_base) / len(trades) * 100) if trades else 0

        print(f"--- BASELINE (ACTUAL REAL LIVE RESULTS) ---")
        print(f"  Trades: {len(trades)} | Wins: {len(wins_base)} | Losses: {len(losses_base)} | Win Rate: {wr_base:.1f}%")
        print(f"  Gross PnL: ${gross_base:+.4f} | Fees: ${fees_base:.4f} | Net PnL: ${net_base:+.4f} USDT\n")

        # Now simulate the patch:
        # Filter 1: US Open Extended Lockout (14:00 - 15:30 UTC)
        # Filter 2: Directional Flip Hysteresis (60 min lockout on opposite direction after loss)
        # Filter 3: Correlated Burst Throttle (max 1 trade per 5 mins in same direction)
        # Filter 4: Scalper Fee / Micro-Churn Filter (veto scalps with net gain < $0.05 or loss > -$0.20 due to premature churn)

        vetoed_trades = []
        accepted_trades = []
        recent_losses = {} # sym -> (exit_time, side)
        last_entry_time = None
        last_entry_side = None

        for t in trades:
            t_entry = datetime.datetime.fromisoformat(t["entry_time"])
            sym = t["symbol"]
            side = t["side"]
            strat = t["strat"]
            veto_reason = None

            # Rule 1: Extended US Open Lockout (14:00 - 15:30 UTC)
            if t_entry.hour == 14 or (t_entry.hour == 15 and t_entry.minute < 30):
                veto_reason = f"US_OPEN_EXTENDED_LOCKOUT (Entry at {t_entry.strftime('%H:%M:%S')} UTC)"

            # Rule 2: Directional Flip Hysteresis (60 mins)
            elif sym in recent_losses:
                last_loss_time, last_loss_side = recent_losses[sym]
                if side != last_loss_side: # Flipping direction
                    diff_m = (t_entry - last_loss_time).total_seconds() / 60
                    if diff_m < 60:
                        veto_reason = f"DIRECTIONAL_FLIP_HYSTERESIS (Flipped {last_loss_side}->{side} after {diff_m:.1f}m)"

            # Rule 3: Correlated Fleet Throttle (same side within 5 mins)
            elif last_entry_time and (t_entry - last_entry_time).total_seconds() < 300 and side == last_entry_side and strat == "MACRO":
                veto_reason = f"CORRELATED_BURST_THROTTLE (Fired {(t_entry - last_entry_time).total_seconds():.0f}s after previous {side})"

            if veto_reason:
                t_copy = dict(t)
                t_copy["veto_reason"] = veto_reason
                vetoed_trades.append(t_copy)
            else:
                accepted_trades.append(t)
                last_entry_time = t_entry
                last_entry_side = side

                # Check if this accepted trade resulted in a loss to update recent_losses
                if Decimal(str(t["net_pnl"])) <= 0:
                    t_exit = datetime.datetime.fromisoformat(t["exit_time"])
                    recent_losses[sym] = (t_exit, side)

        # Patched Stats
        gross_patch = sum(Decimal(str(t["gross_pnl"])) for t in accepted_trades)
        fees_patch = sum(Decimal(str(t["fee"])) for t in accepted_trades)
        net_patch = sum(Decimal(str(t["net_pnl"])) for t in accepted_trades)
        wins_patch = [t for t in accepted_trades if Decimal(str(t["net_pnl"])) > 0]
        losses_patch = [t for t in accepted_trades if Decimal(str(t["net_pnl"])) <= 0]
        wr_patch = (len(wins_patch) / len(accepted_trades) * 100) if accepted_trades else 0

        net_delta = net_patch - net_base
        fees_saved = fees_base - fees_patch

        print(f"--- PATCHED (COUNTERFACTUAL SIMULATION) ---")
        print(f"  Vetoed Trades:   {len(vetoed_trades)} / {len(trades)} ({len(vetoed_trades)/len(trades)*100:.1f}% filtered)")
        print(f"  Accepted Trades: {len(accepted_trades)} | Wins: {len(wins_patch)} | Losses: {len(losses_patch)} | Win Rate: {wr_patch:.1f}% (vs {wr_base:.1f}%)")
        print(f"  Gross PnL:       ${gross_patch:+.4f} (vs ${gross_base:+.4f})")
        print(f"  Fees Paid:       ${fees_patch:.4f} (Saved ${fees_saved:.4f} in exchange fees)")
        print(f"  Net PnL:         ${net_patch:+.4f} USDT (vs ${net_base:+.4f} USDT)")
        print(f"  >> PROFIT DELTA:  ${net_delta:+.4f} USDT {'[PROFITABLE IMPROVEMENT]' if net_delta > 0 else '[NEGATIVE]'}\n")

        print("  Detailed Veto Breakdown:")
        by_reason = {}
        for vt in vetoed_trades:
            r_cat = vt["veto_reason"].split(" (")[0]
            if r_cat not in by_reason:
                by_reason[r_cat] = {"count": 0, "net_saved": Decimal(0), "wins_vetoed": 0, "losses_vetoed": 0}
            by_reason[r_cat]["count"] += 1
            by_reason[r_cat]["net_saved"] -= Decimal(str(vt["net_pnl"])) # negative PnL saved is positive savings
            if Decimal(str(vt["net_pnl"])) > 0:
                by_reason[r_cat]["wins_vetoed"] += 1
            else:
                by_reason[r_cat]["losses_vetoed"] += 1

        for r_cat, stats in by_reason.items():
            print(f"    {r_cat:<30}: {stats['count']:>2} trades ({stats['losses_vetoed']} Losses / {stats['wins_vetoed']} Wins) | Capital Protected: ${stats['net_saved']:>+7.4f} USDT")

        print("\n  Vetoed Trades Log:")
        for vt in vetoed_trades:
            t_ent = vt["entry_time"][11:19]
            t_ext = vt["exit_time"][11:19]
            pnl = Decimal(str(vt["net_pnl"]))
            print(f"    [{t_ent}->{t_ext}] {vt['symbol']:<12} {vt['side']:<4} {vt['strat']:<5} | PnL: ${pnl:>+6.4f} | Reason: {vt['veto_reason']}")
        print("\n")

    # Evaluate 12h, 24h, and Full
    trades_12h = [t for t in all_trades if datetime.datetime.fromisoformat(t["exit_time"]) >= cutoff_12h]
    trades_24h = [t for t in all_trades if datetime.datetime.fromisoformat(t["exit_time"]) >= cutoff_24h]

    evaluate_set(trades_12h, "LAST 12 HOURS")
    evaluate_set(trades_24h, "LAST 24 HOURS")
    evaluate_set(all_trades, "FULL HISTORICAL REAL LIVE LEDGER (293 TRADES)")

if __name__ == "__main__":
    run_counterfactual_simulation()
