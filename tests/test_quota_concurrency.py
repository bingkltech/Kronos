"""
tests/test_quota_concurrency.py — Validation of 50-Trade Quota & 3-Concurrent Position Allocation (2 Macro + 1 Scalp).

Invariants Verified:
1. Live Trade Quota Cap (50 trades default): Increments on dispatch and auto-pauses when reaching quota.
2. Max 3 Concurrent Positions: Total active positions cannot exceed 3 across Macro + Scalp.
3. Dedicated Strategy Allocation:
   - Macro Book: Strictly capped at 2 active positions.
   - Scalp Lane: Strictly capped at 1 active position.
4. QuotaNotifier: Lifecycle state persistence, trades remaining tracking, auto-pause trigger, and email notification logging.
"""

import os
import json
import pytest
from decimal import Decimal
from unittest.mock import MagicMock, patch

from src.quant.config import ALL_SUPPORTED_SYMBOLS, DEFAULT_RISK_CONFIG
from src.quant.binance_execution import PositionState, TradeTicket, ActiveBracketPosition, BinanceAtomicExecutor
from src.quant.apex_scalper import ApexScalperEngine
from src.quant.storm_protocol import StormProtocolManager
from src.quant.quota_notifier import QuotaNotifier


def test_quota_increment_and_auto_pause(tmp_path):
    """Verify that dispatching trades increments session count and automatically pauses at 50."""
    quota_file = str(tmp_path / "test_trade_quota.json")
    
    # State tracking simulation matching headless_worker logic
    live_trading_enabled = True
    live_trade_cap = 50
    live_session_trades = 0
    live_cap_reached = False

    def record_dispatch(symbol: str, source: str):
        nonlocal live_session_trades, live_trading_enabled, live_cap_reached
        live_session_trades += 1
        if live_trade_cap is not None and live_session_trades >= live_trade_cap:
            live_trading_enabled = False
            live_cap_reached = True

    # Simulate 49 trades
    for i in range(49):
        record_dispatch(f"SYM{i}", "MACRO" if i % 2 == 0 else "SCALP")
        assert live_trading_enabled is True
        assert live_session_trades == i + 1

    # 50th trade reaches quota
    record_dispatch("SYM50", "MACRO")
    assert live_session_trades == 50
    assert live_trading_enabled is False
    assert live_cap_reached is True


