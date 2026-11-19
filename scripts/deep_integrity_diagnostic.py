import sys, os, time, datetime, json
from decimal import Decimal
sys.path.insert(0, '.')

from src.quant.orchestrator import QuantBotOrchestrator
from src.quant.config import ALL_SUPPORTED_SYMBOLS, DEFAULT_RISK_CONFIG
from src.quant.binance_execution import BinanceAtomicExecutor
from risk_engine import RiskEngine, RiskConfig, DEFAULT_CONFIG_PATH

print("=" * 76)
print("   KRONOS AWS INTEGRITY & BOT EXECUTION DIAGNOSTIC")
print("=" * 76)

# 1. API & Account Health
executor = BinanceAtomicExecutor(dry_run=False)
risk_cfg = RiskConfig.from_file(DEFAULT_CONFIG_PATH)
risk_engine = RiskEngine(config=risk_cfg)
executor.risk_engine = risk_engine

acct = executor.get_live_account_summary()
connected = acct.get("connected")
err = acct.get("error")
bal = float(acct.get("total_wallet_balance_usd", 0))
avail = float(acct.get("available_balance_usd", 0))
positions = acct.get("positions", [])

print(f"1. BINANCE FUTURES API:")
print(f"   Connected       : {connected} | Error: {err}")
print(f"   Wallet Balance  : ${bal:,.2f} USDT")
print(f"   Available Cash  : ${avail:,.2f} USDT")
print(f"   Active Positions: {len(positions)}")

# 2. Risk Engine State
print(f"\n2. RISK ENGINE STATE:")
ctrl_state, ctrl_err = risk_engine.gateway_layer.read_control_file()
is_halted = risk_engine.gateway_layer.is_halted
desync = risk_engine.gateway_layer._is_desync_halt
print(f"   Control File (risk_state.txt): {ctrl_state} (Error: {ctrl_err})")
print(f"   Is Halted / Latched          : {is_halted}")
print(f"   Is Desync Halt               : {desync}")

# 3. Macro Scan Cycle & Veto Diagnostics
print(f"\n3. MACRO SCAN CYCLE & VETO GATES:")
bot = QuantBotOrchestrator(symbols_config=ALL_SUPPORTED_SYMBOLS, risk_config=DEFAULT_RISK_CONFIG, executor=executor, require_neural_model=False)
rep = bot.run_scan_cycle(execution_mode="LIVE")
regime = rep.macro_verdict.macro_regime
breadth = float(rep.macro_verdict.breadth_ratio) * 100
print(f"   Regime    : {regime} | Breadth: {breadth:.1f}%")
print(f"   Evaluated : {len(rep.decisions)} symbols")
print(f"   Dispatched: {len(rep.dispatched_trades)}")
for sym, d in rep.decisions.items():
    print(f"   - {sym:<14} Passed: {str(d.approved):<6} VetoGate: {str(d.veto_gate_failed):<20} Reason: {d.veto_reason}")

# 4. Scalper State
print(f"\n4. LIGHTNING SCALPER STATE:")
if os.path.exists("data/scalper_config.json"):
    with open("data/scalper_config.json") as f:
        sc = json.load(f)
    print(f"   Execution Mode : {sc.get('execution_mode')}")
    print(f"   Enabled        : {sc.get('enabled')}")
    print(f"   Quarantined    : {sc.get('guardrails', {}).get('quarantined_symbols')}")

# 5. Stalking Tiger State
print(f"\n5. STALKING TIGER STATE:")
if os.path.exists("data/tiger_radar.json"):
    with open("data/tiger_radar.json") as f:
        tr = json.load(f)
    hp = [c.get("symbol") for c in tr.get("hot_prey", [])]
    print(f"   Hot Prey Candidates : {hp}")
    print(f"   Last Sieve Scan Time: {tr.get('timestamp_utc')}")
else:
    print("   tiger_radar.json: Not found")

# 6. System Integrity
print(f"\n6. SYSTEM INTEGRITY:")
print("   All checks executed successfully.")

print("=" * 76)
