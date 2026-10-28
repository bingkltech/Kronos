"""
tests/test_kev_risk_arbiter.py — ASVL Verification Suite for src/quant/kev_risk_arbiter.py.

Validates the 6-Point Supreme Veto Gate & Fractional Kelly Risk Sizing:
1. Gate 1: News & Macro Blackout Shield rejection.
2. Gate 2: Macro Confluence rejection (counter-trend trading).
3. Gate 3: Net Fee Hurdle rejection (Lesson #10 compliance).
4. Gate 4: Crypto Carry & Funding Rate Guard rejection.
5. Gate 5: Portfolio Correlation Shield rejection (rho >= 0.85).
6. Gate 6: Risk-to-Reward ratio minimum (RR >= 1.50:1).
7. Full approval generates type-strict TradeTicket in Decimal.
"""

import os
import sys
from decimal import Decimal
import pytest

WORKSPACE_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if WORKSPACE_ROOT not in sys.path:
    sys.path.insert(0, WORKSPACE_ROOT)

from src.quant.kev_risk_arbiter import KEVSupremeArbiter, TradeTicket, KEVDecision
from src.quant.macro_specialists import NewsBlackoutVerdict, CarryVerdict
from src.quant.crypto_index_engine import MacroIndexVerdict, SymbolMacroStats
from src.quant.kronos_onnx_engine import TrajectoryVerdict


def _make_valid_verdicts(symbol="ETHUSDT", side="LONG"):
    """Helper creating a baseline set of passing verdicts."""
    news = NewsBlackoutVerdict(is_blackout=False, event_name="", minutes_to_event=None, reason="Clear")
    
    # 70% breadth -> BULL_EXPANSION
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

    # Spot: 2500, Terminal: 2560 (+2.40% drift), SL: 2465 (-1.40%), TP: 2560 (+2.40%)
    # RR = 60 / 35 = 1.71 : 1 >= 1.50 : 1
    # Net drift = 2.40% - 0.16% = 2.24% >= 0.50%
    trajectory = TrajectoryVerdict(
        symbol=symbol,
        current_price=Decimal("2500.00"),
        terminal_price=Decimal("2560.00"),
        path_high=Decimal("2560.00"),
        path_low=Decimal("2465.00"),
        raw_drift=Decimal("0.0240"),
        dynamic_take_profit=Decimal("2560.00"),
        dynamic_stop_loss=Decimal("2465.00"),
        proposed_side=side,
        horizon_hours=12,
        rationale="Strong bullish setup"
    )

    return trajectory, news, macro, carry


def test_gate_1_news_blackout_veto():
    """Verify rejection when news blackout is active."""
    arbiter = KEVSupremeArbiter()
    traj, news, macro, carry = _make_valid_verdicts()
    
    blackout_news = NewsBlackoutVerdict(
        is_blackout=True, event_name="FOMC", minutes_to_event=10, reason="FOMC approaching"
    )
    decision = arbiter.evaluate_candidate(
        traj, blackout_news, macro, carry, account_equity=Decimal("10000.00")
    )

    assert not decision.approved
    assert decision.veto_gate_failed == "GATE_1_NEWS_BLACKOUT"
    assert decision.ticket is None


def test_gate_2_macro_confluence_veto():
    """Verify rejection when trying to Long during systemic Bear Distribution."""
    arbiter = KEVSupremeArbiter()
    traj, news, macro, carry = _make_valid_verdicts()

    bear_macro = MacroIndexVerdict(
        macro_regime="BEAR_DISTRIBUTION",
        breadth_ratio=Decimal("0.20"),
        coins_above_vwap_count=2,
        total_coins_evaluated=10,
        symbol_stats={},
        reason="Bear Distribution"
    )
    decision = arbiter.evaluate_candidate(
        traj, news, bear_macro, carry, account_equity=Decimal("10000.00")
    )

    assert not decision.approved
    assert decision.veto_gate_failed == "GATE_2_MACRO_CONFLUENCE"


def test_gate_3_fee_hurdle_veto():
    """Verify Lesson #10 enforcement: net drift must clear 0.50% hurdle."""
    arbiter = KEVSupremeArbiter()
    traj, news, macro, carry = _make_valid_verdicts()

    # Weak drift: +0.35% raw drift. Friction is 0.16% -> Net is 0.19% < 0.50% hurdle
    weak_traj = TrajectoryVerdict(
        symbol="ETHUSDT",
        current_price=Decimal("2500.00"),
        terminal_price=Decimal("2508.75"),
        path_high=Decimal("2510.00"),
        path_low=Decimal("2495.00"),
        raw_drift=Decimal("0.0035"),
        dynamic_take_profit=Decimal("2510.00"),
        dynamic_stop_loss=Decimal("2495.00"),
        proposed_side="LONG",
        horizon_hours=12,
        rationale="Weak drift"
    )
    decision = arbiter.evaluate_candidate(
        weak_traj, news, macro, carry, account_equity=Decimal("10000.00")
    )

    assert not decision.approved
    assert decision.veto_gate_failed == "GATE_3_FEE_HURDLE"


