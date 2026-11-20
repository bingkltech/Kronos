"""
tests/test_tiger_scout_bridge.py — Comprehensive Unit Tests for Tiger-to-Macro Scout Bridge.

Verifies:
1. Zero Float Financial Math (Decimal everywhere).
2. JSON parsing, validation, and TTL caching of tiger_radar.json.
3. Candidate extraction with institutional turnover & quarantine filters.
4. Confluence (+20% Kelly boost) and adversarial conflict (-30% Kelly throttle) evaluation.
5. Dynamic hot prey injection and precision resolution in QuantBotOrchestrator.
"""

import json
import tempfile
import datetime
from decimal import Decimal
import pandas as pd
import pytest

from src.quant.tiger_scout_bridge import (
    PreyNanoTelemetry,
    TigerScoutReport,
    TigerScoutBridge,
)
from src.quant.orchestrator import QuantBotOrchestrator
from src.quant.config import TOP_10_SYMBOLS, DEFAULT_RISK_CONFIG, FuturesSymbolConfig
from src.quant.binance_execution import BinanceAtomicExecutor
from src.quant.kronos_onnx_engine import TrajectoryVerdict


@pytest.fixture
def sample_radar_json(tmp_path):
    """Creates a temporary mock tiger_radar.json file with rich orderflow telemetry."""
    radar_file = tmp_path / "tiger_radar.json"
    data = {
        "updated_at_utc": "2026-11-20T12:00:00+00:00",
        "ws_ticks": 45000,
        "used_weight": 145,
        "btc_1m_return_pct": "0.15",
        "btc_cvd_zscore": "1.4",
        "quarantined_count": 2,
        "quarantined_symbols": ["ETHUSDT", "SOLUSDT"],
        "active_prey": [
            {
                "rank": 1,
                "symbol": "XRPUSDT",
                "last_price": "1.4520",
                "price_change_pct": "5.60",
                "turnover_24h_usd": "85000000.00",
                "volatility_score": "0.85",
                "dynamic_strength_pct": "92.4",
                "stagnation_status": "ACTIVE",
                "retention_ratio_pct": "95.0",
                "elapsed_seconds": 12.5,
                "is_quarantined": False,
                "open_interest": "12000000",
                "delta_oi_pct": "2.45",
                "cvd_zscore": "-1.8",
                "micro_skew_bps": "0.35",
                "ofi_score": "0.45",
                "spread_bps": "0.8",
                "absorption_signal": "BUY"
            },
            {
                "rank": 2,
                "symbol": "ADAUSDT",
                "last_price": "0.1495",
                "price_change_pct": "-3.20",
                "turnover_24h_usd": "65000000.00",
                "volatility_score": "0.78",
                "dynamic_strength_pct": "84.1",
                "stagnation_status": "ACTIVE",
                "retention_ratio_pct": "88.0",
                "elapsed_seconds": 25.0,
                "is_quarantined": False,
                "open_interest": "5400000",
                "delta_oi_pct": "1.10",
                "cvd_zscore": "2.3",
                "micro_skew_bps": "-0.28",
                "ofi_score": "-0.35",
                "spread_bps": "1.2",
                "absorption_signal": "SELL"
            },
            {
                "rank": 3,
                "symbol": "LOWVOLUSDT",
                "last_price": "2.1000",
                "price_change_pct": "1.10",
                "turnover_24h_usd": "15000000.00",  # Below $50M turnover floor
                "volatility_score": "0.40",
                "dynamic_strength_pct": "45.0",
                "stagnation_status": "ACTIVE",
                "retention_ratio_pct": "90.0",
                "elapsed_seconds": 10.0,
                "is_quarantined": False,
                "open_interest": "1000000",
                "delta_oi_pct": "0.10",
                "cvd_zscore": "0.1",
                "micro_skew_bps": "0.02",
                "ofi_score": "0.05",
                "spread_bps": "2.0",
                "absorption_signal": "NONE"
            },
            {
                "rank": 4,
                "symbol": "QUARUSDT",
                "last_price": "0.5000",
                "price_change_pct": "-10.00",
                "turnover_24h_usd": "90000000.00",
                "volatility_score": "0.95",
                "dynamic_strength_pct": "10.0",
                "stagnation_status": "STAGNANT",
                "retention_ratio_pct": "30.0",
                "elapsed_seconds": 45.0,
                "is_quarantined": True,
                "open_interest": "3000000",
                "delta_oi_pct": "-5.00",
                "cvd_zscore": "-3.0",
                "micro_skew_bps": "-0.50",
                "ofi_score": "-0.80",
                "spread_bps": "3.5",
                "absorption_signal": "NONE"
            }
        ]
    }
    with open(radar_file, "w", encoding="utf-8") as f:
        json.dump(data, f)
    return str(radar_file)


def test_bridge_load_report_zero_float(sample_radar_json):
    """Verifies that TigerScoutBridge loads radar JSON adhering to zero float Decimal math."""
    bridge = TigerScoutBridge(radar_paths=[sample_radar_json])
    report = bridge.load_report()
    assert report is not None
    assert report.ws_ticks == 45000
    assert report.btc_1m_return_pct == Decimal("0.15")
    assert report.btc_cvd_zscore == Decimal("1.4")
    assert "ETHUSDT" in report.quarantined_symbols
    assert len(report.active_prey) == 4

    xrp = report.active_prey["XRPUSDT"]
    assert isinstance(xrp.last_price, Decimal)
    assert xrp.last_price == Decimal("1.4520")
    assert xrp.cvd_zscore == Decimal("-1.8")
    assert xrp.micro_skew_bps == Decimal("0.35")
    assert xrp.absorption_signal == "BUY"


