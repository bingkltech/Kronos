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


def _make_sample_ticket(
    symbol="ETHUSDT",
    side="BUY",
    entry_price=Decimal("2500.00"),
    quantity=Decimal("4.000")
) -> TradeTicket:
    """Helper creating a sample pre-cleared TradeTicket."""
    return TradeTicket(
        symbol=symbol,
        side=side,
        entry_price=entry_price,
        stop_loss=Decimal("2465.00"),
        take_profit=Decimal("2560.00"),
        quantity=quantity,
        notional_usd=entry_price * quantity,
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


def test_paper_trading_state_and_win_loss_audit(tmp_path):
    """Verify paper trading $200 initial equity, win/loss tracking, and summary metrics."""
    state_file = str(tmp_path / "test_paper_state.json")
    executor = BinanceAtomicExecutor(dry_run=True, initial_equity=Decimal("200.00"), state_file=state_file)

    assert executor.paper_initial_equity == Decimal("200.00")
    assert executor.get_current_equity() == Decimal("200.00")

    # Trade 1: WIN (+ $10.00)
    t1 = _make_sample_ticket(side="BUY", entry_price=Decimal("100.00"), quantity=Decimal("1.000"))
    pos1 = executor.submit_bracket_order(t1)
    executor.close_position_manual(pos1.position_id, reason="TAKE_PROFIT_TRIGGERED", exit_price=Decimal("110.00"))

    # Trade 2: LOSS (- $4.00)
    t2 = _make_sample_ticket(side="BUY", entry_price=Decimal("100.00"), quantity=Decimal("1.000"))
    pos2 = executor.submit_bracket_order(t2)
    executor.close_position_manual(pos2.position_id, reason="STOP_LOSS_TRIGGERED", exit_price=Decimal("96.00"))

    # Check live equity: 200 + 10 - 4 = $206.00
    assert executor.get_current_equity() == Decimal("206.00")

    summary = executor.get_paper_summary()
    assert summary["initial_equity"] == 200.0
    assert summary["current_equity"] == 206.0
    assert summary["realized_pnl_usd"] == 6.0
    assert summary["total_trades"] == 2
    assert summary["winning_trades"] == 1
    assert summary["losing_trades"] == 1
    assert summary["win_loss_display"] == "1 Wins vs 1 Losses"
    assert summary["win_rate_pct"] == 50.0
    assert len(summary["closed_trades"]) == 2

    # Reset test
    reset_summary = executor.reset_paper_trading(initial_equity=Decimal("200.00"))
    assert reset_summary["current_equity"] == 200.0
    assert reset_summary["total_trades"] == 0
    assert executor.get_current_equity() == Decimal("200.00")


def test_active_positions_and_last_trade_persist_across_restarts(tmp_path):
    """Verify memory engine restores open bracket positions and last paper trade across restarts."""
    state_file = str(tmp_path / "persistent_paper_state.json")

    # Instance 1: Run and create state
    exec1 = BinanceAtomicExecutor(dry_run=True, initial_equity=Decimal("200.00"), state_file=state_file)

    # 1. Closed trade
    t_closed = _make_sample_ticket(symbol="ETHUSDT", side="BUY", entry_price=Decimal("2500.00"), quantity=Decimal("0.100"))
    pos_closed = exec1.submit_bracket_order(t_closed)
    exec1.close_position_manual(pos_closed.position_id, reason="TAKE_PROFIT_TRIGGERED", exit_price=Decimal("2560.00"))

    # 2. Open active position
    t_active = _make_sample_ticket(symbol="BTCUSDT", side="BUY", entry_price=Decimal("70000.00"), quantity=Decimal("0.002"))
    pos_active = exec1.submit_bracket_order(t_active)
    assert pos_active.state == PositionState.BRACKETS_ACTIVE
    assert len(exec1.active_positions) == 1

    # Instance 2: Simulate application restart
    exec2 = BinanceAtomicExecutor(dry_run=True, initial_equity=Decimal("200.00"), state_file=state_file)

    # Assert active position restored with zero-float precision
    assert len(exec2.active_positions) == 1
    restored_pos = list(exec2.active_positions.values())[0]
    assert restored_pos.symbol == "BTCUSDT"
    assert restored_pos.side == "BUY"
    assert restored_pos.entry_price == Decimal("70000.00")
    assert restored_pos.quantity == Decimal("0.002")
    assert restored_pos.state == PositionState.BRACKETS_ACTIVE

    # Assert last trade remembered
    summary = exec2.get_paper_summary()
    assert summary["last_paper_trade"] is not None
    assert summary["last_paper_trade"]["symbol"] == "ETHUSDT"
    assert summary["last_paper_trade"]["result"] == "WIN"
    assert summary["winning_trades"] == 1
    assert summary["current_equity"] > 200.0
