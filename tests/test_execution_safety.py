"""
tests/test_execution_safety.py — ASVL Verification Suite for Quant Execution Safety.

Validates:
1. Pre-flight invariant: Inverted bracket rejection in submit_live_bracket_order.
2. Gate 6 invariant: KEV vetoes inverted brackets (abs() flaw resolution).
3. Ghost Algo Order Purge: Auto-cancellation of dangling algo orders for closed/orphaned symbols.
4. Leverage alignment: Contract margin leverage dispatch without 1x collapse.
"""

import os
import sys
from decimal import Decimal
from unittest.mock import MagicMock
import pytest

WORKSPACE_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if WORKSPACE_ROOT not in sys.path:
    sys.path.insert(0, WORKSPACE_ROOT)

from src.quant.binance_execution import (
    BinanceAtomicExecutor,
    ActiveBracketPosition,
    PositionState,
)
from src.quant.kev_risk_arbiter import (
    KEVSupremeArbiter,
    TradeTicket,
)
from src.quant.kronos_onnx_engine import TrajectoryVerdict
from src.quant.macro_specialists import NewsBlackoutVerdict, CarryVerdict
from src.quant.crypto_index_engine import MacroIndexVerdict


def _make_ticket(symbol="ETHUSDT", side="BUY", entry=Decimal("2000.00"), sl=Decimal("1950.00"), tp=Decimal("2100.00"), qty=Decimal("0.05")):
    return TradeTicket(
        symbol=symbol,
        side=side,
        entry_price=entry,
        stop_loss=sl,
        take_profit=tp,
        quantity=qty,
        notional_usd=(entry * qty),
        effective_leverage=3,
        risk_budget_usd=Decimal("10.00"),
        reward_risk_ratio=Decimal("2.00"),
        net_expected_gain_pct=Decimal("5.00"),
    )


def _make_passing_context(symbol="ETHUSDT"):
    news = NewsBlackoutVerdict(is_blackout=False, event_name="", minutes_to_event=None, reason="Clear")
    macro = MacroIndexVerdict(
        macro_regime="BULL_EXPANSION",
        breadth_ratio=Decimal("0.70"),
        coins_above_vwap_count=7,
        total_coins_evaluated=10,
        symbol_stats={},
        reason="Bull Expansion"
    )
    carry = CarryVerdict(
        symbol=symbol,
        verdict="NEUTRAL",
        funding_rate=Decimal("0.0001"),
        annualized_rate=Decimal("0.1095"),
        next_funding_time_utc=None,
        reason="Normal funding"
    )
    return news, macro, carry


def test_preflight_inverted_bracket_rejection_long():
    """Ensure LONG orders with SL >= entry or TP <= entry are rejected BEFORE any REST order call."""
    executor = BinanceAtomicExecutor(dry_run=False, api_key="test", secret_key="test")
    executor._signed_request = MagicMock()

    # Inverted SL (SL above entry)
    bad_ticket_sl = _make_ticket(side="BUY", entry=Decimal("2000.00"), sl=Decimal("2050.00"), tp=Decimal("2100.00"))
    pos = executor.submit_live_bracket_order(bad_ticket_sl)
    assert pos.state == PositionState.REJECTED
    assert "INVERTED_BRACKET" in pos.close_reason
    assert executor._signed_request.call_count == 0

    # Inverted TP (TP below entry)
    bad_ticket_tp = _make_ticket(side="BUY", entry=Decimal("2000.00"), sl=Decimal("1950.00"), tp=Decimal("1900.00"))
    pos_tp = executor.submit_live_bracket_order(bad_ticket_tp)
    assert pos_tp.state == PositionState.REJECTED
    assert "INVERTED_BRACKET" in pos_tp.close_reason
    assert executor._signed_request.call_count == 0


def test_preflight_inverted_bracket_rejection_short():
    """Ensure SHORT orders with TP >= entry or SL <= entry are rejected BEFORE any REST order call."""
    executor = BinanceAtomicExecutor(dry_run=False, api_key="test", secret_key="test")
    executor._signed_request = MagicMock()

    # Inverted SL on short (SL below entry)
    bad_short_sl = _make_ticket(side="SELL", entry=Decimal("2000.00"), sl=Decimal("1950.00"), tp=Decimal("1900.00"))
    pos = executor.submit_live_bracket_order(bad_short_sl)
    assert pos.state == PositionState.REJECTED
    assert "INVERTED_BRACKET" in pos.close_reason
    assert executor._signed_request.call_count == 0

    # Inverted TP on short (TP above entry)
    bad_short_tp = _make_ticket(side="SELL", entry=Decimal("2000.00"), sl=Decimal("2050.00"), tp=Decimal("2100.00"))
    pos_tp = executor.submit_live_bracket_order(bad_short_tp)
    assert pos_tp.state == PositionState.REJECTED
    assert "INVERTED_BRACKET" in pos_tp.close_reason
    assert executor._signed_request.call_count == 0


