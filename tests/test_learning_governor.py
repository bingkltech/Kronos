"""
tests/test_learning_governor.py — ASVL Verification Suite for src/quant/learning_governor.py.

Validates:
1. Brier score mathematical calibration across diverse outcome distributions.
2. Dynamic Confidence Multiplier derivation (1.0x PRISTINE -> 0.0x HALTED circuit breaker).
3. SQLite database persistence and Zero Float Decimal conversion.
"""

import os
import sys
import tempfile
import datetime
from decimal import Decimal
import pytest

WORKSPACE_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if WORKSPACE_ROOT not in sys.path:
    sys.path.insert(0, WORKSPACE_ROOT)

from src.quant.learning_governor import LearningGovernor, TradeOutcome, CalibrationReport


def test_empty_history_defaults():
    """Verify that empty trading history defaults safely to 1.0x capital."""
    db_path = os.path.join(WORKSPACE_ROOT, "data", "_test_empty.db")
    if os.path.exists(db_path):
        os.remove(db_path)
    try:
        gov = LearningGovernor(db_path=db_path)
        report = gov.calculate_brier_calibration()
        assert report.total_evaluations == 0
        assert report.confidence_multiplier == Decimal("1.00")
        assert report.status == "PRISTINE"
    finally:
        if os.path.exists(db_path):
            os.remove(db_path)


def test_pristine_calibration():
    """Verify well-calibrated predictions produce 1.0x multiplier."""
    gov = LearningGovernor(db_path=":memory:")
    
    # 5 trades: confidence ~0.80 and all 5 hit TP (y=1)
    # Error: (0.8 - 1.0)^2 = 0.04 -> Brier Score = 0.04 <= 0.15
    outcomes = [
        TradeOutcome(
            trade_id=f"T{i}",
            symbol="ETHUSDT",
            side="LONG",
            forecast_confidence=Decimal("0.80"),
            realized_hit=1,
            realized_pnl_usd=Decimal("150.00"),
            exit_reason="TP_HIT",
            timestamp_utc=datetime.datetime.now(datetime.timezone.utc)
        )
        for i in range(5)
    ]

    report = gov.calculate_brier_calibration(outcomes=outcomes)
    assert report.brier_score == Decimal("0.0400")
    assert report.confidence_multiplier == Decimal("1.00")
    assert report.status == "PRISTINE"


def test_throttled_and_halted_circuit_breaker():
    """Verify that regime shifts and miscalibration trigger throttle and circuit breaker."""
    gov = LearningGovernor(db_path=":memory:")

    # Severe miscalibration: Model predicted 0.90 confidence, but all trades hit Stop-Loss (y=0)
    # Error: (0.9 - 0.0)^2 = 0.81 -> Brier Score = 0.8100 >> 0.3500
    failed_outcomes = [
        TradeOutcome(
            trade_id=f"F{i}",
            symbol="BTCUSDT",
            side="LONG",
            forecast_confidence=Decimal("0.90"),
            realized_hit=0,
            realized_pnl_usd=Decimal("-150.00"),
            exit_reason="SL_HIT",
            timestamp_utc=datetime.datetime.now(datetime.timezone.utc)
        )
        for i in range(5)
    ]

    halt_report = gov.calculate_brier_calibration(outcomes=failed_outcomes)
    assert halt_report.brier_score == Decimal("0.8100")
    assert halt_report.confidence_multiplier == Decimal("0.00")
    assert halt_report.status == "HALTED"
    assert "Trading halted" in halt_report.reason


def test_sqlite_persistence():
    """Verify storing trade outcomes and reading them back with Decimal precision."""
    db_path = os.path.join(WORKSPACE_ROOT, "data", "_test_persist.db")
    if os.path.exists(db_path):
        os.remove(db_path)
    try:
        gov = LearningGovernor(db_path=db_path)
        out = TradeOutcome(
            trade_id="ETH-20261028-001",
            symbol="ETHUSDT",
            side="LONG",
            forecast_confidence=Decimal("0.75"),
            realized_hit=1,
            realized_pnl_usd=Decimal("245.50"),
            exit_reason="TP_HIT",
            timestamp_utc=datetime.datetime.now(datetime.timezone.utc)
        )
        gov.record_outcome(out)

        loaded = gov._load_recent_outcomes(limit=10)
        assert len(loaded) == 1
        record = loaded[0]
        assert record.trade_id == "ETH-20261028-001"
        assert record.symbol == "ETHUSDT"
        assert record.forecast_confidence == Decimal("0.75")
        assert record.realized_pnl_usd == Decimal("245.50")
        assert record.realized_hit == 1
        assert record.exit_reason == "TP_HIT"
    finally:
        if os.path.exists(db_path):
            os.remove(db_path)
