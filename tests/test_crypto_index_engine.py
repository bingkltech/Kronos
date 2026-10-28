"""
tests/test_crypto_index_engine.py — ASVL Verification Suite for src/quant/crypto_index_engine.py.

Validates:
1. Exact 24h Volume-Weighted Average Price (VWAP) calculation in Decimal.
2. Market Breadth determination across BULL_EXPANSION, BEAR_DISTRIBUTION, and CHOP.
3. Invariant 1: Zero Float Financial Math (all stats are decimal.Decimal).
4. Live Binance Futures 24h kline endpoint parsing.
"""

import os
import sys
from decimal import Decimal
import pytest

WORKSPACE_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if WORKSPACE_ROOT not in sys.path:
    sys.path.insert(0, WORKSPACE_ROOT)

from src.quant.crypto_index_engine import CryptoIndexEngine, MacroIndexVerdict, SymbolMacroStats
from src.quant.config import TOP_10_SYMBOLS


def test_symbol_vwap_and_stats_calculation():
    """Verify VWAP mathematical calculation with known synthetic candles."""
    engine = CryptoIndexEngine()

    # 3 synthetic candles
    # Typical price: (H + L + C) / 3
    # Candle 1: H=105, L=95, C=100 -> Typ=100, Vol=10 -> PV=1000
    # Candle 2: H=115, L=105, C=110 -> Typ=110, Vol=20 -> PV=2200
    # Candle 3: H=125, L=115, C=120 -> Typ=120, Vol=30 -> PV=3600
    # Total PV = 6800, Total Vol = 60 -> VWAP = 6800 / 60 = 113.33
    klines = [
        {"open": Decimal("98"), "high": Decimal("105"), "low": Decimal("95"), "close": Decimal("100"), "volume": Decimal("10"), "quote_volume": Decimal("1000")},
        {"open": Decimal("101"), "high": Decimal("115"), "low": Decimal("105"), "close": Decimal("110"), "volume": Decimal("20"), "quote_volume": Decimal("2200")},
        {"open": Decimal("111"), "high": Decimal("125"), "low": Decimal("115"), "close": Decimal("120"), "volume": Decimal("30"), "quote_volume": Decimal("3600")},
    ]

    stats = engine.compute_symbol_stats("BTCUSDT", klines)

    assert isinstance(stats.vwap_24h, Decimal)
    assert isinstance(stats.current_price, Decimal)
    assert stats.current_price == Decimal("120")
    assert stats.vwap_24h == Decimal("113.33")
    assert stats.above_vwap is True
    # Price change: (120 - 98) / 98 * 100 = 22.45%
    assert stats.price_change_24h_pct == Decimal("22.45")


def test_market_breadth_regimes():
    """Verify market breadth regime assignment."""
    engine = CryptoIndexEngine()

    # Build dummy klines for the 10 symbols
    # Case 1: 8 coins above VWAP (80%) -> BULL_EXPANSION
    bull_klines = {}
    symbols = list(TOP_10_SYMBOLS.keys())
    for i, sym in enumerate(symbols):
        if i < 8:
            # Bullish candle: close is high
            bull_klines[sym] = [
                {"open": Decimal("100"), "high": Decimal("110"), "low": Decimal("99"), "close": Decimal("108"), "volume": Decimal("10"), "quote_volume": Decimal("1000")}
            ]
        else:
            # Bearish candle: close is low
            bull_klines[sym] = [
                {"open": Decimal("100"), "high": Decimal("102"), "low": Decimal("90"), "close": Decimal("91"), "volume": Decimal("10"), "quote_volume": Decimal("1000")}
            ]

    verdict_bull = engine.evaluate_universe(preloaded_klines=bull_klines)
    assert verdict_bull.macro_regime == "BULL_EXPANSION"
    assert verdict_bull.coins_above_vwap_count == 8
    assert verdict_bull.breadth_ratio == Decimal("0.8")

    # Case 2: Only 2 coins above VWAP (20%) -> BEAR_DISTRIBUTION
    bear_klines = {}
    for i, sym in enumerate(symbols):
        if i < 2:
            bear_klines[sym] = bull_klines[sym]
        else:
            bear_klines[sym] = [
                {"open": Decimal("100"), "high": Decimal("102"), "low": Decimal("90"), "close": Decimal("91"), "volume": Decimal("10"), "quote_volume": Decimal("1000")}
            ]

    verdict_bear = engine.evaluate_universe(preloaded_klines=bear_klines)
    assert verdict_bear.macro_regime == "BEAR_DISTRIBUTION"
    assert verdict_bear.coins_above_vwap_count == 2
    assert verdict_bear.breadth_ratio == Decimal("0.2")

    # Case 3: 5 coins above VWAP (50%) -> CHOP
    chop_klines = {}
    for i, sym in enumerate(symbols):
        if i < 5:
            chop_klines[sym] = bull_klines[sym]
        else:
            chop_klines[sym] = [
                {"open": Decimal("100"), "high": Decimal("102"), "low": Decimal("90"), "close": Decimal("91"), "volume": Decimal("10"), "quote_volume": Decimal("1000")}
            ]

    verdict_chop = engine.evaluate_universe(preloaded_klines=chop_klines)
    assert verdict_chop.macro_regime == "CHOP"
    assert verdict_chop.coins_above_vwap_count == 5
    assert verdict_chop.breadth_ratio == Decimal("0.5")


def test_live_binance_klines_fetch():
    """Verify live public Binance 24h kline parsing for BTCUSDT."""
    engine = CryptoIndexEngine()
    try:
        klines = engine.fetch_24h_klines("BTCUSDT")
    except Exception as e:
        pytest.skip(f"Network unavailable for live Binance API: {e}")

    assert len(klines) == 24
    sample = klines[-1]
    assert isinstance(sample["close"], Decimal)
    assert isinstance(sample["volume"], Decimal)
    assert sample["close"] > Decimal("0")
    assert sample["high"] >= sample["low"]

    stats = engine.compute_symbol_stats("BTCUSDT", klines)
    assert isinstance(stats.vwap_24h, Decimal)
    assert stats.vwap_24h > Decimal("0")