def test_portfolio_concurrency_cap_and_strategy_allocation():
    """
    Verify portfolio concurrency clamp (3 positions total) and dedicated allocation:
    - 2 Macro maximum
    - 1 Scalp maximum
    Total portfolio: max 3 positions at any given time.
    """
    max_portfolio_positions = 3
    max_macro_positions = 2
    max_scalp_positions = 1

    # Scenario A: 0 positions -> Both Macro and Scalp permitted
    active_positions = []
    scalp_active_symbols = set()
    macro_positions = [p for p in active_positions if p["symbol"] not in scalp_active_symbols]
    scalp_positions = [p for p in active_positions if p["symbol"] in scalp_active_symbols]

    can_macro_A = len(active_positions) < max_portfolio_positions and len(macro_positions) < max_macro_positions
    can_scalp_A = len(active_positions) < max_portfolio_positions and len(scalp_positions) < max_scalp_positions
    assert can_macro_A is True
    assert can_scalp_A is True

    # Scenario B: 1 Macro active -> Macro PERMITTED (1/2), Scalp PERMITTED (0/1)
    active_positions = [{"symbol": "BTCUSDT"}]
    scalp_active_symbols = set()  # BTC is macro
    macro_positions = [p for p in active_positions if p["symbol"] not in scalp_active_symbols]
    scalp_positions = [p for p in active_positions if p["symbol"] in scalp_active_symbols]

    can_macro_B = len(active_positions) < max_portfolio_positions and len(macro_positions) < max_macro_positions
    can_scalp_B = len(active_positions) < max_portfolio_positions and len(scalp_positions) < max_scalp_positions
    assert can_macro_B is True, "Second macro trade must be permitted (1/2 active)"
    assert can_scalp_B is True, "Scalp trade must be permitted (0/1 active, total 1/3)"

    # Scenario C: 2 Macro active -> Macro BLOCKED (2/2), Scalp PERMITTED (0/1, total 2/3)
    active_positions = [{"symbol": "BTCUSDT"}, {"symbol": "ETHUSDT"}]
    scalp_active_symbols = set()
    macro_positions = [p for p in active_positions if p["symbol"] not in scalp_active_symbols]
    scalp_positions = [p for p in active_positions if p["symbol"] in scalp_active_symbols]

    can_macro_C = len(active_positions) < max_portfolio_positions and len(macro_positions) < max_macro_positions
    can_scalp_C = len(active_positions) < max_portfolio_positions and len(scalp_positions) < max_scalp_positions
    assert can_macro_C is False, "Third macro trade must be blocked (2/2 macro slots full)"
    assert can_scalp_C is True, "Scalp trade must be permitted when 2 macros are open (total 2/3 < 3)"

    # Scenario D: 2 Macro + 1 Scalp active (3 total) -> BOTH BLOCKED (Portfolio Full at 3/3)
    active_positions = [{"symbol": "BTCUSDT"}, {"symbol": "ETHUSDT"}, {"symbol": "SOLUSDT"}]
    scalp_active_symbols = {"SOLUSDT"}
    macro_positions = [p for p in active_positions if p["symbol"] not in scalp_active_symbols]
    scalp_positions = [p for p in active_positions if p["symbol"] in scalp_active_symbols]

    can_macro_D = len(active_positions) < max_portfolio_positions and len(macro_positions) < max_macro_positions
    can_scalp_D = len(active_positions) < max_portfolio_positions and len(scalp_positions) < max_scalp_positions
    assert can_macro_D is False, "Macro blocked at 3/3 portfolio positions"
    assert can_scalp_D is False, "Scalp blocked at 3/3 portfolio positions"

    # Scenario E: 1 Macro + 1 Scalp active (2 total) -> Macro PERMITTED (1/2), Scalp BLOCKED (1/1)
    active_positions = [{"symbol": "BTCUSDT"}, {"symbol": "SOLUSDT"}]
    scalp_active_symbols = {"SOLUSDT"}
    macro_positions = [p for p in active_positions if p["symbol"] not in scalp_active_symbols]
    scalp_positions = [p for p in active_positions if p["symbol"] in scalp_active_symbols]

    can_macro_E = len(active_positions) < max_portfolio_positions and len(macro_positions) < max_macro_positions
    can_scalp_E = len(active_positions) < max_portfolio_positions and len(scalp_positions) < max_scalp_positions
    assert can_macro_E is True, "Macro permitted when only 1 macro is open and total is 2/3"
    assert can_scalp_E is False, "Second scalp trade must be blocked (1/1 scalp slot full)"

    # Scenario F: 0 Macro + 1 Scalp active (1 total) -> Macro PERMITTED (0/2), Scalp BLOCKED (1/1)
    active_positions = [{"symbol": "SOLUSDT"}]
    scalp_active_symbols = {"SOLUSDT"}
    macro_positions = [p for p in active_positions if p["symbol"] not in scalp_active_symbols]
    scalp_positions = [p for p in active_positions if p["symbol"] in scalp_active_symbols]

    can_macro_F = len(active_positions) < max_portfolio_positions and len(macro_positions) < max_macro_positions
    can_scalp_F = len(active_positions) < max_portfolio_positions and len(scalp_positions) < max_scalp_positions
    assert can_macro_F is True, "Macro permitted when 0 macros are open"
    assert can_scalp_F is False, "Second scalp trade must be blocked"


