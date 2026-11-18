# ==============================================================================
# Kronos Quantitative Architecture — Capital Recycler Unit Tests
# File: tests/test_capital_recycler.py
# Tag: QUANT-OVERSEER | SENTINEL-ARBITER | CAPITAL-RECYCLER-TESTS
# ==============================================================================

import os
import sqlite3
import datetime
import tempfile
from decimal import Decimal
import pytest

from src.quant.capital_recycler import (
    CapitalRecycler,
    RecyclerConfig,
    RecyclerDecision,
    NormalizedPosition,
    TradeHealthEvaluation,
    RecyclerExecutionReceipt
)
from src.quant.tiger_scalper import ActiveTigerPosition
from src.quant.binance_execution import ActiveBracketPosition, PositionState


class MockBinanceClient:
    """Mock Binance execution client verifying atomic order handling."""
    def __init__(self):
        self.cancelled_orders_symbols = []
        self.market_orders = []
        self.updated_stop_losses = []

    def cancel_all_open_orders(self, symbol: str):
        self.cancelled_orders_symbols.append(symbol)

    def submit_market_order(self, symbol: str, side: str, quantity: Decimal, reduce_only: bool = True):
        self.market_orders.append({
            "symbol": symbol,
            "side": side,
            "quantity": quantity,
            "reduce_only": reduce_only
        })

    def update_stop_loss(self, symbol: str, new_stop_price: Decimal):
        self.updated_stop_losses.append({
            "symbol": symbol,
            "new_stop_price": new_stop_price
        })


import gc

@pytest.fixture
def temp_db():
    temp_dir = tempfile.mkdtemp()
    path = os.path.join(temp_dir, "test_autopsies.db")
    yield path
    gc.collect()
    try:
        if os.path.exists(path):
            os.remove(path)
        for ext in ["-wal", "-shm"]:
            if os.path.exists(path + ext):
                os.remove(path + ext)
        os.rmdir(temp_dir)
    except Exception:
        pass


@pytest.fixture
def recycler(temp_db):
    config = RecyclerConfig(database_path=temp_db)
    return CapitalRecycler(config=config)


def test_normalize_tiger_position(recycler):
    """Verify conversion from Strategy #3 ActiveTigerPosition to NormalizedPosition."""
    now = datetime.datetime.now(datetime.timezone.utc)
    tiger_pos = ActiveTigerPosition(
        position_id="TIGER_1",
        symbol="SOLUSDT",
        side="BUY",
        entry_price=Decimal("150.00"),
        take_profit=Decimal("152.00"),
        stop_loss=Decimal("148.00"),
        quantity=Decimal("10.0"),
        entry_time_utc=now,
        is_slow_regime=False,
        notional_usd=Decimal("1500.00")
    )
    norm = recycler.normalize_position(tiger_pos)
    assert norm.symbol == "SOLUSDT"
    assert norm.strategy_tag == "STRATEGY_3_TIGER"
    assert isinstance(norm.entry_price, Decimal)
    assert norm.entry_price == Decimal("150.00")


def test_normalize_bracket_position(recycler):
    """Verify conversion from Strategy #1 ActiveBracketPosition to NormalizedPosition."""
    now = datetime.datetime.now(datetime.timezone.utc)
    bracket_pos = ActiveBracketPosition(
        position_id="MACRO_1",
        symbol="BTCUSDT",
        side="BUY",
        entry_price=Decimal("90000.00"),
        stop_loss=Decimal("88000.00"),
        take_profit=Decimal("94000.00"),
        quantity=Decimal("0.1"),
        state=PositionState.BRACKETS_ACTIVE,
        entry_fill_time_utc=now
    )
    norm = recycler.normalize_position(bracket_pos)
    assert norm.symbol == "BTCUSDT"
    assert norm.strategy_tag == "STRATEGY_1_MACRO"
    assert isinstance(norm.entry_price, Decimal)
    assert norm.entry_price == Decimal("90000.00")


