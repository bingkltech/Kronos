"""
tests/test_binance_futures_bot.py — Unit Tests for Binance Futures Kronos Strategy Engine.
Validates Zero Float Math, fee hurdle filters, Risk/Reward constraints, and risk-budget sizing.
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

from scripts.binance_futures_kronos_bot import (
    FuturesSymbolConfig,
    FuturesTradeSignal,
    KronosFuturesStrategy
)


class MockForecastStrategy(KronosFuturesStrategy):
    """Deterministic mock strategy returning predetermined Kronos forecast paths."""
    def __init__(self, terminal_close: float, path_high: float, path_low: float, **kwargs):
        super().__init__(**kwargs)
        self.mock_terminal = terminal_close
        self.mock_high = path_high
        self.mock_low = path_low

    def generate_forecast(self, lookback_df: pd.DataFrame, pred_len: int = 12) -> pd.DataFrame:
        start_p = float(lookback_df['close'].iloc[-1])
        closes = np.linspace(start_p, self.mock_terminal, pred_len)
        return pd.DataFrame({
            'open': closes,
            'high': np.full(pred_len, self.mock_high),
            'low': np.full(pred_len, self.mock_low),
            'close': closes,
            'volume': np.full(pred_len, 50.0)
        })


def make_dummy_lookback(n_bars: int = 400, spot: float = 80000.0) -> pd.DataFrame:
    timestamps = pd.date_range("2026-01-01", periods=n_bars, freq="h")
    return pd.DataFrame({
        'timestamps': timestamps,
        'open': np.full(n_bars, spot),
        'high': np.full(n_bars, spot + 100.0),
        'low': np.full(n_bars, spot - 100.0),
        'close': np.full(n_bars, spot),
        'volume': np.full(n_bars, 20.0)
    })


def test_zero_float_math_invariants():
    """Verify all monetary and sizing fields in FuturesTradeSignal are strictly Decimal."""
    strat = MockForecastStrategy(
        terminal_close=82500.0, # +3.1% bullish drift
        path_high=83000.0,
        path_low=79500.0,
        min_hurdle_pct=Decimal("0.005")
    )
    cfg = FuturesSymbolConfig(symbol="BTCUSDT", price_precision=2, quantity_precision=3, min_quantity=Decimal("0.001"))
    lookback = make_dummy_lookback(spot=80000.0)

    signal = strat.evaluate_market(cfg, lookback, account_equity=Decimal("10000.00"))

    assert signal.direction == "LONG"
    assert isinstance(signal.entry_price, Decimal)
    assert isinstance(signal.stop_loss, Decimal)
    assert isinstance(signal.take_profit, Decimal)
    assert isinstance(signal.position_quantity, Decimal)
    assert isinstance(signal.notional_value_usd, Decimal)
    assert isinstance(signal.margin_required_usd, Decimal)
    assert isinstance(signal.capital_at_risk_usd, Decimal)
    assert isinstance(signal.est_roundtrip_fee_usd, Decimal)
    assert isinstance(signal.net_expected_profit_usd, Decimal)

    # Floating point math leak detection
    assert not isinstance(signal.capital_at_risk_usd, float)
    assert not isinstance(signal.position_quantity, float)


def test_fee_hurdle_rejection():
    """Verify that small drifts (e.g. +0.2%) below the fee hurdle are rejected as NEUTRAL."""
    strat = MockForecastStrategy(
        terminal_close=80160.0, # +0.20% drift (eaten by 0.16% roundtrip fees)
        path_high=80300.0,
        path_low=79800.0,
        min_hurdle_pct=Decimal("0.0050") # Requires at least 0.50% net drift
    )
    cfg = FuturesSymbolConfig(symbol="BTCUSDT", price_precision=2, quantity_precision=3, min_quantity=Decimal("0.001"))
    lookback = make_dummy_lookback(spot=80000.0)

    signal = strat.evaluate_market(cfg, lookback, account_equity=Decimal("10000.00"))

    assert signal.direction == "NEUTRAL"
    assert signal.position_quantity == Decimal("0.00")
    assert signal.capital_at_risk_usd == Decimal("0.00")


def test_short_bracket_setup():
    """Verify short bracket order generation when forecast indicates strong bearish drift."""
    strat = MockForecastStrategy(
        terminal_close=77000.0, # -3.75% bearish drift
        path_high=80500.0,
        path_low=76500.0,
        min_hurdle_pct=Decimal("0.0050")
    )
    cfg = FuturesSymbolConfig(symbol="BTCUSDT", price_precision=2, quantity_precision=3, min_quantity=Decimal("0.001"))
    lookback = make_dummy_lookback(spot=80000.0)

    signal = strat.evaluate_market(cfg, lookback, account_equity=Decimal("10000.00"))

    assert signal.direction == "SHORT"
    assert signal.stop_loss > signal.entry_price
    assert signal.take_profit < signal.entry_price
    assert signal.risk_reward_ratio >= Decimal("1.50")
    # Verify risk budget: 1.5% of $10,000 = $150
    assert signal.capital_at_risk_usd <= Decimal("150.00")


def test_dollar_risk_budget_cap():
    """Verify capital at risk never exceeds max_risk_per_trade_pct allocation."""
    strat = MockForecastStrategy(
        terminal_close=85000.0,
        path_high=86000.0,
        path_low=79000.0,
        max_risk_per_trade_pct=Decimal("0.010") # 1% risk on $5,000 = $50
    )
    cfg = FuturesSymbolConfig(symbol="BTCUSDT", price_precision=2, quantity_precision=3, min_quantity=Decimal("0.001"))
    lookback = make_dummy_lookback(spot=80000.0)

    signal = strat.evaluate_market(cfg, lookback, account_equity=Decimal("5000.00"))

    assert signal.direction == "LONG"
    assert signal.capital_at_risk_usd <= Decimal("50.00")
    assert signal.capital_at_risk_usd > Decimal("0.00")
