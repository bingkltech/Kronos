"""
Empirical Verification Suite: Kronos Tsunami Storm Adaptive Protocol
Verifies:
1. Calm Waters: Standard capacity (3 Macro / 1 Scalp).
2. High-Wave Detection: BTC violent 5m velocity shock triggers Storm Mode.
3. Unforeseen News Shock: High-impact economic news triggers Storm Mode.
4. Phase 1 (Shock Pause): Strict veto on all new entries during initial 15 minutes.
5. Phase 2 (Focused Caution): Clamps strictly to 1 Macro + 1 Scalp with >=75% confidence hurdle.
6. Phase 3 (Calm Water Auto-Recovery): Reverts automatically after 60 minutes.
"""

import os
import pytest
import datetime
from decimal import Decimal
from src.quant.storm_protocol import StormProtocolManager, StormPhase


@pytest.fixture
def temp_storm_manager(tmp_path):
    test_state_file = str(tmp_path / "test_storm_state.json")
    mgr = StormProtocolManager(state_file=test_state_file)
    return mgr


def test_normal_waters_capacity(temp_storm_manager):
    status = temp_storm_manager.get_status()
    assert not status.is_storm_active
    assert status.phase == StormPhase.NORMAL_WATERS
    assert status.max_macro_positions == 2
    assert status.max_scalp_positions == 1

    # Macro trade 1 permitted
    ok, _ = temp_storm_manager.is_entry_permitted(is_scalp=False, current_macro_count=0, current_scalp_count=0, confidence_pct=65.0)
    assert ok is True

    # Macro trade 2 permitted
    ok, _ = temp_storm_manager.is_entry_permitted(is_scalp=False, current_macro_count=1, current_scalp_count=0, confidence_pct=65.0)
    assert ok is True

    # Macro trade 3 rejected (cap 2)
    ok, _ = temp_storm_manager.is_entry_permitted(is_scalp=False, current_macro_count=2, current_scalp_count=0, confidence_pct=65.0)
    assert ok is False


def test_high_wave_velocity_trigger(temp_storm_manager):
    # Simulate sudden violent BTC 5-minute dump of -2.5%
    btc_klines = [
        {"open": "90000.0", "high": "90200.0", "low": "89800.0", "close": "90100.0"},
        {"open": "90100.0", "high": "90150.0", "low": "87500.0", "close": "87800.0"} # -2.55% drop, 2.94% range
    ]

    t0 = datetime.datetime(2026, 11, 14, 12, 0, 0, tzinfo=datetime.timezone.utc)
    triggered, status = temp_storm_manager.evaluate_market_wave(
        btc_klines=btc_klines,
        current_time_utc=t0
    )

    assert triggered is True
    assert status.is_storm_active is True
    assert status.phase == StormPhase.PHASE_1_SHOCK_PAUSE
    assert "Violent BTC Volatility Spike" in status.reason
    assert status.max_macro_positions == 1
    assert status.max_scalp_positions == 1


def test_unforeseen_news_catalyst_trigger(temp_storm_manager):
    t0 = datetime.datetime(2026, 11, 14, 14, 0, 0, tzinfo=datetime.timezone.utc)
    triggered, status = temp_storm_manager.evaluate_market_wave(
        is_news_blackout=True,
        news_event_name="FOMC Emergency Rate Hike Announcement",
        current_time_utc=t0
    )

    assert triggered is True
    assert status.is_storm_active is True
    assert "FOMC" in status.reason


