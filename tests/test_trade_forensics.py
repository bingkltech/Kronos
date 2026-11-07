"""
Unit Tests for Trade Forensics Engine
Verifies 46-item telemetry and deterministic root-cause diagnosis.
"""

from decimal import Decimal
import pytest
from src.quant.trade_forensics import TradeForensicsEngine


def test_clean_conviction_win():
    raw_trade = {
        "trade_id": "T-01",
        "symbol": "BTC/USDT",
        "direction": "LONG",
        "entry_timestamp": "2026-11-07T12:00:00Z",
        "exit_timestamp": "2026-11-07T12:30:00Z",
        "entry_price": "60000.00",
        "exit_price": "61200.00",
        "position_size": "0.1",
        "exchange_fees_usd": "2.00",
        "planned_target_price": "61200.00",
        "planned_stop_price": "59500.00",
        "mfe_pct": "2.0",
        "mae_pct": "-0.3",
        "rsi_14": "55.0",
        "atr_current": "200.0",
        "atr_ratio": "1.0"
    }
    record = TradeForensicsEngine.assess_trade(raw_trade, trade_mode="LIVE")
    assert record.directional_accuracy is True
    assert record.root_cause_diagnosis == "CONVICTION_WIN"
    assert record.alpha_learning_weight == Decimal("1.0")
    assert record.friction_learning_weight == Decimal("1.0")


def test_stop_inside_noise():
    raw_trade = {
        "trade_id": "T-02",
        "symbol": "ETH/USDT",
        "direction": "LONG",
        "entry_timestamp": "2026-11-07T13:00:00Z",
        "exit_timestamp": "2026-11-07T13:15:00Z",
        "entry_price": "3000.00",
        "exit_price": "2975.00",
        "position_size": "2.0",
        "exchange_fees_usd": "3.00",
        "planned_target_price": "3060.00",
        "planned_stop_price": "2975.00",
        "mfe_pct": "2.2",   # Target was reached after initial dip
        "mae_pct": "-0.83", # Dipped by 0.83%
        "time_to_mfe_seconds": 900,
        "time_to_mae_seconds": 120,
        "rsi_14": "50.0",
        "atr_current": "30.0", # 30 / 3000 = 1.0% ATR
        "atr_ratio": "1.0"
    }
    record = TradeForensicsEngine.assess_trade(raw_trade, trade_mode="PAPER")
    assert record.directional_accuracy is True
    assert record.root_cause_diagnosis == "STOP_INSIDE_NOISE"
    # Paper mode weights
    assert record.alpha_learning_weight == Decimal("0.50")
    assert record.friction_learning_weight == Decimal("0.00")


def test_friction_bleed():
    raw_trade = {
        "trade_id": "T-03",
        "symbol": "SOL/USDT",
        "direction": "LONG",
        "entry_timestamp": "2026-11-07T14:00:00Z",
        "exit_timestamp": "2026-11-07T14:05:00Z",
        "entry_price": "150.00",
        "exit_price": "150.15", # +0.10% gross
        "position_size": "10.0",
        "exchange_fees_usd": "2.50", # fees exceed gross profit ($1.50)
        "planned_target_price": "150.15",
        "planned_stop_price": "149.00",
        "mfe_pct": "0.10",
        "mae_pct": "-0.02",
        "rsi_14": "52.0",
        "atr_current": "0.5",
        "atr_ratio": "1.0"
    }
    record = TradeForensicsEngine.assess_trade(raw_trade, trade_mode="LIVE")
    assert record.directional_accuracy is True
    assert record.net_pnl_usd < Decimal("0")
    assert record.root_cause_diagnosis == "FRICTION_BLEED"