def test_minimum_observation_window_maintains(recycler):
    """Positions under the minimum observation window must be maintained (no jitter)."""
    now = datetime.datetime.now(datetime.timezone.utc)
    entry_t = now - datetime.timedelta(minutes=1)  # 1 min old (< 3 min scalp window)

    pos = NormalizedPosition(
        position_id="TEST_OBS",
        symbol="ETHUSDT",
        side="BUY",
        entry_price=Decimal("3000.00"),
        stop_loss=Decimal("2950.00"),
        take_profit=Decimal("3100.00"),
        quantity=Decimal("1.0"),
        entry_time_utc=entry_t,
        strategy_tag="STRATEGY_3_TIGER"
    )

    eval_res = recycler.evaluate(pos, current_price=Decimal("2998.00"), current_time_utc=now)
    assert eval_res.decision == RecyclerDecision.MAINTAIN
    assert not eval_res.should_exit
    assert "observation window" in eval_res.action_reason


def test_temporal_stall_dead_band_scalp(recycler):
    """A scalp sitting flat past max_stall_minutes (12m) must trigger MOVE_ON_STALL."""
    now = datetime.datetime.now(datetime.timezone.utc)
    entry_t = now - datetime.timedelta(minutes=13)  # 13m old (> 12m limit)

    pos = NormalizedPosition(
        position_id="TEST_STALL",
        symbol="DOGEUSDT",
        side="BUY",
        entry_price=Decimal("0.3800"),
        stop_loss=Decimal("0.3700"),
        take_profit=Decimal("0.4000"),
        quantity=Decimal("1000.0"),
        entry_time_utc=entry_t,
        strategy_tag="STRATEGY_3_TIGER"
    )

    # Flat price (+0.05% gain, inside dead band)
    current_px = Decimal("0.3802")
    eval_res = recycler.evaluate(pos, current_price=current_px, current_time_utc=now)

    assert eval_res.decision == RecyclerDecision.MOVE_ON_STALL
    assert eval_res.should_exit
    assert eval_res.health_score <= Decimal("30.00")
    assert "Temporal edge expired" in eval_res.action_reason


def test_temporal_stall_macro_swing(recycler):
    """A macro swing sitting flat past 180m (3h) must trigger MOVE_ON_STALL."""
    now = datetime.datetime.now(datetime.timezone.utc)
    entry_t = now - datetime.timedelta(minutes=185)  # 185m old (> 180m limit)

    pos = NormalizedPosition(
        position_id="TEST_MACRO_STALL",
        symbol="BTCUSDT",
        side="BUY",
        entry_price=Decimal("90000.00"),
        stop_loss=Decimal("88000.00"),
        take_profit=Decimal("94000.00"),
        quantity=Decimal("0.1"),
        entry_time_utc=entry_t,
        strategy_tag="STRATEGY_1_MACRO"
    )

    # Price slightly red (-0.11%)
    current_px = Decimal("89900.00")
    eval_res = recycler.evaluate(pos, current_price=current_px, current_time_utc=now)

    assert eval_res.decision == RecyclerDecision.MOVE_ON_STALL
    assert eval_res.should_exit
    assert "Temporal edge expired" in eval_res.action_reason


def test_cvd_inversion_kills_trade(recycler):
    """An extreme CVD delta reversal against position triggers MOVE_ON_CVD_INVERSION."""
    now = datetime.datetime.now(datetime.timezone.utc)
    entry_t = now - datetime.timedelta(minutes=5)

    pos = NormalizedPosition(
        position_id="TEST_CVD",
        symbol="AVAXUSDT",
        side="BUY",
        entry_price=Decimal("35.00"),
        stop_loss=Decimal("34.00"),
        take_profit=Decimal("37.00"),
        quantity=Decimal("10.0"),
        entry_time_utc=entry_t,
        strategy_tag="STRATEGY_3_TIGER"
    )

    # Extreme negative CVD (aggressive selling absorbing bids)
    eval_res = recycler.evaluate(
        pos,
        current_price=Decimal("34.98"),
        current_time_utc=now,
        cvd_zscore=Decimal("-2.8")
    )

    assert eval_res.decision == RecyclerDecision.MOVE_ON_CVD_INVERSION
    assert eval_res.should_exit
    assert "CVD delta inverted" in eval_res.action_reason


