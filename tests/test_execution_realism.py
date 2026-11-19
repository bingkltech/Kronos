"""
tests/test_execution_realism.py — Anti-Fantasy & Truth-Grade Execution Regression Suite
=======================================================================================
Verifies every pillar of the Kronos Institutional Accuracy & Verification Standard:
  1. Zero same-candle retroactive entry fills
  2. Dynamic breakout slippage & taker fees
  3. Hard Take-Profit limit cap (zero phantom overshoot)
  4. Intra-candle wick stop-loss capture
  5. Pessimistic TP+SL same-bar tie-breaker (SL always wins without tick proof)
  6. Chronological tick ordering fidelity
  7. QuantFlawAuditor phantom TP overshoot detection
"""

from decimal import Decimal
import pytest

from src.quant.execution_realism import (
    ExecutionFrictionConfig,
    TickQuote,
    compute_dynamic_slippage_pct,
    evaluate_causal_breakout_entry,
    evaluate_pessimistic_bracket_exit,
    evaluate_market_flatten_exit,
    calculate_exact_trade_pnl,
)
from src.quant.quant_flaw_auditor import QuantFlawAuditor, FlawSeverity


def test_same_candle_retroactive_fill_blocked():
    """Fallback kline opened BEFORE signal creation must NEVER trigger a retroactive fill."""
    signal_ts = 1_700_000_030_000   # Signal emitted 30s into the 1m candle
    same_bar_open = 1_700_000_000_000

    res = evaluate_causal_breakout_entry(
        side="BUY",
        trigger_price=Decimal("100.00"),
        signal_created_ts_ms=signal_ts,
        symbol="EVAAUSDT",
        ticks_after_signal=[],  # No post-signal WS ticks
        fallback_bar_open_ts_ms=same_bar_open,
        fallback_bar_high=Decimal("101.00"),  # Even though candle high > trigger!
        fallback_bar_low=Decimal("99.00"),
    )
    assert res.filled is False
    assert "blocked" in res.reason.lower()


def test_next_bar_and_causal_ws_entry_apply_adverse_slippage():
    """Causal post-signal ticks fill with adverse slippage and VIP0 taker fee (0.05%)."""
    signal_ts = 1_700_000_030_000
    ticks = [
        TickQuote(price=Decimal("100.50"), timestamp_ms=signal_ts - 5000),  # Pre-signal (ignored!)
        TickQuote(price=Decimal("99.90"), timestamp_ms=signal_ts + 1000),   # Below trigger
        TickQuote(price=Decimal("100.05"), timestamp_ms=signal_ts + 2000),  # Causal crossing!
    ]
    res = evaluate_causal_breakout_entry(
        side="BUY",
        trigger_price=Decimal("100.00"),
        signal_created_ts_ms=signal_ts,
        symbol="EVAAUSDT",
        ticks_after_signal=ticks,
        best_ask=Decimal("100.06"),
    )
    assert res.filled is True
    assert res.fill_source == "WS_TICK"
    assert res.fill_price > Decimal("100.06")  # Must include adverse slippage on top of ask
    assert res.entry_fee_pct == Decimal("0.0005")
    assert res.slippage_pct >= Decimal("0.0005")  # >= 5 bps alt floor


def test_take_profit_hard_capped_eliminates_phantom_overshoot():
    """Even when price crashes -2.12% in one tick, SELL Limit TP strictly caps at take_profit."""
    entry = Decimal("58.41")
    tp = Decimal("57.7675")   # -1.10% TP
    sl = Decimal("58.80")

    res = evaluate_pessimistic_bracket_exit(
        side="SELL",
        take_profit=tp,
        stop_loss=sl,
        symbol="SOXSUSDT",
        ordered_ticks=[TickQuote(price=Decimal("57.17"), timestamp_ms=1000)],  # -2.12% flash drop
    )
    assert res.triggered is True
    assert res.action == "TAKE_PROFIT"
    assert res.exit_price == tp  # NEVER 57.17!
    assert res.exit_fee_pct == Decimal("0.0002")  # Maker fee


def test_tp_queue_penetration_required():
    """Touching exact TP price without penetrating does not guarantee resting limit fill."""
    res_touch = evaluate_pessimistic_bracket_exit(
        side="BUY",
        take_profit=Decimal("101.00"),
        stop_loss=Decimal("99.00"),
        symbol="ETHUSDT",
        ordered_ticks=[TickQuote(price=Decimal("101.00"), timestamp_ms=1000)],
        require_tp_penetration=True,
    )
    assert res_touch.triggered is False

    res_pen = evaluate_pessimistic_bracket_exit(
        side="BUY",
        take_profit=Decimal("101.00"),
        stop_loss=Decimal("99.00"),
        symbol="ETHUSDT",
        ordered_ticks=[TickQuote(price=Decimal("101.01"), timestamp_ms=2000)],
        require_tp_penetration=True,
    )
    assert res_pen.triggered is True
    assert res_pen.action == "TAKE_PROFIT"
    assert res_pen.exit_price == Decimal("101.00")


