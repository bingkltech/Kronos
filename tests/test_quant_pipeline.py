"""
tests/test_quant_pipeline.py — Full End-to-End ASVL Integration Test Suite.

Validates the complete multi-agent quantitative pipeline:
1. Orchestrator executes scan cycle across Top 10 universe.
2. News blackout gate prevents trade dispatch during economic risk.
3. Systemic Bull Expansion approves candidate and sizes via Decimal Kelly risk budget.
4. Binance execution gateway submits atomic bracket orders.
5. 12-hour temporal exit sweep flattens stale active positions.
6. Invariant 1: Zero Float Financial Math (100% Decimal fidelity).
"""

import os
import sys
import datetime
from decimal import Decimal
import pytest

WORKSPACE_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if WORKSPACE_ROOT not in sys.path:
    sys.path.insert(0, WORKSPACE_ROOT)

from src.quant.orchestrator import QuantBotOrchestrator, CycleReport
from src.quant.macro_specialists import NewsCatalystSpecialist, CryptoCarrySpecialist
from src.quant.crypto_index_engine import CryptoIndexEngine
from src.quant.kronos_onnx_engine import KronosTrajectoryEngine, TrajectoryVerdict
from src.quant.kev_risk_arbiter import KEVSupremeArbiter
from src.quant.learning_governor import LearningGovernor
from src.quant.binance_execution import BinanceAtomicExecutor, PositionState
from src.quant.config import TOP_10_SYMBOLS


def _build_test_orchestrator(db_name="_test_pipeline.db"):
    """Assemble an orchestrator instance configured for deterministic testing."""
    db_path = os.path.join(WORKSPACE_ROOT, "data", db_name)
    if os.path.exists(db_path):
        os.remove(db_path)

    news = NewsCatalystSpecialist(blackout_window_minutes=30)
    index = CryptoIndexEngine()
    carry = CryptoCarrySpecialist()
    traj = KronosTrajectoryEngine()
    risk = KEVSupremeArbiter()
    learning = LearningGovernor(db_path=db_path)
    executor = BinanceAtomicExecutor(dry_run=True)

    orch = QuantBotOrchestrator(
        news_specialist=news,
        index_engine=index,
        carry_specialist=carry,
        trajectory_engine=traj,
        risk_arbiter=risk,
        learning_governor=learning,
        executor=executor
    )
    return orch, db_path