def test_relative_beta_weakness(recycler):
    """If BTC is surging green but the asset is drifting red, trigger MOVE_ON_BETA_WEAKNESS."""
    now = datetime.datetime.now(datetime.timezone.utc)
    entry_t = now - datetime.timedelta(minutes=6)

    pos = NormalizedPosition(
        position_id="TEST_BETA",
        symbol="ADAUSDT",
        side="BUY",
        entry_price=Decimal("0.8000"),
        stop_loss=Decimal("0.7800"),
        take_profit=Decimal("0.8400"),
        quantity=Decimal("500.0"),
        entry_time_utc=entry_t,
        strategy_tag="STRATEGY_3_TIGER"
    )

    # Asset is down -0.625% while BTC is up +0.50% (Relative lag: 1.125% > 0.80% threshold)
    current_px = Decimal("0.7950")
    eval_res = recycler.evaluate(
        pos,
        current_price=current_px,
        current_time_utc=now,
        btc_price_change_pct=Decimal("0.0050")
    )

    assert eval_res.decision == RecyclerDecision.MOVE_ON_BETA_WEAKNESS
    assert eval_res.should_exit
    assert "Relative beta breakdown" in eval_res.action_reason


def test_plateau_breakeven_ratchet_protection(recycler):
    """MFE reached +0.80% and plateaued for 6 minutes -> triggers RATCHET_PROTECT to entry + fee buffer."""
    now = datetime.datetime.now(datetime.timezone.utc)
    entry_t = now - datetime.timedelta(minutes=10)
    peak_t = now - datetime.timedelta(minutes=6)  # Peaked 6 min ago (> 5 min plateau trigger)

    pos = NormalizedPosition(
        position_id="TEST_RATCHET",
        symbol="LINKUSDT",
        side="BUY",
        entry_price=Decimal("15.00"),
        stop_loss=Decimal("14.70"),
        take_profit=Decimal("15.50"),
        quantity=Decimal("20.0"),
        entry_time_utc=entry_t,
        strategy_tag="STRATEGY_3_TIGER",
        highest_favorable_price=Decimal("15.12"),  # +0.80% gain
        last_peak_time_utc=peak_t,
        is_breakeven_ratcheted=False
    )

    # Price has pulled back slightly to 15.08 (+0.53%)
    current_px = Decimal("15.08")
    eval_res = recycler.evaluate(pos, current_price=current_px, current_time_utc=now)

    assert eval_res.decision == RecyclerDecision.RATCHET_PROTECT
    assert not eval_res.should_exit
    assert eval_res.should_ratchet
    expected_new_sl = Decimal("15.00") * (Decimal("1.0") + Decimal("0.0012"))
    assert eval_res.recommended_new_sl == expected_new_sl
    assert eval_res.recommended_new_sl > pos.entry_price


def test_opportunity_displacement_liberation(recycler):
    """A sluggish trade is displaced when top scanner candidate is waiting to enter."""
    now = datetime.datetime.now(datetime.timezone.utc)
    entry_t = now - datetime.timedelta(minutes=8)  # 8m old (> 60% of 12m)

    pos = NormalizedPosition(
        position_id="TEST_DISPLACE",
        symbol="NEARUSDT",
        side="BUY",
        entry_price=Decimal("6.500"),
        stop_loss=Decimal("6.350"),
        take_profit=Decimal("6.800"),
        quantity=Decimal("50.0"),
        entry_time_utc=entry_t,
        strategy_tag="STRATEGY_3_TIGER"
    )

    class MockCandidate:
        symbol = "JTOUSDT"
        volatility_score = Decimal("0.045")

    # Current price barely up +0.03%
    current_px = Decimal("6.502")
    eval_res = recycler.evaluate(
        pos,
        current_price=current_px,
        current_time_utc=now,
        scanner_candidates=[MockCandidate()]
    )

    assert eval_res.decision == RecyclerDecision.MOVE_ON_DISPLACEMENT
    assert eval_res.should_exit
    assert eval_res.displaced_by_candidate == "JTOUSDT"
    assert "Displaced by higher-conviction asset JTOUSDT" in eval_res.action_reason


def test_emergency_tsunami_kill(recycler):
    """Tsunami shock immediately commands emergency liquidation."""
    now = datetime.datetime.now(datetime.timezone.utc)
    entry_t = now - datetime.timedelta(minutes=4)

    pos = NormalizedPosition(
        position_id="TEST_TSUNAMI",
        symbol="BTCUSDT",
        side="BUY",
        entry_price=Decimal("90000.00"),
        stop_loss=Decimal("88000.00"),
        take_profit=Decimal("94000.00"),
        quantity=Decimal("0.1"),
        entry_time_utc=entry_t,
        strategy_tag="STRATEGY_1_MACRO"
    )

    eval_res = recycler.evaluate(
        pos,
        current_price=Decimal("89800.00"),
        current_time_utc=now,
        is_tsunami_shock=True
    )

    assert eval_res.decision == RecyclerDecision.EMERGENCY_KILL
    assert eval_res.should_exit
    assert eval_res.health_score == Decimal("0.00")


