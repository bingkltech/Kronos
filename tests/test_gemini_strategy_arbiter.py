# -*- coding: utf-8 -*-
"""
Tests for GeminiStrategyArbiter & Meta-Strategy Assessment Engine.
"""

from decimal import Decimal
from unittest.mock import MagicMock
from src.quant.gemini_strategy_arbiter import (
    GeminiStrategyArbiter,
    StrategyAssessmentOutput,
    MIN_RR_BOUND,
    MAX_RR_BOUND,
    MIN_FEE_HURDLE_BOUND,
    MAX_FEE_HURDLE_BOUND,
    MIN_RISK_BUDGET_BOUND,
    MAX_RISK_BUDGET_BOUND
)


def _build_dummy_summaries():
    macro_summary = {
        "macro_regime": "BULL_EXPANSION",
        "breadth_pct": "70.0%",
        "coins_above_vwap": 7,
        "total_coins": 10,
        "news_blackout": {"is_blackout": False}
    }
    paper_summary = {
        "current_equity_usdt": 204.50,
        "total_trades": 8,
        "wins": 5,
        "losses": 3,
        "win_rate_pct": 62.5,
        "net_pnl_usdt": 4.50,
        "net_pnl_pct": 2.25,
        "profit_factor": 1.85,
        "closed_trades": [
            {
                "symbol": "BTCUSDT",
                "side": "LONG",
                "entry_price": 83200.0,
                "exit_price": 84100.0,
                "pnl_usd": 2.20,
                "pnl_pct": 1.08,
                "exit_reason": "BRACKET_TAKE_PROFIT"
            },
            {
                "symbol": "SOLUSDT",
                "side": "SHORT",
                "entry_price": 185.0,
                "exit_price": 187.2,
                "pnl_usd": -1.10,
                "pnl_pct": -1.18,
                "exit_reason": "BRACKET_STOP_LOSS"
            }
        ]
    }
    lessons_summary = {
        "brier_score": 0.175,
        "confidence_multiplier": 1.0,
        "total_lessons": 12
    }
    current_settings = {
        "rr_hurdle_ratio": 1.60,
        "fee_hurdle_pct": 0.50,
        "risk_budget_pct": 1.50,
        "param_sweep_fast_ema": 17,
        "param_sweep_slow_ema": 65
    }
    return macro_summary, paper_summary, lessons_summary, current_settings


def test_build_strategic_digest():
    arbiter = GeminiStrategyArbiter(api_key="test_dummy_key")
    m, p, l, c = _build_dummy_summaries()
    digest = arbiter.build_strategic_digest(m, p, l, c)

    assert "BULL_EXPANSION" in digest
    assert "204.50 USDT" in digest
    assert "BTCUSDT LONG" in digest
    assert "SOLUSDT SHORT" in digest
    assert len(digest) < 3000


def test_fallback_assessment_regimes():
    arbiter = GeminiStrategyArbiter(api_key="")  # Force fallback
    m, p, l, c = _build_dummy_summaries()

    # Test Bull Expansion
    m["macro_regime"] = "BULL_EXPANSION"
    res_bull = arbiter.evaluate_strategy(m, p, l, c)
    assert res_bull.sweetspot_rr_ratio >= 1.60
    assert res_bull.confidence_score > 0.70

    # Test Chop Compression
    m["macro_regime"] = "CHOP_COMPRESSION"
    res_chop = arbiter.evaluate_strategy(m, p, l, c)
    assert res_chop.sweetspot_rr_ratio <= 1.60
    assert "CHOP_COMPRESSION" in res_chop.regime_diagnosis


def test_safety_bounds_clamping():
    arbiter = GeminiStrategyArbiter(api_key="test")
    # Test values beyond bounds
    rr_clamped = arbiter._clamp_decimal(Decimal("5.0"), MIN_RR_BOUND, MAX_RR_BOUND)
    assert rr_clamped == MAX_RR_BOUND  # 2.20

    rr_clamped_low = arbiter._clamp_decimal(Decimal("0.5"), MIN_RR_BOUND, MAX_RR_BOUND)
    assert rr_clamped_low == MIN_RR_BOUND  # 1.40

    fee_clamped = arbiter._clamp_decimal(Decimal("0.020"), MIN_FEE_HURDLE_BOUND, MAX_FEE_HURDLE_BOUND)
    assert fee_clamped == MAX_FEE_HURDLE_BOUND  # 0.75%


def test_mocked_gemini_api_response_parsing():
    """Verify that structured JSON from Gemini is parsed, clamped, and formatted cleanly."""
    arbiter = GeminiStrategyArbiter(api_key="mock_key")
    arbiter.client = MagicMock()

    mock_resp = MagicMock()
    mock_resp.text = """{
      "regime_diagnosis": "BULL_EXPANSION with rising liquidity",
      "sweetspot_rr_ratio": 1.85,
      "sweetspot_fee_hurdle_pct": 0.55,
      "sweetspot_risk_budget_pct": 1.40,
      "sweetspot_fast_ema": 15,
      "sweetspot_slow_ema": 58,
      "market_edge_summary": "Trend continuation favors higher R:R hurdles.",
      "confidence_score": 0.91,
      "action_items": ["Focus on breakout longs", "Let winners run to 1.85 R:R"]
    }"""
    arbiter.client.models.generate_content.return_value = mock_resp

    m, p, l, c = _build_dummy_summaries()
    res = arbiter.evaluate_strategy(m, p, l, c)

    assert isinstance(res, StrategyAssessmentOutput)
    assert res.sweetspot_rr_ratio == 1.85
    assert res.sweetspot_fee_hurdle_pct == 0.55
    assert res.sweetspot_risk_budget_pct == 1.40
    assert res.sweetspot_fast_ema == 15
    assert res.sweetspot_slow_ema == 58
    assert res.confidence_score == 0.91
    assert "BULL_EXPANSION" in res.regime_diagnosis