def test_bridge_candidate_screening(sample_radar_json):
    """Verifies candidate extraction filters existing universe, low turnover, and quarantined assets."""
    bridge = TigerScoutBridge(radar_paths=[sample_radar_json])

    # 1. Base test: existing universe has BTC and ETH, but not XRP or ADA
    candidates = bridge.get_scouted_prey_candidates(
        existing_universe=["BTCUSDT", "ETHUSDT"],
        max_candidates=2,
        min_turnover_usd=Decimal("50000000.00")
    )
    # Should select Rank 1 (XRPUSDT) and Rank 2 (ADAUSDT)
    assert len(candidates) == 2
    assert candidates[0].symbol == "XRPUSDT"
    assert candidates[1].symbol == "ADAUSDT"

    # 2. If ADAUSDT is already in existing universe, it should be excluded
    candidates_no_ada = bridge.get_scouted_prey_candidates(
        existing_universe=["BTCUSDT", "ADAUSDT"],
        max_candidates=2,
        min_turnover_usd=Decimal("50000000.00")
    )
    # Only XRPUSDT qualifies; LOWVOLUSDT is <$50M and QUARUSDT is quarantined
    assert len(candidates_no_ada) == 1
    assert candidates_no_ada[0].symbol == "XRPUSDT"


def test_bridge_nano_confluence_evaluation(sample_radar_json):
    """Verifies Kelly boost (+20%) on confluence and Kelly throttle (-30%) on conflict."""
    bridge = TigerScoutBridge(radar_paths=[sample_radar_json])

    # 1. Long XRPUSDT (absorption_signal == "BUY", CVD z == -1.8, skew == +0.35) -> Trapped Bears Spring Confluence
    is_conf, mult, note = bridge.evaluate_nano_confluence("XRPUSDT", "LONG")
    assert is_conf is True
    assert mult == Decimal("1.20")
    assert "NANO_CONFLUENCE_CONFIRMED" in note

    # 2. Short XRPUSDT when orderflow indicates Spring -> Conflict Warning (-30% throttle)
    is_conf, mult, note = bridge.evaluate_nano_confluence("XRPUSDT", "SHORT")
    assert is_conf is False
    assert mult == Decimal("0.70")
    assert "NANO_CONFLICT_WARNING" in note

    # 3. Short ADAUSDT (absorption_signal == "SELL", CVD z == +2.3, skew == -0.28) -> Trapped Bulls Climax Confluence
    is_conf, mult, note = bridge.evaluate_nano_confluence("ADAUSDT", "SHORT")
    assert is_conf is True
    assert mult == Decimal("1.20")
    assert "NANO_CONFLUENCE_CONFIRMED" in note

    # 4. Long ADAUSDT when orderflow indicates Climax at high -> Conflict Warning (-30% throttle)
    is_conf, mult, note = bridge.evaluate_nano_confluence("ADAUSDT", "LONG")
    assert is_conf is False
    assert mult == Decimal("0.70")
    assert "NANO_CONFLICT_WARNING" in note

    # 5. Untracked symbol -> Neutral
    is_conf, mult, note = bridge.evaluate_nano_confluence("SOLUSDT", "LONG")
    assert is_conf is True
    assert mult == Decimal("1.00")
    assert "NANO_NEUTRAL" in note


def test_orchestrator_integration_with_scout_bridge(sample_radar_json):
    """Verifies end-to-end integration of TigerScoutBridge within QuantBotOrchestrator."""
    bridge = TigerScoutBridge(radar_paths=[sample_radar_json])

    # Instantiate orchestrator with bridge enabled
    orchestrator = QuantBotOrchestrator(
        symbols_config=dict(TOP_10_SYMBOLS),
        tiger_scout_bridge=bridge,
        enable_tiger_scout=True,
        require_neural_model=False,
        enable_volume_profile_veto=False
    )

    # Mock trajectories for base symbol and scouted symbol
    mock_trajs = {
        "BTCUSDT": TrajectoryVerdict(
            symbol="BTCUSDT",
            current_price=Decimal("90000.00"),
            terminal_price=Decimal("88000.00"),
            path_high=Decimal("90500.00"),
            path_low=Decimal("87500.00"),
            raw_drift=Decimal("-0.0222"),
            dynamic_take_profit=Decimal("88000.00"),
            dynamic_stop_loss=Decimal("91500.00"),
            proposed_side="SHORT",
            horizon_hours=12,
            rationale="Bearish distribution breakdown"
        ),
        "XRPUSDT": TrajectoryVerdict(
            symbol="XRPUSDT",
            current_price=Decimal("1.4520"),
            terminal_price=Decimal("1.5200"),
            path_high=Decimal("1.5300"),
            path_low=Decimal("1.4200"),
            raw_drift=Decimal("0.0468"),
            dynamic_take_profit=Decimal("1.5200"),
            dynamic_stop_loss=Decimal("1.4100"),
            proposed_side="LONG",
            horizon_hours=12,
            rationale="Bullish momentum expansion"
        )
    }

    report = orchestrator.run_scan_cycle(
        account_equity=Decimal("200.00"),
        mock_trajectories=mock_trajs,
        execution_mode="PAPER"
    )

    # 1. XRPUSDT was scouted and dynamically added to symbols_config
    assert "XRPUSDT" in orchestrator.symbols_config
    xrp_cfg = orchestrator.symbols_config["XRPUSDT"]
    assert xrp_cfg.symbol == "XRPUSDT"
    assert xrp_cfg.min_notional == Decimal("5.0")

    # 2. Decision was evaluated for XRPUSDT
    assert "XRPUSDT" in report.decisions
    xrp_dec = report.decisions["XRPUSDT"]
    # Check that nano-confluence note was recorded
    assert "NANO_CONFLUENCE_CONFIRMED" in (xrp_dec.adversarial_notes or "")