def test_intra_candle_wick_stop_loss_caught_even_when_close_recovers():
    """Fast wick touching SL must stop out the trade even if close finishes in profit."""
    res = evaluate_pessimistic_bracket_exit(
        side="BUY",
        take_profit=Decimal("101.50"),
        stop_loss=Decimal("99.34"),
        symbol="KORUUSDT",
        interval_high=Decimal("100.80"),
        interval_low=Decimal("99.20"),     # Wicked below SL!
        current_price=Decimal("100.50"),   # Recovered above entry by close!
    )
    assert res.triggered is True
    assert res.action == "STOP_LOSS"
    assert res.exit_price < Decimal("99.34")  # Adverse stop slippage applied
    assert res.exit_fee_pct == Decimal("0.0005")  # Taker fee


def test_pessimistic_same_bar_tie_breaker_sl_always_wins():
    """Without tick-level timestamp proof, if one bar hits BOTH TP and SL, STOP_LOSS always wins."""
    res = evaluate_pessimistic_bracket_exit(
        side="BUY",
        take_profit=Decimal("101.00"),
        stop_loss=Decimal("99.00"),
        symbol="MMTUSDT",
        ordered_ticks=[],
        interval_high=Decimal("102.00"),  # Touched TP
        interval_low=Decimal("98.50"),    # AND touched SL
        current_price=Decimal("101.50"),
    )
    assert res.triggered is True
    assert res.action == "STOP_LOSS"


def test_chronological_ws_ticks_respect_exact_ordering():
    """When live WS ticks prove TP penetrated BEFORE SL was touched, TP wins (capped at TP)."""
    ticks = [
        TickQuote(price=Decimal("101.05"), timestamp_ms=1000),  # TP penetrated first!
        TickQuote(price=Decimal("98.90"), timestamp_ms=2000),   # SL hit later
    ]
    res = evaluate_pessimistic_bracket_exit(
        side="BUY",
        take_profit=Decimal("101.00"),
        stop_loss=Decimal("99.00"),
        symbol="EVAAUSDT",
        ordered_ticks=ticks,
    )
    assert res.triggered is True
    assert res.action == "TAKE_PROFIT"
    assert res.exit_price == Decimal("101.00")


def test_friction_stress_multiplier_and_exact_pnl():
    """1.5x and 2.0x stress multipliers scale slippage monotonically and PnL stays exact Decimal."""
    base = compute_dynamic_slippage_pct("EVAAUSDT", Decimal("150"), cfg=ExecutionFrictionConfig(stress_multiplier=Decimal("1.0")))
    mid = compute_dynamic_slippage_pct("EVAAUSDT", Decimal("150"), cfg=ExecutionFrictionConfig(stress_multiplier=Decimal("1.5")))
    high = compute_dynamic_slippage_pct("EVAAUSDT", Decimal("150"), cfg=ExecutionFrictionConfig(stress_multiplier=Decimal("2.0")))
    assert base < mid < high

    bd = calculate_exact_trade_pnl(
        side="BUY",
        entry_price=Decimal("100.00"),
        exit_price=Decimal("101.00"),
        notional_usd=Decimal("100.00"),
        entry_fee_pct=Decimal("0.0005"),
        exit_fee_pct=Decimal("0.0002"),
    )
    assert bd.gross_pnl_usd == Decimal("1.0000")
    assert bd.friction_usd == Decimal("0.0700")
    assert bd.net_pnl_usd == Decimal("0.9300")
    assert bd.is_net_win is True


def test_quant_flaw_auditor_detects_phantom_tp_overshoot():
    """QuantFlawAuditor must flag last night's SOXSUSDT +2.12% TP overshoot as CRITICAL_HALLUCINATION."""
    auditor = QuantFlawAuditor()
    flaws = auditor.audit_trade_record({
        "entry_price": "58.41",
        "exit_price": "57.17",
        "side": "SELL",
        "realized_pnl_usd": "5.54",
        "reason": "Target Hit: +2.12%",
        "max_tp_pct": "0.0190",
    })
    codes = [f.code for f in flaws]
    assert "FLAW_PHANTOM_TP_OVERSHOOT" in codes
    assert any(f.severity == FlawSeverity.CRITICAL_HALLUCINATION for f in flaws)


def test_orderflow_tracker_last_depth_integration():
    """Verify exact SymbolOrderflowTracker.last_depth & trades integration with execution_realism."""
    from src.quant.tiger_orderflow import SymbolOrderflowTracker

    tracker = SymbolOrderflowTracker("EVAAUSDT")
    tracker.process_depth_update(
        best_bid=Decimal("3.7100"),
        best_bid_qty=Decimal("100"),
        best_ask=Decimal("3.7120"),
        best_ask_qty=Decimal("100"),
        timestamp_ms=1000,
    )
    tracker.process_agg_trade(1, Decimal("3.7130"), Decimal("50"), False, 2000)

    assert tracker.last_depth is not None
    ticks = [TickQuote(price=t.price, timestamp_ms=t.timestamp_ms) for t in list(tracker.trades) if t.timestamp_ms > 1500]
    res = evaluate_causal_breakout_entry(
        side="BUY",
        trigger_price=Decimal("3.7118"),
        signal_created_ts_ms=1500,
        symbol="EVAAUSDT",
        ticks_after_signal=ticks,
        best_bid=tracker.last_depth.best_bid,
        best_ask=tracker.last_depth.best_ask,
        live_spread_pct=tracker.last_depth.spread_pct,
    )
    assert res.filled is True
    assert res.fill_price > Decimal("3.7130")

