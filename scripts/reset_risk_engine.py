import sys, os
sys.path.insert(0, '.')
from risk_engine import RiskEngine, RiskConfig, DEFAULT_CONFIG_PATH

# 1. Set risk_state.txt to ACTIVE
with open('data/risk_state.txt', 'w') as f:
    f.write('ACTIVE\n')

# 2. Reset RiskEngine latch in database
cfg = RiskConfig.from_file(DEFAULT_CONFIG_PATH)
engine = RiskEngine(config=cfg)
ok = engine.manual_reset('admin', 'operational_latch_clear')
print(f"Reset OK: {ok}")
print(f"Is Halted now: {engine.gateway_layer.is_halted}")