def test_storm_protocol_manager_allocation_limits():
    """Verify StormProtocolManager respects normal_macro_cap=2 and normal_scalp_cap=1 (3 total max)."""
    storm_mgr = StormProtocolManager(normal_macro_cap=2, normal_scalp_cap=1)

    # 0 macro, 0 scalp -> Both permitted
    p_macro, _ = storm_mgr.is_entry_permitted(is_scalp=False, current_macro_count=0, current_scalp_count=0, confidence_pct=80.0)
    p_scalp, _ = storm_mgr.is_entry_permitted(is_scalp=True, current_macro_count=0, current_scalp_count=0, confidence_pct=80.0)
    assert p_macro is True
    assert p_scalp is True

    # 1 macro, 0 scalp -> Macro permitted (1/2), Scalp permitted (0/1)
    p_macro, _ = storm_mgr.is_entry_permitted(is_scalp=False, current_macro_count=1, current_scalp_count=0, confidence_pct=80.0)
    p_scalp, _ = storm_mgr.is_entry_permitted(is_scalp=True, current_macro_count=1, current_scalp_count=0, confidence_pct=80.0)
    assert p_macro is True
    assert p_scalp is True

    # 2 macro, 0 scalp -> Macro full (2/2), Scalp permitted (0/1)
    p_macro, reason_m = storm_mgr.is_entry_permitted(is_scalp=False, current_macro_count=2, current_scalp_count=0, confidence_pct=80.0)
    p_scalp, reason_s = storm_mgr.is_entry_permitted(is_scalp=True, current_macro_count=2, current_scalp_count=0, confidence_pct=80.0)
    assert p_macro is False
    assert "Macro capacity full (2/2)" in reason_m
    assert p_scalp is True

    # 2 macro, 1 scalp -> Both full
    p_macro, reason_m = storm_mgr.is_entry_permitted(is_scalp=False, current_macro_count=2, current_scalp_count=1, confidence_pct=80.0)
    p_scalp, reason_s = storm_mgr.is_entry_permitted(is_scalp=True, current_macro_count=2, current_scalp_count=1, confidence_pct=80.0)
    assert p_macro is False
    assert p_scalp is False
    assert "Scalp slot full" in reason_s or "Scalp capacity full" in reason_s

    # 0 macro, 1 scalp -> Macro permitted, Scalp full
    p_macro, reason_m = storm_mgr.is_entry_permitted(is_scalp=False, current_macro_count=0, current_scalp_count=1, confidence_pct=80.0)
    p_scalp, reason_s = storm_mgr.is_entry_permitted(is_scalp=True, current_macro_count=0, current_scalp_count=1, confidence_pct=80.0)
    assert p_macro is True
    assert p_scalp is False
    assert "Scalp slot full" in reason_s or "Scalp capacity full" in reason_s


def test_quota_notifier_lifecycle_and_audit(tmp_path):
    """Verify QuotaNotifier full lifecycle: state persistence, counter increment, auto-pause at cap, and reset."""
    quota_file = str(tmp_path / "aws_trade_quota.json")
    notifier = QuotaNotifier(quota_path=quota_file)
    notifier.trade_cap = 5
    notifier.session_trades = 0
    notifier.macro_trades = 0
    notifier.scalp_trades = 0
    notifier.is_active = True
    notifier.save_state()

    assert notifier.has_quota_remaining is True
    assert notifier.trades_remaining == 5

    # Dispatch 2 macro + 2 scalp trades = 4 total
    notifier.record_dispatch("BTCUSDT", "MACRO")
    notifier.record_dispatch("ETHUSDT", "MACRO")
    notifier.record_dispatch("PEPEUSDT", "SCALP")
    active, just_reached = notifier.record_dispatch("DOGEUSDT", "SCALP")

    assert active is True
    assert just_reached is False
    assert notifier.session_trades == 4
    assert notifier.macro_trades == 2
    assert notifier.scalp_trades == 2
    assert notifier.trades_remaining == 1
    assert notifier.has_quota_remaining is True

    # 5th trade hits cap
    active_5, just_reached_5 = notifier.record_dispatch("SOLUSDT", "MACRO")
    assert active_5 is False
    assert just_reached_5 is True
    assert notifier.session_trades == 5
    assert notifier.macro_trades == 3
    assert notifier.trades_remaining == 0
    assert notifier.has_quota_remaining is False
    assert notifier.is_active is False
    assert notifier.cap_reached_utc is not None

    # Verify reloading from disk preserves reached state
    reloaded = QuotaNotifier(quota_path=quota_file)
    assert reloaded.session_trades == 5
    assert reloaded.macro_trades == 3
    assert reloaded.scalp_trades == 2
    assert reloaded.is_active is False
    assert reloaded.trades_remaining == 0

    # Reset quota
    reloaded.reset_quota(new_cap=50)
    assert reloaded.session_trades == 0
    assert reloaded.macro_trades == 0
    assert reloaded.scalp_trades == 0
    assert reloaded.trade_cap == 50
    assert reloaded.is_active is True
    assert reloaded.trades_remaining == 50
    assert reloaded.has_quota_remaining is True



