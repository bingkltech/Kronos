"""
Unit tests for NEON Strategy (Institutional Regime-Adaptive Quant Engine)
Verifies 6-gate evaluation, exact Decimal math, and backtest integrity.
"""

from decimal import Decimal
import pytest
from src.quant.neon_strategy import (
    load_neon_config,
    save_neon_config,
    compute_live_forensic_audit,
    evaluate_neon_universe,
    run_neon_backtest,
    build_neon_equity_curve,
    NEON_CORE_UNIVERSE,
    NEON_QUARANTINED_SYMBOLS,
)


def test_neon_config_lifecycle():
    cfg = load_neon_config()
    assert cfg["strategy_name"] == "NEON Regime-Adaptive Pullback-Resumption"
    assert cfg["risk_per_trade_pct"] == 1.5
    assert cfg["max_leverage"] == 3.5

    updated = save_neon_config({"risk_per_trade_pct": 2.0})
    assert updated["risk_per_trade_pct"] == 2.0
    # Restore
    save_neon_config({"risk_per_trade_pct": 1.5})


def test_neon_forensic_audit():
    audit = compute_live_forensic_audit()
    assert "dataset_summary" in audit
    summary = audit["dataset_summary"]
    assert summary["total_trades"] == 293
    assert summary["baseline"]["trades"] == 293
    assert summary["step_core"]["trades"] <= 293
    assert summary["neon_gated"]["win_rate_pct"] > summary["baseline"]["win_rate_pct"]


def test_neon_universe_scanner():
    equity = Decimal("191.47")
    tickers = {
        "BTCUSDT": {"lastPrice": "60500.0", "priceChangePercent": "2.5"},
        "ETHUSDT": {"lastPrice": "1700.0", "priceChangePercent": "3.1"},
    }
    scan = evaluate_neon_universe(tickers, equity, open_position_count=0)
    assert "evaluations" in scan
    assert len(scan["evaluations"]) == len(NEON_CORE_UNIVERSE) + len(NEON_QUARANTINED_SYMBOLS)
    btc_eval = next((e for e in scan["evaluations"] if e["symbol"] == "BTCUSDT"), None)
    assert btc_eval is not None
    assert btc_eval["tier"] == "CORE_TIER_1"
    assert len(btc_eval["gates"]) == 6


def test_neon_backtest_and_equity_curve():
    bt = run_neon_backtest("BTCUSDT", initial_equity=200.0, mirror_bull=False)
    assert bt["symbol"] == "BTCUSDT"
    assert bt["initial_equity_usd"] == 200.0
    assert isinstance(bt["net_pnl_usd"], float)

    curve = build_neon_equity_curve("CORE_BASKET", initial_equity=200.0)
    assert curve["scope"] == "CORE_BASKET"
    assert len(curve["series"]) > 0
    assert "trade_markers" in curve
    assert curve["summary"]["initial_equity_usd"] == 200.0