def test_storm_lifecycle_and_auto_recovery(temp_storm_manager):
    t0 = datetime.datetime(2026, 11, 14, 15, 0, 0, tzinfo=datetime.timezone.utc)
    
    # 1. Trigger Storm
    temp_storm_manager.trigger_storm(
        reason="Tsunami News Shock",
        duration_minutes=60,
        pause_minutes=15,
        current_time_utc=t0
    )

    # 2. Phase 1 (First 15 Minutes): Shock Pause (Strict VETO on all new entries)
    t_5m = t0 + datetime.timedelta(minutes=5)
    status_5m = temp_storm_manager.get_status(current_time_utc=t_5m)
    assert status_5m.phase == StormPhase.PHASE_1_SHOCK_PAUSE
    assert status_5m.pause_seconds_remaining == 600 # 10m left

    # Attempt to open Macro or Scalp during Shock Pause -> MUST BE VETOED
    ok, reason = temp_storm_manager.is_entry_permitted(is_scalp=False, current_macro_count=0, current_scalp_count=0, confidence_pct=90.0, current_time_utc=t_5m)
    assert ok is False
    assert "Phase 1" in reason

    ok, reason = temp_storm_manager.is_entry_permitted(is_scalp=True, current_macro_count=0, current_scalp_count=0, confidence_pct=90.0, current_time_utc=t_5m)
    assert ok is False
    assert "Phase 1" in reason

    # 3. Phase 2 (Minutes 15-60): Focused Caution
    t_20m = t0 + datetime.timedelta(minutes=20)
    status_20m = temp_storm_manager.get_status(current_time_utc=t_20m)
    assert status_20m.phase == StormPhase.PHASE_2_FOCUSED_CAUTION
    assert status_20m.pause_seconds_remaining == 0
    assert status_20m.seconds_remaining == 2400 # 40m left

    # Attempt low-confidence entry (68%) -> MUST BE VETOED (requires >=75% in storm)
    ok, reason = temp_storm_manager.is_entry_permitted(is_scalp=False, current_macro_count=0, current_scalp_count=0, confidence_pct=68.0, current_time_utc=t_20m)
    assert ok is False
    assert "≥75.0% confidence" in reason

    # High-confidence Macro entry (78%) -> PERMITTED for slot 1
    ok, reason = temp_storm_manager.is_entry_permitted(is_scalp=False, current_macro_count=0, current_scalp_count=0, confidence_pct=78.0, current_time_utc=t_20m)
    assert ok is True
    assert "1 Macro" in reason

    # Attempt 2nd Macro entry -> MUST BE VETOED (strictly clamped to 1 Macro!)
    ok, reason = temp_storm_manager.is_entry_permitted(is_scalp=False, current_macro_count=1, current_scalp_count=0, confidence_pct=85.0, current_time_utc=t_20m)
    assert ok is False
    assert "clamps Macro to strictly 1 position" in reason

    # High-confidence Scalp entry (82%) -> PERMITTED for slot 1
    ok, reason = temp_storm_manager.is_entry_permitted(is_scalp=True, current_macro_count=1, current_scalp_count=0, confidence_pct=82.0, current_time_utc=t_20m)
    assert ok is True
    assert "1 Scalp" in reason

    # Attempt 2nd Scalp entry -> MUST BE VETOED (strictly clamped to 1 Scalp!)
    ok, reason = temp_storm_manager.is_entry_permitted(is_scalp=True, current_macro_count=1, current_scalp_count=1, confidence_pct=90.0, current_time_utc=t_20m)
    assert ok is False
    assert "clamps Scalp to strictly 1 position" in reason

    # 4. Phase 3 (Minute 61): Calm Water Auto-Recovery
    t_61m = t0 + datetime.timedelta(minutes=61)
    status_61m = temp_storm_manager.get_status(current_time_utc=t_61m)
    assert status_61m.is_storm_active is False
    assert status_61m.phase == StormPhase.NORMAL_WATERS
    assert status_61m.max_macro_positions == 2
    assert status_61m.max_scalp_positions == 1

    # Standard confidence entry (65%) -> PERMITTED again now that ocean is calm
    ok, reason = temp_storm_manager.is_entry_permitted(is_scalp=False, current_macro_count=1, current_scalp_count=0, confidence_pct=65.0, current_time_utc=t_61m)
    assert ok is True
    assert "Normal Waters" in reason


def test_consecutive_stopouts_threshold_five(temp_storm_manager):
    t0 = datetime.datetime(2026, 11, 14, 16, 0, 0, tzinfo=datetime.timezone.utc)
    
    # 4 stopouts -> should NOT trigger storm
    triggered, _ = temp_storm_manager.evaluate_market_wave(
        recent_stopouts=4,
        current_time_utc=t0
    )
    assert triggered is False

    # 5 stopouts -> MUST trigger storm (Phase 1 Shock Pause)
    triggered, status = temp_storm_manager.evaluate_market_wave(
        recent_stopouts=5,
        current_time_utc=t0
    )
    assert triggered is True
    assert status.is_storm_active is True
    assert status.phase == StormPhase.PHASE_1_SHOCK_PAUSE
    assert "5 Consecutive Stop-Outs Triggered" in status.high_wave_metric
