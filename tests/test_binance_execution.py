"""
tests/test_binance_execution.py — ASVL Verification Suite for src/quant/binance_execution.py.

Validates:
1. Atomic bracket state machine progression (IDLE -> ENTRY_FILLED -> BRACKETS_ACTIVE).
2. Anti-Naked-Position Guard: Emergency flatten on Stop-Loss confirmation failure.
3. 12-Hour Temporal Stale-Trade Expiry execution.
4. Invariant 1: Zero Float Financial Math (realized PnL strictly decimal.Decimal).
"""

import os
import sys
import datetime
from decimal import Decimal
import pytest

WORKSPACE_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if WORKSPACE_ROOT not in sys.path:
    sys.path.insert(0, WORKSPACE_ROOT)

from src.quant.binance_execution import (
    BinanceAtomicExecutor,
    ActiveBracketPosition,
    PositionState
)
from src.quant.kev_risk_arbiter import TradeTicket


def _make_sample_ticket(symbol="ETHUSDT", side="BUY") -> TradeTicket:
    """Helper creating a sample pre-cleared TradeTicket."""
    return TradeTicket(
        symbol=symbol,
        side=side,
        entry_price=Decimal("2500.00"),
        stop_loss=Decimal("2465.00"),
        take_profit=Decimal("2560.00"),
        quantity=Decimal("4.000"),
        notional_usd=Decimal("10000.00"),
        effective_leverage=1,
        risk_budget_usd=Decimal("140.00"),
        reward_risk_ratio=Decimal("1.71"),
        net_expected_gain_pct=Decimal("2.24")
    )


def test_atomic_bracket_order_lifecycle():
    """Verify normal dry-run bracket dispatch and state transitions."""
    executor = BinanceAtomicExecutor(dry_run=True)
    ticket = _make_sample_ticket()

    pos = executor.submit_bracket_order(ticket)

    assert pos.state == PositionState.BRACKETS_ACTIVE
    assert pos.symbol == "ETHUSDT"
    assert pos.side == "BUY"
    assert pos.entry_price == Decimal("2500.00")
    assert pos.stop_loss == Decimal("2465.00")
    assert pos.take_profit == Decimal("2560.00")
    assert pos.quantity == Decimal("4.000")
    assert pos.entry_order_id is not None
    assert pos.sl_order_id is not None
    assert pos.tp_order_id is not None
    assert pos.position_id in executor.active_positions


def test_anti_naked_position_guard():
    """Verify emergency flatten when Stop-Loss fails confirmation."""
    executor = BinanceAtomicExecutor(dry_run=True)
    ticket = _make_sample_ticket()

    pos = executor.submit_bracket_order(ticket, mock_simulate_sl_failure=True)

    assert pos.state == PositionState.EMERGENCY_FLATTEN
    assert pos.close_reason == "EMERGENCY_FLATTEN_SL_TIMEOUT"
    assert pos.close_time_utc is not None


def test_12h_temporal_exit():
    """Verify position expiry when trade remains open for 12 hours."""
    executor = BinanceAtomicExecutor(dry_run=True)
    ticket = _make_sample_ticket()
    pos = executor.submit_bracket_order(ticket)

    entry_time = pos.entry_fill_time_utc
    assert entry_time is not None

    # Case 1: 5 hours elapsed -> Not expired
    t_5h = entry_time + datetime.timedelta(hours=5)
    expired_5h = executor.evaluate_temporal_exit(pos, current_time_utc=t_5h, max_duration_hours=12)
    assert not expired_5h
    assert pos.state == PositionState.BRACKETS_ACTIVE

    # Case 2: 12.5 hours elapsed -> Trigger temporal exit
    t_12h = entry_time + datetime.timedelta(hours=12, minutes=30)
    expired_12h = executor.evaluate_temporal_exit(pos, current_time_utc=t_12h, max_duration_hours=12)
    assert expired_12h
    assert pos.state == PositionState.CLOSED
    assert pos.close_reason == "TEMPORAL_EXIT_12H_STALE"


def test_realized_pnl_calculation():
    """Verify realized PnL precision for Long and Short trades."""
    executor = BinanceAtomicExecutor(dry_run=True)
    ticket = _make_sample_ticket(side="BUY")
    pos = executor.submit_bracket_order(ticket)

    # Close at Take-Profit 2560 (Profit: (2560 - 2500) * 4.0 = $240.00)
    closed_pos = executor.close_position_manual(pos.position_id, reason="TP_HIT", exit_price=Decimal("2560.00"))
    assert closed_pos.realized_pnl_usd == Decimal("240.00")
    assert isinstance(closed_pos.realized_pnl_usd, Decimal)
