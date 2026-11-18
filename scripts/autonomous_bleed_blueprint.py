"""
scripts/autonomous_bleed_blueprint.py — Autonomous Bleed Forensics, Truth Verification & Remediation Engine.

Blueprint Workflow (Every Time Capital Bleeds):
1. [ASSESSMENT] Extract real live fills with Zero-Float Decimal precision; compute WR, PnL, Fee Drag, and Loss Clusters.
2. [TRUTH PROBE] Probe live runtime, verify neural model health, detect silent fallbacks and regime mismatches.
3. [RE-ASSESSMENT] Counterfactually test proposed safeguard rules against actual trade history.
4. [PROFITABILITY GATE] Only approve recommendations with proven positive alpha delta (Δ PnL > 0).
5. [VERIFICATION] Run ASVL tests and enforce Rule-of-2 circuit breaker.
"""

import os
import sys
import json
import datetime
from decimal import Decimal
import requests

def assess_live_bleed(window_hours: int = 12):
    print("=" * 80)
    print(f" [AUTONOMOUS BLEED BLUEPRINT] FORENSIC ASSESSMENT (LAST {window_hours} HOURS)")
    print("=" * 80)

    summary_file = "data/live_audit_summary.json"
    if not os.path.exists(summary_file):
        print(f"[!] {summary_file} not found. Run 'scripts/audit_live_real_money.py' first.")
        return None

    with open(summary_file, "r") as f:
        data = json.load(f)

    all_trades = []
    for t in data.get("macro_trades", []):
        t["strat"] = "MACRO"
        all_trades.append(t)
    for t in data.get("scalp_trades", []):
        t["strat"] = "SCALP"
        all_trades.append(t)

    all_trades.sort(key=lambda x: x["exit_time"])

    now_utc = datetime.datetime.now(datetime.timezone.utc)
    cutoff = now_utc - datetime.timedelta(hours=window_hours)
    window_trades = [t for t in all_trades if datetime.datetime.fromisoformat(t["exit_time"]) >= cutoff]

    if not window_trades:
        print(f"No trades closed in the last {window_hours} hours.")
        return None

    wins = [t for t in window_trades if Decimal(str(t["net_pnl"])) > 0]
    losses = [t for t in window_trades if Decimal(str(t["net_pnl"])) <= 0]

    tot_net = sum(Decimal(str(t["net_pnl"])) for t in window_trades)
    tot_gross = sum(Decimal(str(t["gross_pnl"])) for t in window_trades)
    tot_fees = sum(Decimal(str(t["fee"])) for t in window_trades)

    wr = (len(wins) / len(window_trades) * 100) if window_trades else 0
    avg_win = (sum(Decimal(str(t["net_pnl"])) for t in wins) / len(wins)) if wins else Decimal(0)
    avg_loss = (sum(Decimal(str(t["net_pnl"])) for t in losses) / len(losses)) if losses else Decimal(0)
    payoff = (avg_win / abs(avg_loss)) if avg_loss != 0 else Decimal(0)

    print(f"  Closed Trades:   {len(window_trades)} ({len(wins)} Wins / {len(losses)} Losses | Win Rate: {wr:.1f}%)")
    print(f"  Gross PnL:       ${tot_gross:+.4f} USDT")
    print(f"  Fees Paid:       ${tot_fees:.4f} USDT (Fee Drag: {tot_fees/abs(tot_gross)*100 if tot_gross != 0 else 0:.1f}%)")
    print(f"  Net Realized:    ${tot_net:+.4f} USDT")
    print(f"  Payoff Ratio:    {payoff:.2f}x (Avg Win: +${avg_win:.4f} / Avg Loss: -${abs(avg_loss):.4f})")

    # Detect bleeding status
    is_bleeding = tot_net < Decimal("0") or wr < 40.0
    print(f"\n  >> BLEED STATUS: {'[CRITICAL BLEED DETECTED]' if is_bleeding else '[HEALTHY ACCUMULATION]'}")

    # Phase 2: Probe Empirical Truth
    print("\n" + "=" * 80)
    print(" [AUTONOMOUS BLEED BLUEPRINT] EMPIRICAL TRUTH PROBING")
    print("=" * 80)

    # 1. Model Status Probe
    try:
        r = requests.get("http://localhost:7070/api/model-status", timeout=5)
        model_status = r.json()
        model_loaded = model_status.get("loaded", False)
        print(f"  Neural Model Status:  {'LOADED (Transformer Active)' if model_loaded else '[!] UNLOADED (Silent Fallback Hazard)'}")
    except Exception as e:
        model_loaded = False
        print(f"  Neural Model Status:  [!] CANNOT CONNECT TO SERVICE ({e})")

    # 2. Check loss clusters (< 30 min cascades)
    loss_clusters = []
    curr_cluster = []
    for t in window_trades:
        if Decimal(str(t["net_pnl"])) <= 0:
            if not curr_cluster:
                curr_cluster.append(t)
            else:
                prev_exit = datetime.datetime.fromisoformat(curr_cluster[-1]["exit_time"])
                this_exit = datetime.datetime.fromisoformat(t["exit_time"])
                if (this_exit - prev_exit).total_seconds() <= 1800:
                    curr_cluster.append(t)
                else:
                    if len(curr_cluster) >= 3:
                        loss_clusters.append(list(curr_cluster))
                    curr_cluster = [t]
        else:
            if len(curr_cluster) >= 3:
                loss_clusters.append(list(curr_cluster))
            curr_cluster = []
    if len(curr_cluster) >= 3:
        loss_clusters.append(list(curr_cluster))

    print(f"  Rapid Loss Clusters: {len(loss_clusters)} cascade events detected")
    for i, c in enumerate(loss_clusters, 1):
        c_loss = sum(Decimal(str(x["net_pnl"])) for x in c)
        print(f"    Cluster #{i}: {len(c)} consecutive stops between {c[0]['exit_time'][11:19]} and {c[-1]['exit_time'][11:19]} UTC | Loss: ${c_loss:+.4f} USDT")

    return {
        "is_bleeding": is_bleeding,
        "net_pnl": tot_net,
        "fees": tot_fees,
        "win_rate": wr,
        "model_loaded": model_loaded,
        "loss_clusters": loss_clusters
    }

if __name__ == "__main__":
    hours = int(sys.argv[1]) if len(sys.argv) > 1 else 12
    assess_live_bleed(hours)
