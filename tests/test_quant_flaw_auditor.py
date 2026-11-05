"""
Tests for Kronos Quant Flaw Auditor
===================================
Verifies detection of:
1. Impossible win rates (Simulation Artifacts).
2. Unconstrained compounding explosions.
3. Inverted bracket geometry.
4. Almgren-Chriss square-root market impact.
"""

from decimal import Decimal
import pytest
from src.quant.quant_flaw_auditor import QuantFlawAuditor, FlawSeverity


def test_quant_flaw_auditor_detects_impossible_win_rate():
    auditor = QuantFlawAuditor(max_realistic_win_rate=Decimal("78.0"))
    summary = {
        "total_trades": 100,
        "winning_trades": 95,
        "win_rate_pct": 95.0,
        "profit_factor": 15.0,
        "initial_equity": 200.0,
        "current_equity": 100000.0,
        "net_return_pct": 49900.0
    }
    verdict = auditor.audit_performance_summary(summary)
    assert not verdict.is_valid
    assert verdict.confidence_score == Decimal("0.00")
    codes = [f.code for f in verdict.flaws]
    assert "FLAW_IMPOSSIBLE_WIN_RATE" in codes
    assert "FLAW_EXTREME_PROFIT_FACTOR" in codes
    assert "FLAW_HYPER_COMPOUNDING_EXPLOSION" in codes


def test_quant_flaw_auditor_passes_realistic_summary():
    auditor = QuantFlawAuditor()
    summary = {
        "total_trades": 30,
        "winning_trades": 16,
        "win_rate_pct": 53.3,
        "profit_factor": 1.45,
        "initial_equity": 200.0,
        "current_equity": 218.40,
        "net_return_pct": 9.2
    }
    verdict = auditor.audit_performance_summary(summary)
    assert verdict.is_valid
    assert verdict.confidence_score == Decimal("1.00")
    assert len(verdict.flaws) == 0


def test_quant_flaw_auditor_almgren_chriss_impact():
    auditor = QuantFlawAuditor()
    # Trade $1,000,000 on an asset with $10,000,000 ADV and 4% daily volatility
    # Participation = 0.1 -> sqrt(0.1) ~ 0.3162 -> 0.5 * 0.04 * 0.3162 = 0.0063 (63 bps impact)
    impact = auditor.compute_almgren_chriss_impact(
        notional_usd=Decimal("1000000.00"),
        adv_24h_usd=Decimal("10000000.00"),
        daily_volatility=Decimal("0.04"),
        eta=Decimal("0.5")
    )
    assert impact > Decimal("0.0050")
    assert impact < Decimal("0.0080")


def test_quant_flaw_auditor_trade_geometry():
    auditor = QuantFlawAuditor()
    # Flawed trade: Exit > Entry but Gross PnL is negative
    bad_trade = {
        "side": "BUY",
        "entry_price": 2000.00,
        "exit_price": 2100.00,
        "gross_pnl_usd": -50.00,
        "realized_pnl_usd": -60.00,
        "duration_minutes": 5,
        "reason": "MANUAL_CLOSE"
    }
    flaws = auditor.audit_trade_record(bad_trade)
    assert any(f.code == "FLAW_INVERTED_PNL" for f in flaws)
