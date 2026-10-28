"""
tests/test_quant_config.py — ASVL Verification Suite for src/quant/config.py.

Validates:
1. Exact registration of Top 10 Binance USD(S)-M Futures symbols.
2. Invariant 1: Zero Float Financial Math (all numerical fields are decimal.Decimal).
3. Price and Quantity precision quantization rules.
4. Round-trip friction calculations (Taker vs Maker Sniper).
5. Global risk constants and safety thresholds.
"""

import os
import sys
from decimal import Decimal

# Add workspace root to sys.path
WORKSPACE_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if WORKSPACE_ROOT not in sys.path:
    sys.path.insert(0, WORKSPACE_ROOT)

from src.quant.config import TOP_10_SYMBOLS, ALL_SUPPORTED_SYMBOLS, DEFAULT_RISK_CONFIG, FuturesSymbolConfig


def test_top_10_symbols_presence():
    """Verify core 10 index symbols and extended meme symbols."""
    core_10 = [
        "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT",
        "DOGEUSDT", "ADAUSDT", "AVAXUSDT", "LINKUSDT", "SUIUSDT"
    ]
    assert len(TOP_10_SYMBOLS) == 10
    for sym in core_10:
        assert sym in TOP_10_SYMBOLS, f"Symbol {sym} missing from TOP_10_SYMBOLS"

    # Verify extended universe contains PEPE
    assert "1000PEPEUSDT" in ALL_SUPPORTED_SYMBOLS
    assert "PEPEUSDT" in ALL_SUPPORTED_SYMBOLS
    assert len(ALL_SUPPORTED_SYMBOLS) == 12


def test_zero_float_invariants():
    """Verify strictly no IEEE 754 floats exist in symbol and risk configurations."""
    for sym, cfg in ALL_SUPPORTED_SYMBOLS.items():
        assert isinstance(cfg.min_quantity, Decimal)
        assert isinstance(cfg.min_notional, Decimal)
        assert isinstance(cfg.taker_fee_rate, Decimal)
        assert isinstance(cfg.maker_fee_rate, Decimal)
        assert isinstance(cfg.est_slippage_rate, Decimal)
        assert not any(isinstance(v, float) for v in cfg.__dict__.values())

    risk = DEFAULT_RISK_CONFIG
    assert isinstance(risk.base_risk_budget_ratio, Decimal)
    assert isinstance(risk.max_pair_correlation, Decimal)
    assert isinstance(risk.daily_drawdown_limit_ratio, Decimal)
    assert isinstance(risk.min_net_fee_hurdle, Decimal)
    assert isinstance(risk.min_rr_ratio, Decimal)
    assert isinstance(risk.breadth_bull_threshold, Decimal)
    assert isinstance(risk.breadth_bear_threshold, Decimal)
    assert isinstance(risk.max_prohibitive_funding_rate, Decimal)


def test_price_and_quantity_quantization():
    """Verify rounding down on quantity and round-half-up on prices."""
    btc = TOP_10_SYMBOLS["BTCUSDT"]
    # BTC price precision is 2 decimals
    raw_price = Decimal("67432.146")
    quantized_price = btc.quantize_price(raw_price)
    assert quantized_price == Decimal("67432.15")

    # BTC quantity precision is 3 decimals (stepSize 0.001)
    raw_qty = Decimal("0.123999")
    quantized_qty = btc.quantize_quantity(raw_qty)
    assert quantized_qty == Decimal("0.123")  # Must truncate/round down, NEVER round up

    doge = TOP_10_SYMBOLS["DOGEUSDT"]
    # DOGE qty precision is 0 decimals (integer lots)
    assert doge.quantize_quantity(Decimal("456.9")) == Decimal("456")
    # DOGE price precision is 5 decimals
    assert doge.quantize_price(Decimal("0.145674")) == Decimal("0.14567")
    assert doge.quantize_price(Decimal("0.145676")) == Decimal("0.14568")

    pepe = ALL_SUPPORTED_SYMBOLS["1000PEPEUSDT"]
    # 1000PEPE price precision is 7 decimals
    assert pepe.quantize_price(Decimal("0.009456784")) == Decimal("0.0094568")
    # 1000PEPE qty precision is 0 decimals (integer lots)
    assert pepe.quantize_quantity(Decimal("1520.8")) == Decimal("1520")


def test_friction_calculations():
    """Verify round-trip friction logic."""
    eth = TOP_10_SYMBOLS["ETHUSDT"]
    # Taker friction: 2 * 0.0005 + 2 * 0.0003 = 0.0016 (0.16%)
    taker_friction = eth.round_trip_taker_friction()
    assert taker_friction == Decimal("0.0016")

    # Maker sniper friction: 0.0002 + 0.0005 + 0.0003 = 0.0010 (0.10%)
    maker_friction = eth.round_trip_maker_friction()
    assert maker_friction == Decimal("0.0010")
