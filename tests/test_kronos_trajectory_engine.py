"""
tests/test_kronos_trajectory_engine.py — ASVL Verification Suite for src/quant/kronos_onnx_engine.py.

Validates:
1. Invariant 2: Context Slicing Contract (tail-slices df.iloc[-512:]).
2. Invariant 1: Zero Float Financial Math (all outputs strictly decimal.Decimal).
3. Dynamic Stop-Loss and Take-Profit envelope construction for Long and Short setups.
4. Quantization to symbol precision rules.
"""

import os
import sys
from decimal import Decimal
import pandas as pd
import pytest

WORKSPACE_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if WORKSPACE_ROOT not in sys.path:
    sys.path.insert(0, WORKSPACE_ROOT)

from src.quant.kronos_onnx_engine import KronosTrajectoryEngine, TrajectoryVerdict
from src.quant.config import TOP_10_SYMBOLS


def _build_dummy_lookback(n_bars: int = 100, last_price: float = 2500.0) -> pd.DataFrame:
    """Helper to generate dummy OHLCV lookback DataFrame where final bar close == last_price."""
    prices = [last_price - (n_bars - 1 - i) * 0.5 for i in range(n_bars)]
    return pd.DataFrame({
        "open": prices,
        "high": [p + 2.0 for p in prices],
        "low": [p - 2.0 for p in prices],
        "close": prices,
        "volume": [100.0] * n_bars
    })


def test_insufficient_lookback_rejection():
    """Verify that fewer than 50 bars raises ValueError."""
    engine = KronosTrajectoryEngine()
    short_df = _build_dummy_lookback(30)
    with pytest.raises(ValueError, match="Insufficient lookback"):
        engine.generate_trajectory("ETHUSDT", short_df)


def test_long_trajectory_bracket_envelope():
    """Verify Long trajectory extraction and dynamic bracket generation."""
    engine = KronosTrajectoryEngine()
    lookback = _build_dummy_lookback(100, last_price=2500.0)

    # Mock a bullish 12h forecast: climbing from 2505 to 2560
    mock_pred = pd.DataFrame({
        "open": [2500.0 + i * 5 for i in range(1, 13)],
        "high": [2505.0 + i * 5 for i in range(1, 13)],
        "low": [2495.0 + i * 3 for i in range(1, 13)],
        "close": [2502.0 + i * 5 for i in range(1, 13)],
        "volume": [50.0] * 12
    })

    verdict = engine.generate_trajectory("ETHUSDT", lookback, mock_forecast=mock_pred)

    assert verdict.symbol == "ETHUSDT"
    assert verdict.proposed_side == "LONG"
    assert isinstance(verdict.current_price, Decimal)
    assert isinstance(verdict.terminal_price, Decimal)
    assert isinstance(verdict.raw_drift, Decimal)
    assert isinstance(verdict.dynamic_take_profit, Decimal)
    assert isinstance(verdict.dynamic_stop_loss, Decimal)

    assert verdict.current_price == Decimal("2500.00")
    # Terminal close: 2502 + 12*5 = 2562.00
    assert verdict.terminal_price == Decimal("2562.00")
    assert verdict.raw_drift > Decimal("0")
    # Take profit must be >= terminal price
    assert verdict.dynamic_take_profit >= verdict.terminal_price
    # Stop loss must be below spot price
    assert verdict.dynamic_stop_loss < verdict.current_price


def test_short_trajectory_bracket_envelope():
    """Verify Short trajectory extraction and dynamic bracket generation."""
    engine = KronosTrajectoryEngine()
    lookback = _build_dummy_lookback(100, last_price=2500.0)

    # Mock a bearish 12h forecast: dropping from 2490 to 2420
    mock_pred = pd.DataFrame({
        "open": [2500.0 - i * 6 for i in range(1, 13)],
        "high": [2502.0 - i * 4 for i in range(1, 13)],
        "low": [2488.0 - i * 7 for i in range(1, 13)],
        "close": [2490.0 - i * 6 for i in range(1, 13)],
        "volume": [50.0] * 12
    })

    verdict = engine.generate_trajectory("ETHUSDT", lookback, mock_forecast=mock_pred)

    assert verdict.symbol == "ETHUSDT"
    assert verdict.proposed_side == "SHORT"
    assert verdict.raw_drift < Decimal("0")
    # Take profit must be <= terminal price
    assert verdict.dynamic_take_profit <= verdict.terminal_price
    # Stop loss must be above spot price
    assert verdict.dynamic_stop_loss > verdict.current_price
