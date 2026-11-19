"""
tests/test_advisory_consultant.py — Validation of Specialized Advisory Consultant & Mathematical Audit Engine.

Invariants Verified:
1. Zero Float Financial Math: Uses Decimal everywhere for prices, returns, alpha, and conviction scores.
2. Tri-Perspective ACR Formula: ACR = (C_bull * (1 - P_bear)) / (1 + R_drag).
3. Adversarial Veto Trigger: Rejects trades with crowded funding or firing into Volume Profile POC.
4. Post-Trade Alpha Settlement: Accurately attributes alpha vs. BTC and generates 2-sentence empirical lesson.
"""

import pytest
from decimal import Decimal
from src.quant.advisory_consultant import AdvisoryConsultantEngine, TriPerspectiveAudit, AdvisoryAssessment


def test_tri_perspective_acr_formula():
    """Verify mathematical properties of ACR formula."""
    consultant = AdvisoryConsultantEngine()

    # Scenario 1: Ideal bull setup (C_bull=0.85, P_bear=0.10, R_drag=0.125)
    # ACR = (0.85 * (1 - 0.10)) / (1 + 0.125) = (0.85 * 0.90) / 1.125 = 0.765 / 1.125 = 0.6800
    acr_ideal = consultant.compute_acr(
        bull_conviction=Decimal("0.85"),
        bear_trap_risk=Decimal("0.10"),
        friction_drag=Decimal("0.125")
    )
    assert acr_ideal == Decimal("0.6800")

    # Scenario 2: Overcrowded Bear Trap (C_bull=0.85, P_bear=0.60, R_drag=0.125)
    # ACR = (0.85 * 0.40) / 1.125 = 0.340 / 1.125 = 0.3022 -> Heavy Veto
    acr_trap = consultant.compute_acr(
        bull_conviction=Decimal("0.85"),
        bear_trap_risk=Decimal("0.60"),
        friction_drag=Decimal("0.125")
    )
    assert acr_trap == Decimal("0.3022")
    assert acr_trap < Decimal("0.40")

    # Scenario 3: High Friction Drag (C_bull=0.70, P_bear=0.15, R_drag=0.50)
    # ACR = (0.70 * 0.85) / 1.50 = 0.595 / 1.50 = 0.3967 -> Friction Bleed Veto
    acr_friction = consultant.compute_acr(
        bull_conviction=Decimal("0.70"),
        bear_trap_risk=Decimal("0.15"),
        friction_drag=Decimal("0.50")
    )
    assert acr_friction == Decimal("0.3967")


def test_assess_instrument_with_poc_and_funding():
    """Verify assess_instrument detects POC resistance ceiling and funding rate traps."""
    consultant = AdvisoryConsultantEngine()

    curr_p = Decimal("100.00")
    recent_klines = [
        {"close": Decimal("99.50"), "high": Decimal("100.20"), "low": Decimal("99.20")},
        {"close": Decimal("100.00"), "high": Decimal("100.50"), "low": Decimal("99.80")}
    ]

    # Setup A: Firing right into POC resistance ceiling (POC = 100.20, price = 100.00 -> -0.20% dist)
    assess_poc_trap = consultant.assess_instrument(
        symbol="SOLUSDT",
        current_price=curr_p,
        order_book_imbalance=Decimal("0.35"),  # Good book pressure
        micro_skew_bps=Decimal("2.0"),
        recent_klines=recent_klines,
        volume_profile_poc=Decimal("100.20"),   # Resistance right above!
        funding_rate_bps=Decimal("3.5")        # Crowded funding!
    )
    assert assess_poc_trap.volume_profile_poc_aligned is False
    assert assess_poc_trap.audit.bear_trap_risk >= Decimal("0.60")
    assert assess_poc_trap.rating in ("HOLD", "UNDERWEIGHT", "AVOID")
    assert assess_poc_trap.audit.risk_verdict == "ADVERSARIAL_VETO"

    # Setup B: Clean breakout above POC with neutral funding
    assess_clean = consultant.assess_instrument(
        symbol="SOLUSDT",
        current_price=Decimal("105.00"),
        order_book_imbalance=Decimal("0.40"),
        micro_skew_bps=Decimal("2.5"),
        recent_klines=recent_klines,
        volume_profile_poc=Decimal("100.00"),  # Support far below
        funding_rate_bps=Decimal("0.2")       # Healthy funding
    )
    assert assess_clean.volume_profile_poc_aligned is True
    assert assess_clean.audit.bear_trap_risk <= Decimal("0.30")
    assert assess_clean.audit.acr_score >= Decimal("0.58")
    assert assess_clean.rating in ("STRONG_BUY", "OVERWEIGHT")


def test_settle_and_reflect_trade_attribution():
    """Verify post-trade reflection, alpha calculation, and lesson generation."""
    consultant = AdvisoryConsultantEngine()

    # Case 1: Scalp win with outperformance against BTC
    # Entry: $1000, Exit: $1005 (+0.50% gross). Real ETH friction: 0.16%. Net: +0.34%.
    # BTC moved +0.10% in same period. Alpha = +0.50% - +0.10% = +0.40%.
    ref_win = consultant.settle_and_reflect(
        position_id="SCALP-WIN-1",
        symbol="ETHUSDT",
        side="BUY",
        entry_price=Decimal("1000.00"),
        exit_price=Decimal("1005.00"),
        holding_seconds=420,  # 7 minutes (sweetspot ok)
        btc_entry_price=Decimal("90000.00"),
        btc_exit_price=Decimal("90090.00"),  # +0.10%
        is_scalp=True
    )
    assert ref_win.gross_return_pct == Decimal("0.50")
    assert ref_win.net_return_pct == Decimal("0.34")
    assert ref_win.alpha_return_pct == Decimal("0.40")
    assert ref_win.sweetspot_compliance is True
    assert ref_win.dominant_root_cause == "THESIS_CONFIRMED_PROFIT"
    assert "Alpha: +0.40% vs BTC" in ref_win.empirical_lesson
    assert "sweetspot" in ref_win.empirical_lesson

    # Case 2: Friction Tax Drag (Gross win turned into net loss by taker fees)
    # Entry: $1000, Exit: $1000.50 (+0.05% gross). Fees: 0.10%. Net: -0.05%.
    ref_friction = consultant.settle_and_reflect(
        position_id="SCALP-DRAG-1",
        symbol="ETHUSDT",
        side="BUY",
        entry_price=Decimal("1000.00"),
        exit_price=Decimal("1000.50"),
        holding_seconds=300,
        btc_entry_price=Decimal("90000.00"),
        btc_exit_price=Decimal("90000.00"),
        is_scalp=True
    )
    assert ref_friction.dominant_root_cause == "FRICTION_TAX_BLEED"
    assert "taker friction" in ref_friction.empirical_lesson
