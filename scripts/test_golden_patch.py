import json
import datetime
from decimal import Decimal

with open("data/live_audit_summary.json", "r") as f:
    data = json.load(f)

all_trades = []
for t in data["macro_trades"]:
    t["strat"] = "MACRO"
    all_trades.append(t)
for t in data["scalp_trades"]:
    t["strat"] = "SCALP"
    all_trades.append(t)
all_trades.sort(key=lambda x: x["entry_time"])

now_utc = datetime.datetime(2026, 11, 16, 15, 15, 0, tzinfo=datetime.timezone.utc)
cutoff_12h = now_utc - datetime.timedelta(hours=12)
cutoff_24h = now_utc - datetime.timedelta(hours=24)

def evaluate_golden_patch(trades, name):
    gross_base = sum(Decimal(str(t["gross_pnl"])) for t in trades)
    fees_base = sum(Decimal(str(t["fee"])) for t in trades)
    net_base = sum(Decimal(str(t["net_pnl"])) for t in trades)
    wins_base = [t for t in trades if Decimal(str(t["net_pnl"])) > 0]
    wr_base = (len(wins_base) / len(trades) * 100) if trades else 0

    accepted = []
    vetoed = []
    recent_losses = {} # sym -> (exit_time, side)

    for idx, t in enumerate(trades):
        te = datetime.datetime.fromisoformat(t["entry_time"])
        sym = t["symbol"]
        side = t["side"]
        strat = t["strat"]
        veto_reason = None

        # 1. Extended US Open Lockout (14:00 - 15:30 UTC)
        if te.hour == 14 or (te.hour == 15 and te.minute < 30):
            veto_reason = "US_OPEN_LOCKOUT (14:00-15:30 UTC)"

        # 2. Directional Flip Hysteresis (30m)
        elif sym in recent_losses:
            last_ext, last_side = recent_losses[sym]
            if side != last_side:
                diff_m = (te - last_ext).total_seconds() / 60
                if 0 <= diff_m < 30:
                    veto_reason = f"DIRECTIONAL_FLIP_HYSTERESIS (30m: {last_side}->{side})"

        if veto_reason:
            t_copy = dict(t)
            t_copy["veto_reason"] = veto_reason
            vetoed.append(t_copy)
        else:
            accepted.append(t)
            if Decimal(str(t["net_pnl"])) < 0:
                recent_losses[sym] = (datetime.datetime.fromisoformat(t["exit_time"]), side)

    gross_patch = sum(Decimal(str(t["gross_pnl"])) for t in accepted)
    fees_patch = sum(Decimal(str(t["fee"])) for t in accepted)
    net_patch = sum(Decimal(str(t["net_pnl"])) for t in accepted)
    wins_patch = [t for t in accepted if Decimal(str(t["net_pnl"])) > 0]
    wr_patch = (len(wins_patch) / len(accepted) * 100) if accepted else 0

    print("=" * 75)
    print(f"RESULTS FOR: {name} (Total: {len(trades)})")
    print(f"  Baseline Net PnL:  ${net_base:>+7.4f} USDT | WR: {wr_base:.1f}% | Fees: ${fees_base:.4f}")
    print(f"  Patched Net PnL:   ${net_patch:>+7.4f} USDT | WR: {wr_patch:.1f}% | Fees: ${fees_patch:.4f}")
    print(f"  Net Delta (Gain):  ${net_patch - net_base:>+7.4f} USDT {'[PROFITABLE]' if net_patch > net_base else '[UNPROFITABLE]'}")
    print(f"  Vetoed Breakdown:  {len(vetoed)} trades filtered ({len([t for t in vetoed if Decimal(str(t['net_pnl'])) <= 0])} Losses / {len([t for t in vetoed if Decimal(str(t['net_pnl'])) > 0])} Wins)")
    print(f"  Fees Saved:        ${fees_base - fees_patch:.4f} USDT")

trades_12h = [t for t in all_trades if datetime.datetime.fromisoformat(t["exit_time"]) >= cutoff_12h]
trades_24h = [t for t in all_trades if datetime.datetime.fromisoformat(t["exit_time"]) >= cutoff_24h]

evaluate_golden_patch(trades_12h, "LAST 12 HOURS")
evaluate_golden_patch(trades_24h, "LAST 24 HOURS")
evaluate_golden_patch(all_trades, "FULL HISTORICAL LEDGER (293 REAL TRADES)")
