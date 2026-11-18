import datetime
from decimal import Decimal
import pandas as pd
import pytest

from src.quant.orchestrator import QuantBotOrchestrator, LIVE_EXCLUDED_SYMBOLS
from src.quant.kronos_onnx_engine import TrajectoryVerdict

def test_directional_flip_hysteresis():
    """Verify that a symbol that suffered a loss on SELL cannot flip to BUY within 30m."""
    bot = QuantBotOrchestrator()
    # Pick a time outside of US open / late night funding window (e.g. 10:00 UTC European Prime session)
    t_exit = datetime.datetime(2026, 11, 16, 10, 0, tzinfo=datetime.timezone.utc)
    bot.record_directional_loss("ETHUSDT", "SELL", t_exit)

    # 1. 10 minutes later: proposed LONG (BUY) -> Vetoed by Hysteresis
    t_scan_10m = t_exit + datetime.timedelta(minutes=10)
    mock_traj_bullish = {
        "ETHUSDT": TrajectoryVerdict(
            symbol="ETHUSDT",
            current_price=Decimal("1830.00"),
            terminal_price=Decimal("1850.00"),
            path_high=Decimal("1855.00"),
            path_low=Decimal("1825.00"),
            raw_drift=Decimal("0.0109"),
            dynamic_take_profit=Decimal("1850.00"),
            dynamic_stop_loss=Decimal("1815.00"),
            proposed_side="LONG",
            horizon_hours=12,
            rationale="Test Bullish Drift"
        )
    }

    report = bot.run_scan_cycle(
        account_equity=Decimal("200.00"),
        current_time_utc=t_scan_10m,
        mock_trajectories=mock_traj_bullish,
        execution_mode="PAPER"
    )

    eth_dec = report.decisions.get("ETHUSDT")
    assert eth_dec is not None
    assert eth_dec.approved is False
    assert eth_dec.veto_gate_failed == "DIRECTIONAL_FLIP_HYSTERESIS"
    assert "Directional flip" in eth_dec.veto_reason

    # 2. 35 minutes later: proposed LONG (BUY) -> Cooldown expired, permitted
    t_scan_35m = t_exit + datetime.timedelta(minutes=35)
    report_35m = bot.run_scan_cycle(
        account_equity=Decimal("200.00"),
        current_time_utc=t_scan_35m,
        mock_trajectories=mock_traj_bullish,
        execution_mode="PAPER"
    )
    eth_dec_35m = report_35m.decisions.get("ETHUSDT")
    assert eth_dec_35m is not None
    assert eth_dec_35m.veto_gate_failed != "DIRECTIONAL_FLIP_HYSTERESIS"


def test_neural_model_fail_safe_gate():
    """Verify that in LIVE mode, if neural model is reported unloaded, candidate is vetoed."""
    bot = QuantBotOrchestrator()
    # Mock trajectory_engine to report model unloaded
    bot.trajectory_engine.is_neural_model_loaded = lambda: False

    t_now = datetime.datetime(2026, 11, 16, 10, 0, tzinfo=datetime.timezone.utc)
    report = bot.run_scan_cycle(
        account_equity=Decimal("200.00"),
        current_time_utc=t_now,
        execution_mode="LIVE"
    )

    active_non_pruned = [sym for sym in report.decisions.keys() if sym not in LIVE_EXCLUDED_SYMBOLS]
    assert len(active_non_pruned) > 0
    for sym in active_non_pruned:
        dec = report.decisions[sym]
        assert dec.approved is False
        assert dec.veto_gate_failed == "NEURAL_MODEL_OFFLINE"
        assert "Kronos Foundation Neural Model is offline/unloaded" in dec.veto_reason
