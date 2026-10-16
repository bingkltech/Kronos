"""
tests/test_headless_kalshi.py — Fast Unit Tests for Headless Kalshi Decision Engine.
Validates Zero Float Math, Kelly sizing boundaries, decision thresholds, and tail-slicing contracts.
"""

import os
import sys
from decimal import Decimal
import pandas as pd
import numpy as np
import pytest

WORKSPACE_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if WORKSPACE_ROOT not in sys.path:
    sys.path.insert(0, WORKSPACE_ROOT)

from scripts.headless_kalshi_agent import (
    KalshiMarketContract,
    KalshiDecisionEngine,
    BaseKronosBackend
)


class MockKronosBackend(BaseKronosBackend):
    """Deterministic mock backend simulating Kronos forecast trajectories without GPU/weights."""
    def __init__(self, terminal_close: float, path_std: float = 100.0):
        self.terminal_close = terminal_close
        self.path_std = path_std

    def predict_horizon(self, lookback_df: pd.DataFrame, pred_len: int) -> pd.DataFrame:
        start_price = float(lookback_df['close'].iloc[-1])
        prices = np.linspace(start_price, self.terminal_close, pred_len)
        return pd.DataFrame({
            'open': prices,
            'high': prices + self.path_std,
            'low': prices - self.path_std,
            'close': prices,
            'volume': np.full(pred_len, 100.0)
        })


def create_sample_lookback(n_bars: int = 400, spot_price: float = 80000.0) -> pd.DataFrame:
    timestamps = pd.date_range("2026-01-01", periods=n_bars, freq="h")
    prices = np.full(n_bars, spot_price)
    return pd.DataFrame({
        'timestamps': timestamps,
        'open': prices,
        'high': prices + 50.0,
        'low': prices - 50.0,
        'close': prices,
        'volume': np.full(n_bars, 10.0)
    })


def test_kalshi_zero_float_math_invariants():
    """Verify all monetary, edge, and probability fields in KalshiDecision are strictly Decimal."""
    backend = MockKronosBackend(terminal_close=82000.0)
    engine = KalshiDecisionEngine(backend=backend, min_edge_cents=Decimal("0.05"))

    contract = KalshiMarketContract(
        ticker="KXTEST-01",
        title="Test Bull Contract",
        underlying_symbol="BTCUSDT",
        strike_price=Decimal("81000.00"),
        expiry_horizon_steps=6,
        yes_ask=Decimal("0.40"),
        no_ask=Decimal("0.62")
    )

    lookback_df = create_sample_lookback(spot_price=80000.0)
    decision = engine.evaluate_contract(contract, lookback_df, bankroll=Decimal("2000.00"))

    # Strict type checks
    assert isinstance(decision.strike_price, Decimal)
    assert isinstance(decision.spot_price, Decimal)
    assert isinstance(decision.forecasted_terminal, Decimal)
    assert isinstance(decision.forecasted_return_pct, Decimal)
    assert isinstance(decision.model_prob_yes, Decimal)
    assert isinstance(decision.market_prob_yes, Decimal)
    assert isinstance(decision.edge, Decimal)
    assert isinstance(decision.expected_value, Decimal)
    assert isinstance(decision.capital_at_risk, Decimal)
    assert isinstance(decision.max_payout, Decimal)
    assert isinstance(decision.kelly_fraction, Decimal)
    assert isinstance(decision.recommended_contracts, int)

    # Ensure no floating point leaks
    assert not isinstance(decision.expected_value, float)
    assert not isinstance(decision.capital_at_risk, float)


def test_kalshi_buy_yes_decision():
    """Verify BUY_YES is triggered when terminal price strongly exceeds strike and EV >= hurdle."""
    # Terminal close $84,000 >> Strike $81,000 -> P_yes ~ 0.98
    backend = MockKronosBackend(terminal_close=84000.0, path_std=50.0)
    engine = KalshiDecisionEngine(backend=backend, min_edge_cents=Decimal("0.05"))

    contract = KalshiMarketContract(
        ticker="KXTEST-BULL",
        title="BTC Bull Strike",
        underlying_symbol="BTCUSDT",
        strike_price=Decimal("81000.00"),
        expiry_horizon_steps=6,
        yes_ask=Decimal("0.45"),
        no_ask=Decimal("0.58")
    )

    lookback_df = create_sample_lookback(spot_price=80000.0)
    bankroll = Decimal("1000.00")
    decision = engine.evaluate_contract(contract, lookback_df, bankroll=bankroll)

    assert decision.action == "BUY_YES"
    assert decision.edge > Decimal("0.05")
    assert decision.expected_value > Decimal("0.05")
    assert decision.recommended_contracts > 0
    # Must respect max bankroll allocation limit (10% of $1000 = $100)
    assert decision.capital_at_risk <= Decimal("100.00")
    assert decision.capital_at_risk > Decimal("0.00")


