"""
tests/test_pepe_asset_scaling.py — Verification of Asset-Aware Chart & Volatility Scaling (PEPE vs BTC).

Validates:
1. PEPE extreme sub-penny decimal precision (7 decimals for 1000PEPEUSDT, 8 decimals for PEPEUSDT).
2. Dynamic ATR Volatility Scaling: high-beta meme coin Stop-Loss envelopes expand
   according to true volatility (e.g. 7-10% stop on PEPE vs 1.0% stop on BTC).
3. Zero Float Financial Math (Decimal quantization).
"""

import os
import sys
from decimal import Decimal
import pandas as pd
import pytest

WORKSPACE_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if WORKSPACE_ROOT not in sys.path:
    sys.path.insert(0, WORKSPACE_ROOT)

from src.quant.config import ALL_SUPPORTED_SYMBOLS
from src.quant.kronos_onnx_engine import KronosTrajectoryEngine, TrajectoryVerdict


def test_pepe_precision_and_quantization():
    """Verify PEPE high-precision decimal quantization."""
    pepe_1000 = ALL_SUPPORTED_SYMBOLS["1000PEPEUSDT"]
    assert pepe_1000.price_precision == 7
    assert pepe_1000.quantity_precision == 0
    assert pepe_1000.min_quantity == Decimal("1")

    raw_price = Decimal("0.009456789")
    quantized_price = pepe_1000.quantize_price(raw_price)
    assert quantized_price == Decimal("0.0094568")

    pepe_spot = ALL_SUPPORTED_SYMBOLS["PEPEUSDT"]
    assert pepe_spot.price_precision == 8
    raw_spot_price = Decimal("0.0000094567")
    assert pepe_spot.quantize_price(raw_spot_price) == Decimal("0.00000946")


def test_pepe_vs_btc_volatility_stop_scaling():
    """
    Demonstrate that PEPE's dynamic Stop-Loss envelope expands to accommodate
    meme-coin ATR volatility rather than choking on BTC's narrow 1% stop.
    """
    engine = KronosTrajectoryEngine()

    # 1. Build BTC lookback with narrow 0.5% volatility
    btc_price = 67000.0
    n = 100
    btc_df = pd.DataFrame({
        "open": [btc_price] * n,
        "high": [btc_price + 200.0] * n,
        "low": [btc_price - 200.0] * n,
        "close": [btc_price] * n,
        "volume": [10.0] * n
    })
    btc_mock_pred = pd.DataFrame({
        "open": [btc_price + i * 50 for i in range(1, 13)],
        "high": [btc_price + i * 50 + 100 for i in range(1, 13)],
        "low": [btc_price + i * 50 - 100 for i in range(1, 13)],
        "close": [btc_price + i * 50 for i in range(1, 13)],
        "volume": [10.0] * 12
    })
    btc_verdict = engine.generate_trajectory("BTCUSDT", btc_df, mock_forecast=btc_mock_pred)
    btc_stop_pct = abs(btc_verdict.current_price - btc_verdict.dynamic_stop_loss) / btc_verdict.current_price

    # BTC stop should be approximately 1.0% (safety floor since 1.5 * 400 ATR = $600 = ~0.9%)
    assert btc_stop_pct == Decimal("0.010")  # Exactly 1.0% floor

    # 2. Build 1000PEPE lookback with wide 6.0% meme-coin volatility
    pepe_price = 0.0100000
    pepe_df = pd.DataFrame({
        "open": [pepe_price] * n,
        "high": [pepe_price + 0.0006000] * n,   # +6% swings
        "low": [pepe_price - 0.0006000] * n,    # -6% swings
        "close": [pepe_price] * n,
        "volume": [1000000.0] * n
    })
    pepe_mock_pred = pd.DataFrame({
        "open": [pepe_price + i * 0.0002000 for i in range(1, 13)],
        "high": [pepe_price + i * 0.0002000 + 0.0006000 for i in range(1, 13)],
        "low": [pepe_price + i * 0.0002000 - 0.0006000 for i in range(1, 13)],
        "close": [pepe_price + i * 0.0002000 for i in range(1, 13)],
        "volume": [1000000.0] * 12
    })
    pepe_verdict = engine.generate_trajectory("1000PEPEUSDT", pepe_df, mock_forecast=pepe_mock_pred)
    pepe_stop_pct = abs(pepe_verdict.current_price - pepe_verdict.dynamic_stop_loss) / pepe_verdict.current_price

    # PEPE stop distance is scaled by ATR: 1.5 * 0.0012000 = 0.0018000 = 18.0%!
    assert pepe_stop_pct > Decimal("0.05")  # Must be > 5.0%, accommodating meme volatility
    assert pepe_stop_pct > btc_stop_pct     # PEPE stop percentage is much wider than BTC!
