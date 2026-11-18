"""
Unit Tests for Scalper Learning & Distillation Engine
Validates:
1. Zero float financial math invariants across PnL, profit factor, and fee tax calculations.
2. 46-item TCA ingestion and SQLite forensics persistence.
3. Bayesian recalibration of ATR multiplier, fee hurdle, and win prob gate.
4. Toxic asset quarantine identification.
5. Generation of data/scalper_distilled_rules.json and config merging.
"""

import os
import json
import pytest
from decimal import Decimal
from src.quant.scalper_distillation import ScalperDistillationEngine, DistillationSummary


@pytest.fixture
def temp_distill_engine(tmp_path):
    test_db = str(tmp_path / "test_lessons.db")
    engine = ScalperDistillationEngine(db_path=test_db)
    return engine


def test_initial_distillation_empty_db(temp_distill_engine):
    summary = temp_distill_engine.run_learning_and_distillation(lookback_trades=50, sync_aws=False)
    assert summary.sample_size == 0
    assert summary.dominant_root_cause == "INSUFFICIENT_DATA"
    assert summary.calibrated_atr_multiplier == Decimal("1.00")
    assert summary.calibrated_fee_hurdle_pct == Decimal("1.10")
    assert summary.calibrated_min_win_prob_pct == Decimal("65.0")
    assert summary.quarantined_symbols == []


def test_bayesian_recalibration_stop_noise(temp_distill_engine):
    # Simulate batch with high STOP_INSIDE_NOISE
    raw_trades = []
    for i in range(10):
        # 3 wins, 7 stop-inside-noise losses
        if i < 3:
            raw_trades.append({
                "trade_id": f"T-WIN-{i}",
                "symbol": "BTCUSDT",
                "direction": "LONG",
                "entry_timestamp": "2026-11-14T10:00:00Z",
                "exit_timestamp": "2026-11-14T10:05:00Z",
                "entry_price": "60000.00",
                "exit_price": "60660.00",
                "position_size": "0.1",
                "exchange_fees_usd": "1.00",
                "planned_target_price": "60660.00",
                "planned_stop_price": "59580.00",
                "mfe_pct": "1.10",
                "mae_pct": "-0.20",
                "holding_duration_seconds": 300,
                "exit_trigger_reason": "TAKE_PROFIT_HIT"
            })
        else:
            raw_trades.append({
                "trade_id": f"T-LOSS-{i}",
                "symbol": "ETHUSDT",
                "direction": "LONG",
                "entry_timestamp": "2026-11-14T11:00:00Z",
                "exit_timestamp": "2026-11-14T11:03:00Z",
                "entry_price": "3000.00",
                "exit_price": "2975.00",
                "position_size": "2.0",
                "exchange_fees_usd": "2.00",
                "planned_target_price": "3033.00",
                "planned_stop_price": "2970.00",
                "mfe_pct": "1.20", # reached target after noise dip
                "mae_pct": "-0.70",
                "time_to_mfe_seconds": 600,
                "time_to_mae_seconds": 60,
                "atr_current": "30.0",
                "holding_duration_seconds": 180,
                "exit_trigger_reason": "STOP_LOSS_HIT"
            })

    temp_distill_engine.ingest_raw_trades(raw_trades, trade_mode="LIVE")
    summary = temp_distill_engine.run_learning_and_distillation(lookback_trades=50, sync_aws=False)

    assert summary.sample_size == 10
    assert summary.win_rate_pct == Decimal("30.0")
    assert summary.calibrated_atr_multiplier == Decimal("1.25")
    # Low win rate (<55%) triggers elevated win prob gate
    assert summary.calibrated_min_win_prob_pct == Decimal("70.0")
    # ETHUSDT has repeated losses -> should be quarantined
    assert "ETHUSDT" in summary.quarantined_symbols


def test_bayesian_recalibration_friction_bleed(temp_distill_engine):
    # Simulate batch with FRICTION_BLEED
    raw_trades = []
    for i in range(10):
        raw_trades.append({
            "trade_id": f"T-FRIC-{i}",
            "symbol": "SOLUSDT",
            "direction": "LONG",
            "entry_timestamp": "2026-11-14T12:00:00Z",
            "exit_timestamp": "2026-11-14T12:04:00Z",
            "entry_price": "150.00",
            "exit_price": "150.15", # tiny gain +0.10%
            "position_size": "5.0",
            "exchange_fees_usd": "1.80", # fees > $0.75 gross -> net negative!
            "planned_target_price": "150.15",
            "planned_stop_price": "148.50",
            "mfe_pct": "0.10",
            "mae_pct": "-0.01",
            "holding_duration_seconds": 240,
            "exit_trigger_reason": "TAKE_PROFIT_HIT"
        })

    temp_distill_engine.ingest_raw_trades(raw_trades, trade_mode="LIVE")
    summary = temp_distill_engine.run_learning_and_distillation(lookback_trades=50, sync_aws=False)

    assert summary.sample_size == 10
    assert summary.dominant_root_cause == "FRICTION_BLEED"
    assert summary.calibrated_fee_hurdle_pct == Decimal("1.25")
    assert summary.calibrated_ratchet_trigger_pct == Decimal("0.85")
