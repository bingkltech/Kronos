"""
tests/test_macro_specialists.py — ASVL Verification Suite for src/quant/macro_specialists.py.

Validates:
1. NewsCatalystSpecialist blackout detection (+/- 30 min window around FOMC/CPI).
2. CryptoCarrySpecialist cost-of-carry evaluation for Long and Short sides.
3. Live Binance Futures API funding rate fetch and Zero Float Decimal conversion.
"""

import os
import sys
import datetime
from decimal import Decimal
import pytest

WORKSPACE_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if WORKSPACE_ROOT not in sys.path:
    sys.path.insert(0, WORKSPACE_ROOT)

from src.quant.macro_specialists import (
    NewsCatalystSpecialist,
    NewsBlackoutVerdict,
    CryptoCarrySpecialist,
    CarryVerdict,
)


def test_news_catalyst_blackout_detection():
    """Verify high-impact news blackout window behavior."""
    specialist = NewsCatalystSpecialist(blackout_window_minutes=30)
    
    # Register an FOMC rate decision at 18:00 UTC
    base_time = datetime.datetime(2026, 10, 28, 18, 0, tzinfo=datetime.timezone.utc)
    specialist.register_event(base_time, "FOMC Rate Decision")

    # 1. Check 2 hours before: Clear
    t_clear_before = base_time - datetime.timedelta(hours=2)
    verdict = specialist.evaluate_blackout(t_clear_before)
    assert not verdict.is_blackout
    assert verdict.event_name == ""

    # 2. Check 15 minutes before: Blackout Active
    t_blackout_before = base_time - datetime.timedelta(minutes=15)
    verdict = specialist.evaluate_blackout(t_blackout_before)
    assert verdict.is_blackout
    assert "FOMC Rate Decision" in verdict.event_name
    assert verdict.minutes_to_event == 15

    # 3. Check exact time: Blackout Active
    verdict = specialist.evaluate_blackout(base_time)
    assert verdict.is_blackout
    assert verdict.minutes_to_event == 0

    # 4. Check 20 minutes after: Blackout Active (market digesting release)
    t_blackout_after = base_time + datetime.timedelta(minutes=20)
    verdict = specialist.evaluate_blackout(t_blackout_after)
    assert verdict.is_blackout
    assert verdict.minutes_to_event == -20

    # 5. Check 45 minutes after: Clear
    t_clear_after = base_time + datetime.timedelta(minutes=45)
    verdict = specialist.evaluate_blackout(t_clear_after)
    assert not verdict.is_blackout


def test_crypto_carry_verdict_logic():
    """Verify Long and Short funding rate evaluations."""
    carry = CryptoCarrySpecialist()

    # LONG Tests
    # Case A: Hyper-positive funding rate (+0.04% per 8h > 0.03% ceiling) -> PROHIBITIVE
    v_long_prohib = carry.evaluate_carry("ETHUSDT", "LONG", Decimal("0.0004"))
    assert v_long_prohib.verdict == "PROHIBITIVE"
    assert "Veto Long" in v_long_prohib.reason
    assert isinstance(v_long_prohib.annualized_rate, Decimal)

    # Case B: Negative funding rate (-0.02% per 8h) -> FAVORABLE (shorts pay longs)
    v_long_fav = carry.evaluate_carry("ETHUSDT", "LONG", Decimal("-0.0002"))
    assert v_long_fav.verdict == "FAVORABLE"
    assert "receive carry yield" in v_long_fav.reason

    # Case C: Mild normal funding (+0.01% per 8h) -> NEUTRAL
    v_long_neu = carry.evaluate_carry("ETHUSDT", "LONG", Decimal("0.0001"))
    assert v_long_neu.verdict == "NEUTRAL"

    # SHORT Tests
    # Case D: Deep negative funding (-0.04% per 8h) -> PROHIBITIVE (shorts pay excessive fees)
    v_short_prohib = carry.evaluate_carry("ETHUSDT", "SHORT", Decimal("-0.0004"))
    assert v_short_prohib.verdict == "PROHIBITIVE"
    assert "Veto Short" in v_short_prohib.reason

    # Case E: High positive funding (+0.02% per 8h) -> FAVORABLE (longs pay shorts)
    v_short_fav = carry.evaluate_carry("ETHUSDT", "SHORT", Decimal("0.0002"))
    assert v_short_fav.verdict == "FAVORABLE"
    assert "receive carry yield" in v_short_fav.reason


def test_live_binance_funding_fetch():
    """Verify live public Binance endpoint fetching with Decimal conversion."""
    carry = CryptoCarrySpecialist()
    try:
        data = carry.fetch_funding_rates(symbol="BTCUSDT")
    except Exception as e:
        pytest.skip(f"Network unavailable for live Binance API: {e}")

    assert "BTCUSDT" in data
    btc_info = data["BTCUSDT"]
    funding_rate = btc_info["funding_rate"]
    next_time = btc_info["next_funding_time"]

    # Verify Invariant 1: Zero Float Financial Math
    assert isinstance(funding_rate, Decimal)
    assert not isinstance(funding_rate, float)
    assert isinstance(next_time, datetime.datetime)

    # Evaluate carry on live rate
    verdict = carry.evaluate_carry("BTCUSDT", "LONG", funding_rate, next_time)
    assert verdict.verdict in ["FAVORABLE", "NEUTRAL", "PROHIBITIVE"]