def test_scalp_expiration_sweetspots():
    """Verify Scalper stagnation ejection and 15m maximum hard expiry."""
    import datetime
    from src.quant.apex_scalper import ActiveScalpState

    engine = ApexScalperEngine(max_duration_seconds=900)
    assert engine.max_duration_seconds == 900

    now_utc = datetime.datetime(2026, 11, 19, 8, 0, 0, tzinfo=datetime.timezone.utc)
    engine.active_scalp = ActiveScalpState(
        position_id="TEST-1",
        symbol="BTCUSDT",
        side="BUY",
        entry_price=Decimal("100.00"),
        take_profit=Decimal("102.00"),
        stop_loss=Decimal("98.50"),
        quantity=Decimal("1.0"),
        notional_usd=Decimal("100.00"),
        entry_time_utc=now_utc,
        max_duration_seconds=900,
        highest_favorable_price=Decimal("100.10"),  # Only +0.10% MFE (dead band)
        lowest_adverse_price=Decimal("99.90")
    )

    # 1. At 5 minutes: duration < 8m stagnation cutoff -> should NOT trigger stagnation
    t_5m = now_utc + datetime.timedelta(minutes=5)
    stalled, _ = engine.evaluate_stagnation(t_5m, stagnation_seconds=480, min_mfe_pct=Decimal("0.25"))
    assert stalled is False

    # 2. At 9 minutes with +0.10% MFE (below +0.25% required): -> triggers STAGNATION_DEAD_BAND
    t_9m = now_utc + datetime.timedelta(minutes=9)
    stalled, reason = engine.evaluate_stagnation(t_9m, stagnation_seconds=480, min_mfe_pct=Decimal("0.25"))
    assert stalled is True
    assert "STAGNATION_DEAD_BAND" in reason

    # 3. If MFE was +0.40% (alive and expanding), at 9m it should NOT be flagged as stalled
    engine.active_scalp = ActiveScalpState(
        position_id="TEST-1",
        symbol="BTCUSDT",
        side="BUY",
        entry_price=Decimal("100.00"),
        take_profit=Decimal("102.00"),
        stop_loss=Decimal("98.50"),
        quantity=Decimal("1.0"),
        notional_usd=Decimal("100.00"),
        entry_time_utc=now_utc,
        max_duration_seconds=900,
        highest_favorable_price=Decimal("100.40"),  # +0.40% MFE
        lowest_adverse_price=Decimal("99.90")
    )
    stalled, _ = engine.evaluate_stagnation(t_9m, stagnation_seconds=480, min_mfe_pct=Decimal("0.25"))
    assert stalled is False


def test_capital_recycler_and_risk_config_sweetspots():
    """Verify Capital Recycler and GlobalRiskConfig sweetspot values."""
    from src.quant.capital_recycler import RecyclerConfig
    from src.quant.config import DEFAULT_RISK_CONFIG

    rc = RecyclerConfig()
    assert rc.max_stall_minutes_scalp == Decimal("8.0")
    assert rc.max_stall_minutes_macro == Decimal("90.0")
    assert rc.plateau_ratchet_minutes_scalp == Decimal("4.0")
    assert rc.plateau_ratchet_minutes_macro == Decimal("30.0")

    assert DEFAULT_RISK_CONFIG.stale_trade_hours == 4


def test_quota_and_pause_settings_persistence(tmp_path):
    """Verify that pausing the bot and configuring custom settings persists across reloads/reboots."""
    quota_file = str(tmp_path / "aws_trade_quota.json")

    # 1. Initialize with custom settings
    notifier = QuotaNotifier(quota_path=quota_file)
    notifier.trade_cap = 15
    notifier.session_trades = 3
    notifier.is_active = False  # User manually paused the bot

    # Initial save
    notifier.save_state()

    # Verify custom keys are preserved in json
    with open(quota_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert data["live_trading_enabled"] is False
    assert data["live_trade_cap"] == 15
    assert data["live_session_trades"] == 3

    # Manually simulate additional headless worker keys stored in quota file
    data["sole_live_engine"] = "NEON_V1"
    data["scan_interval_sec"] = 45
    data["contra_mode"] = True
    with open(quota_file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

    # 2. Re-instantiate QuotaNotifier (simulate server reboot / restart)
    reloaded = QuotaNotifier(quota_path=quota_file)
    assert reloaded.is_active is False  # MUST REMAIN PAUSED!
    assert reloaded.trade_cap == 15
    assert reloaded.session_trades == 3
    assert reloaded.trades_remaining == 12

    # 3. Subsequent save_state from QuotaNotifier must NOT wipe out existing custom keys
    reloaded.save_state()
    with open(quota_file, "r", encoding="utf-8") as f:
        re_saved = json.load(f)
    assert re_saved["live_trading_enabled"] is False
    assert re_saved["sole_live_engine"] == "NEON_V1"
    assert re_saved["scan_interval_sec"] == 45
    assert re_saved["contra_mode"] is True