def test_end_to_end_scan_and_execution_cycle():
    """Verify full quantitative scan cycle from macro screening to atomic execution."""
    orch, db_path = _build_test_orchestrator("_test_pipeline_e2e.db")

    try:
        # 1. Setup Mock Universe with 70% Bull Expansion (7 of 10 above VWAP)
        mock_klines = {}
        symbols = list(TOP_10_SYMBOLS.keys())
        for i, sym in enumerate(symbols):
            if i < 7:
                mock_klines[sym] = [
                    {"open": Decimal("100"), "high": Decimal("110"), "low": Decimal("99"), "close": Decimal("108"), "volume": Decimal("10"), "quote_volume": Decimal("1000")}
                ]
            else:
                mock_klines[sym] = [
                    {"open": Decimal("100"), "high": Decimal("102"), "low": Decimal("90"), "close": Decimal("91"), "volume": Decimal("10"), "quote_volume": Decimal("1000")}
                ]

        # 2. Setup Mock Trajectories:
        # ETHUSDT: Strong Bullish Drift (+2.40% > 0.50% fee hurdle, RR=1.71 >= 1.50)
        # BTCUSDT: Weak Drift (+0.30% < 0.50% fee hurdle -> will be vetoed by Gate 3)
        mock_trajectories = {
            "ETHUSDT": TrajectoryVerdict(
                symbol="ETHUSDT",
                current_price=Decimal("2500.00"),
                terminal_price=Decimal("2560.00"),
                path_high=Decimal("2560.00"),
                path_low=Decimal("2465.00"),
                raw_drift=Decimal("0.0240"),
                dynamic_take_profit=Decimal("2560.00"),
                dynamic_stop_loss=Decimal("2465.00"),
                proposed_side="LONG",
                horizon_hours=12,
                rationale="Strong bullish setup"
            ),
            "BTCUSDT": TrajectoryVerdict(
                symbol="BTCUSDT",
                current_price=Decimal("67000.00"),
                terminal_price=Decimal("67200.00"),
                path_high=Decimal("67250.00"),
                path_low=Decimal("66800.00"),
                raw_drift=Decimal("0.0030"),
                dynamic_take_profit=Decimal("67250.00"),
                dynamic_stop_loss=Decimal("66800.00"),
                proposed_side="LONG",
                horizon_hours=12,
                rationale="Weak drift"
            )
        }

        # 3. Run Hourly Scan Cycle with $10,000 Equity
        cycle_time = datetime.datetime(2026, 10, 28, 12, 0, tzinfo=datetime.timezone.utc)
        report: CycleReport = orch.run_scan_cycle(
            account_equity=Decimal("10000.00"),
            current_time_utc=cycle_time,
            mock_preloaded_klines=mock_klines,
            mock_trajectories=mock_trajectories
        )

        # 4. Verify Macro Screening
        assert report.macro_verdict.macro_regime == "BULL_EXPANSION"
        assert report.macro_verdict.breadth_ratio == Decimal("0.7")
        assert not report.news_verdict.is_blackout

        # 5. Verify KEV Decisions
        # BTC must be vetoed due to fee hurdle failure
        assert "BTCUSDT" in report.decisions
        btc_decision = report.decisions["BTCUSDT"]
        assert not btc_decision.approved
        assert btc_decision.veto_gate_failed == "GATE_3_FEE_HURDLE"

        # ETH must be approved
        assert "ETHUSDT" in report.decisions
        eth_decision = report.decisions["ETHUSDT"]
        assert eth_decision.approved
        assert eth_decision.ticket is not None
        assert eth_decision.ticket.quantity == Decimal("4.285")
        assert eth_decision.ticket.risk_budget_usd == Decimal("150.00")

        # 6. Verify Atomic Execution Dispatch
        assert len(report.dispatched_trades) == 1
        pos = report.dispatched_trades[0]
        assert pos.symbol == "ETHUSDT"
        assert pos.state == PositionState.BRACKETS_ACTIVE
        assert pos.sl_order_id is not None
        assert pos.tp_order_id is not None

        # 7. Verify 12-Hour Temporal Expiry Sweep
        # Case A: 4 hours later -> Still active
        expired_4h = orch.sweep_temporal_exits(current_time_utc=cycle_time + datetime.timedelta(hours=4))
        assert len(expired_4h) == 0
        assert pos.state == PositionState.BRACKETS_ACTIVE

        # Case B: 12.5 hours later -> Closed as stale
        expired_12h = orch.sweep_temporal_exits(current_time_utc=cycle_time + datetime.timedelta(hours=12, minutes=30))
        assert len(expired_12h) == 1
        assert pos.state == PositionState.CLOSED
        assert pos.close_reason == "TEMPORAL_EXIT_12H_STALE"

    finally:
        if os.path.exists(db_path):
            os.remove(db_path)


def test_news_blackout_halts_cycle():
    """Verify that active macroeconomic risk freezes trade dispatch."""
    orch, db_path = _build_test_orchestrator("_test_pipeline_blackout.db")
    try:
        # Register FOMC rate decision
        fomc_time = datetime.datetime(2026, 10, 28, 18, 0, tzinfo=datetime.timezone.utc)
        orch.news_specialist.register_event(fomc_time, "FOMC Decision")

        # Scan 10 minutes before FOMC
        eval_time = fomc_time - datetime.timedelta(minutes=10)
        report = orch.run_scan_cycle(
            account_equity=Decimal("10000.00"),
            current_time_utc=eval_time
        )

        assert report.news_verdict.is_blackout
        assert len(report.dispatched_trades) == 0
        assert len(report.decisions) == 0
    finally:
        if os.path.exists(db_path):
            os.remove(db_path)