def test_gate_4_carry_guard_veto():
    """Verify rejection when 8h funding rate is prohibitive."""
    arbiter = KEVSupremeArbiter()
    traj, news, macro, carry = _make_valid_verdicts()

    prohib_carry = CarryVerdict(
        symbol="ETHUSDT",
        verdict="PROHIBITIVE",
        funding_rate=Decimal("0.0004"),
        annualized_rate=Decimal("0.438"),
        next_funding_time_utc=None,
        reason="Funding prohibitive"
    )
    decision = arbiter.evaluate_candidate(
        traj, news, macro, prohib_carry, account_equity=Decimal("10000.00")
    )

    assert not decision.approved
    assert decision.veto_gate_failed == "GATE_4_CARRY_GUARD"


def test_gate_5_correlation_shield_veto():
    """Verify rejection when candidate shares high correlation with open position."""
    arbiter = KEVSupremeArbiter()
    traj, news, macro, carry = _make_valid_verdicts(symbol="SOLUSDT")

    active_positions = ["ETHUSDT"]
    correlations = {
        "SOLUSDT": {"ETHUSDT": Decimal("0.89")}  # 0.89 >= 0.85 threshold
    }

    decision = arbiter.evaluate_candidate(
        traj, news, macro, carry,
        account_equity=Decimal("10000.00"),
        active_positions=active_positions,
        correlation_matrix=correlations
    )

    assert not decision.approved
    assert decision.veto_gate_failed == "GATE_5_CORRELATION_SHIELD"


def test_gate_6_risk_reward_veto():
    """Verify rejection when Take-Profit over Stop-Loss < 1.50:1."""
    arbiter = KEVSupremeArbiter()
    traj, news, macro, carry = _make_valid_verdicts()

    # Spot: 2500, TP: 2525 (+25), SL: 2470 (-30) -> RR = 25/30 = 0.83 : 1 < 1.50 : 1
    bad_rr_traj = TrajectoryVerdict(
        symbol="ETHUSDT",
        current_price=Decimal("2500.00"),
        terminal_price=Decimal("2525.00"),
        path_high=Decimal("2525.00"),
        path_low=Decimal("2470.00"),
        raw_drift=Decimal("0.0100"),
        dynamic_take_profit=Decimal("2525.00"),
        dynamic_stop_loss=Decimal("2470.00"),
        proposed_side="LONG",
        horizon_hours=12,
        rationale="Poor RR setup"
    )

    decision = arbiter.evaluate_candidate(
        bad_rr_traj, news, macro, carry, account_equity=Decimal("10000.00")
    )

    assert not decision.approved
    assert decision.veto_gate_failed == "GATE_6_RISK_REWARD"


def test_full_approval_and_kelly_sizing():
    """Verify approved trade generates exact Decimal TradeTicket."""
    arbiter = KEVSupremeArbiter()
    traj, news, macro, carry = _make_valid_verdicts()

    # Equity: $10,000. Risk budget ratio: 1.5% -> $150.00 risk budget
    # Entry: 2500.00, SL: 2465.00 -> Risk per unit = $35.00
    # Expected qty: 150 / 35 = 4.2857 -> quantized to 4.285 ETH
    # Notional: 4.285 * 2500 = $10,712.50
    # Leverage: ceil(10712.5 / 10000) = 2x
    decision = arbiter.evaluate_candidate(
        traj, news, macro, carry,
        account_equity=Decimal("10000.00"),
        active_positions=[],
        confidence_multiplier=Decimal("1.0")
    )

    assert decision.approved
    assert decision.veto_gate_failed is None
    ticket = decision.ticket
    assert ticket is not None
    assert ticket.symbol == "ETHUSDT"
    assert ticket.side == "BUY"
    assert ticket.entry_price == Decimal("2500.00")
    assert ticket.stop_loss == Decimal("2465.00")
    assert ticket.take_profit == Decimal("2560.00")
    assert ticket.risk_budget_usd == Decimal("150.00")
    assert ticket.quantity == Decimal("4.285")
    assert ticket.notional_usd == Decimal("10712.50")
    assert ticket.effective_leverage == 2
    assert ticket.reward_risk_ratio == Decimal("1.71")
    assert isinstance(ticket.net_expected_gain_pct, Decimal)