def test_zero_orphan_execution_flow(recycler):
    """Verify that execute_move_on cancels orders, executes market exit, sets quarantine, and logs autopsy."""
    mock_client = MockBinanceClient()
    liberated_events = []

    def on_liberate(pos_id, sym):
        liberated_events.append((pos_id, sym))

    now = datetime.datetime.now(datetime.timezone.utc)
    pos = NormalizedPosition(
        position_id="TEST_EXEC_1",
        symbol="SUIUSDT",
        side="BUY",
        entry_price=Decimal("3.200"),
        stop_loss=Decimal("3.100"),
        take_profit=Decimal("3.400"),
        quantity=Decimal("100.0"),
        entry_time_utc=now - datetime.timedelta(minutes=15),
        strategy_tag="STRATEGY_3_TIGER"
    )

    eval_res = TradeHealthEvaluation(
        symbol="SUIUSDT",
        position_id="TEST_EXEC_1",
        decision=RecyclerDecision.MOVE_ON_STALL,
        health_score=Decimal("20.00"),
        current_pnl_pct=Decimal("0.0005"),
        mfe_pct=Decimal("0.0010"),
        mae_pct=Decimal("0.0005"),
        elapsed_minutes=Decimal("15.0"),
        plateau_minutes=Decimal("12.0"),
        action_reason="Stalled dead momentum",
        should_exit=True,
        should_ratchet=False
    )

    receipt = recycler.execute_move_on(
        pos,
        eval_res,
        current_price=Decimal("3.2016"),
        current_time_utc=now,
        binance_client=mock_client,
        on_slot_liberated=on_liberate
    )

    # 1. Zero-Orphan Guarantee: Resting conditional orders cancelled first
    assert "SUIUSDT" in mock_client.cancelled_orders_symbols

    # 2. Market close submitted
    assert len(mock_client.market_orders) == 1
    assert mock_client.market_orders[0]["symbol"] == "SUIUSDT"
    assert mock_client.market_orders[0]["side"] == "SELL"
    assert mock_client.market_orders[0]["reduce_only"] is True

    # 3. Quarantine registered
    assert recycler.is_symbol_in_quarantine("SUIUSDT", now)

    # 4. Slot liberation callback fired
    assert len(liberated_events) == 1
    assert liberated_events[0] == ("TEST_EXEC_1", "SUIUSDT")

    # 5. Autopsy logged in SQLite
    with sqlite3.connect(recycler.config.database_path) as conn:
        rows = conn.execute("SELECT position_id, symbol, decision FROM sentinel_autopsies").fetchall()
        assert len(rows) == 1
        assert rows[0][0] == "TEST_EXEC_1"
        assert rows[0][1] == "SUIUSDT"
        assert rows[0][2] == "MOVE_ON_STALL"


def test_zero_float_math_invariants(recycler):
    """Confirm zero float math across all internal calculations."""
    now = datetime.datetime.now(datetime.timezone.utc)
    pos = NormalizedPosition(
        position_id="TEST_FLOAT_CHECK",
        symbol="SOLUSDT",
        side="BUY",
        entry_price=Decimal("150.00"),
        stop_loss=Decimal("147.00"),
        take_profit=Decimal("155.00"),
        quantity=Decimal("5.0"),
        entry_time_utc=now - datetime.timedelta(minutes=5),
        strategy_tag="STRATEGY_3_TIGER"
    )

    eval_res = recycler.evaluate(pos, current_price=Decimal("151.20"), current_time_utc=now)

    assert isinstance(eval_res.current_pnl_pct, Decimal)
    assert isinstance(eval_res.mfe_pct, Decimal)
    assert isinstance(eval_res.mae_pct, Decimal)
    assert isinstance(eval_res.health_score, Decimal)
    assert isinstance(eval_res.elapsed_minutes, Decimal)