def test_kalshi_buy_no_decision():
    """Verify BUY_NO is triggered when terminal price falls well below strike."""
    # Terminal close $77,000 << Strike $80,000 -> P_yes ~ 0.02, P_no ~ 0.98
    backend = MockKronosBackend(terminal_close=77000.0, path_std=50.0)
    engine = KalshiDecisionEngine(backend=backend, min_edge_cents=Decimal("0.05"))

    contract = KalshiMarketContract(
        ticker="KXTEST-BEAR",
        title="BTC Bear Strike",
        underlying_symbol="BTCUSDT",
        strike_price=Decimal("80000.00"),
        expiry_horizon_steps=6,
        yes_ask=Decimal("0.40"),
        no_ask=Decimal("0.65")  # Market charges 65c for NO, model values it at 98c -> edge = +33c
    )

    lookback_df = create_sample_lookback(spot_price=80000.0)
    decision = engine.evaluate_contract(contract, lookback_df, bankroll=Decimal("1000.00"))

    assert decision.action == "BUY_NO"
    assert decision.edge > Decimal("0.05")
    assert decision.expected_value > Decimal("0.05")
    assert decision.recommended_contracts > 0


def test_kalshi_pass_when_no_edge():
    """Verify PASS is triggered when market spread eliminates edge below hurdle."""
    # Forecast close matches strike exactly -> P_yes ~ 0.50
    backend = MockKronosBackend(terminal_close=80000.0, path_std=200.0)
    engine = KalshiDecisionEngine(backend=backend, min_edge_cents=Decimal("0.05"))

    contract = KalshiMarketContract(
        ticker="KXTEST-FAIR",
        title="BTC Efficient Strike",
        underlying_symbol="BTCUSDT",
        strike_price=Decimal("80000.00"),
        expiry_horizon_steps=6,
        yes_ask=Decimal("0.52"),  # Asking 52c for 50% probability -> negative edge
        no_ask=Decimal("0.52")
    )

    lookback_df = create_sample_lookback(spot_price=80000.0)
    decision = engine.evaluate_contract(contract, lookback_df, bankroll=Decimal("1000.00"))

    assert decision.action == "PASS"
    assert decision.recommended_contracts == 0
    assert decision.capital_at_risk == Decimal("0.00")
    assert decision.max_payout == Decimal("0.00")


def test_kalshi_batch_evaluation():
    """Verify evaluate_contracts_batch correctly evaluates multiple contracts with a single forecast."""
    backend = MockKronosBackend(terminal_close=85000.0, path_std=60.0)
    engine = KalshiDecisionEngine(backend=backend, min_edge_cents=Decimal("0.05"))

    c1 = KalshiMarketContract(
        ticker="KXTEST-BULL-1",
        title="Strike 1",
        underlying_symbol="BTCUSDT",
        strike_price=Decimal("82000.00"),
        expiry_horizon_steps=6,
        yes_ask=Decimal("0.40"),
        no_ask=Decimal("0.65")
    )
    c2 = KalshiMarketContract(
        ticker="KXTEST-FAR-2",
        title="Strike 2 (Way OTM)",
        underlying_symbol="BTCUSDT",
        strike_price=Decimal("95000.00"),
        expiry_horizon_steps=6,
        yes_ask=Decimal("0.30"),
        no_ask=Decimal("0.72")
    )

    lookback_df = create_sample_lookback(spot_price=80000.0)
    results = engine.evaluate_contracts_batch([c1, c2], lookback_df, bankroll=Decimal("2000.00"))

    assert len(results) == 2
    assert results[0].ticker == "KXTEST-BULL-1"
    assert results[0].action == "BUY_YES"
    assert results[1].ticker == "KXTEST-FAR-2"
    assert results[1].action == "BUY_NO"