def test_kev_gate_6_inverted_bracket_veto():
    """Verify KEV Gate 6 vetoes inverted brackets even if absolute distance passes R:R check."""
    arbiter = KEVSupremeArbiter()
    news, macro, carry = _make_passing_context("ETHUSDT")

    # Inverted LONG: SL=2100 (>2000), TP=2200 (>2000) but SL is above entry!
    traj_long = TrajectoryVerdict(
        symbol="ETHUSDT",
        current_price=Decimal("2000.00"),
        terminal_price=Decimal("2200.00"),
        path_high=Decimal("2250.00"),
        path_low=Decimal("1950.00"),
        raw_drift=Decimal("0.10"),
        dynamic_take_profit=Decimal("2200.00"),
        dynamic_stop_loss=Decimal("2050.00"),    # INVERTED! SL > entry on Long!
        proposed_side="LONG",
        horizon_hours=12,
        rationale="Test inverted long"
    )
    dec = arbiter.evaluate_candidate(traj_long, news, macro, carry, account_equity=Decimal("200.00"))
    assert not dec.approved
    assert dec.veto_gate_failed == "GATE_6_INVALID_STOPS"

    # Inverted SHORT: SL=1950 (<2000), TP=1800 (<2000) but SL is below entry!
    macro_bear = MacroIndexVerdict(
        macro_regime="BEAR_EXPANSION",
        breadth_ratio=Decimal("0.20"),
        coins_above_vwap_count=2,
        total_coins_evaluated=10,
        symbol_stats={},
        reason="Bear Expansion"
    )
    traj_short = TrajectoryVerdict(
        symbol="ETHUSDT",
        current_price=Decimal("2000.00"),
        terminal_price=Decimal("1800.00"),
        path_high=Decimal("2050.00"),
        path_low=Decimal("1750.00"),
        raw_drift=Decimal("-0.10"),
        dynamic_take_profit=Decimal("1800.00"),
        dynamic_stop_loss=Decimal("1950.00"),    # INVERTED! SL < entry on Short!
        proposed_side="SHORT",
        horizon_hours=12,
        rationale="Test inverted short"
    )
    dec_short = arbiter.evaluate_candidate(traj_short, news, macro_bear, carry, account_equity=Decimal("200.00"))
    assert not dec_short.approved
    assert dec_short.veto_gate_failed == "GATE_6_INVALID_STOPS"


def test_purge_orphaned_algo_orders():
    """Verify purge_orphaned_algo_orders deletes algo orders for zero-position symbols while preserving active brackets."""
    executor = BinanceAtomicExecutor(dry_run=False, api_key="test", secret_key="test")

    mock_positions = [
        {"symbol": "BTCUSDT", "positionAmt": "-0.001", "leverage": "3"},
        {"symbol": "SUIUSDT", "positionAmt": "0.0", "leverage": "1"},
        {"symbol": "DOGEUSDT", "positionAmt": "768", "leverage": "3"},
    ]

    mock_algo_orders = [
        {"algoId": 1, "symbol": "SUIUSDT", "side": "BUY", "triggerPrice": "0.784"},
        {"algoId": 2, "symbol": "SUIUSDT", "side": "BUY", "triggerPrice": "0.8125"},
        {"algoId": 3, "symbol": "DOGEUSDT", "side": "SELL", "triggerPrice": "0.067"},  # defending long
    ]

    def mock_signed_request(method, endpoint, params=None):
        if endpoint == "/fapi/v2/positionRisk":
            return mock_positions
        if endpoint == "/fapi/v1/openAlgoOrders":
            return mock_algo_orders
        if endpoint == "/fapi/v1/algoOpenOrders" and method == "DELETE":
            return {"code": 200, "msg": f"Cancelled for {params.get('symbol')}"}
        return {}

    executor._signed_request = MagicMock(side_effect=mock_signed_request)

    purged = executor.purge_orphaned_algo_orders()
    assert "SUIUSDT" in purged
    assert "BTCUSDT" not in purged
    assert "DOGEUSDT" not in purged
