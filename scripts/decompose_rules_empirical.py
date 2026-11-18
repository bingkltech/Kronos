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

def test_single_rule(name, rule_fn, dataset, ds_name):
    vetoed = [t for t in dataset if rule_fn(t, dataset)]
    losses_vetoed = [t for t in vetoed if Decimal(str(t["net_pnl"])) <= 0]
    wins_vetoed = [t for t in vetoed if Decimal(str(t["net_pnl"])) > 0]
    
    saved_pnl = sum(-Decimal(str(t["net_pnl"])) for t in vetoed)
    fees_saved = sum(Decimal(str(t["fee"])) for t in vetoed)
    
    print(f"[{ds_name}] {name}:")
    print(f"  Vetoed: {len(vetoed)} ({len(losses_vetoed)} Losses / {len(wins_vetoed)} Wins)")
    print(f"  Net Capital Protected: ${saved_pnl:>+7.4f} USDT | Fees Saved: ${fees_saved:.4f}")

# Rule 1: Extended US Open Lockout (14:00 - 15:30 UTC)
def rule_us_open(t, dataset):
    te = datetime.datetime.fromisoformat(t["entry_time"])
    return te.hour == 14 or (te.hour == 15 and te.minute < 30)

# Rule 2: Correlated Burst Throttle (same side Macro trade within 5 mins of previous)
def rule_burst(t, dataset):
    if t["strat"] != "MACRO":
        return False
    te = datetime.datetime.fromisoformat(t["entry_time"])
    idx = dataset.index(t)
    for prev in dataset[max(0, idx-5):idx]:
        if prev["strat"] == "MACRO" and prev["side"] == t["side"]:
            prev_te = datetime.datetime.fromisoformat(prev["entry_time"])
            if 0 < (te - prev_te).total_seconds() < 300:
                return True
    return False

# Rule 3: Directional Flip Hysteresis within 30 mins after stop loss
def rule_flip_30m(t, dataset):
    te = datetime.datetime.fromisoformat(t["entry_time"])
    sym = t["symbol"]
    side = t["side"]
    idx = dataset.index(t)
    for prev in dataset[max(0, idx-10):idx]:
        if prev["symbol"] == sym and prev["side"] != side and Decimal(str(prev["net_pnl"])) < 0:
            prev_ext = datetime.datetime.fromisoformat(prev["exit_time"])
            diff_m = (te - prev_ext).total_seconds() / 60
            if 0 <= diff_m < 30:
                return True
    return False

# Rule 4: Exclude toxic PEPE from scalper
def rule_exclude_pepe_scalp(t, dataset):
    return t["strat"] == "SCALP" and t["symbol"] == "1000PEPEUSDT"

trades_12h = [t for t in all_trades if datetime.datetime.fromisoformat(t["exit_time"]) >= cutoff_12h]
trades_24h = [t for t in all_trades if datetime.datetime.fromisoformat(t["exit_time"]) >= cutoff_24h]

for ds, ds_name in [(trades_12h, "12H"), (trades_24h, "24H"), (all_trades, "FULL_293")]:
    print("=" * 60)
    test_single_rule("Rule 1: Extended US Open Lockout (14:00-15:30)", rule_us_open, ds, ds_name)
    test_single_rule("Rule 2: Correlated Burst Throttle (Macro 5m)", rule_burst, ds, ds_name)
    test_single_rule("Rule 3: Directional Flip Hysteresis (30m)", rule_flip_30m, ds, ds_name)
    test_single_rule("Rule 4: Exclude 1000PEPE from Scalper", rule_exclude_pepe_scalp, ds, ds_name)
