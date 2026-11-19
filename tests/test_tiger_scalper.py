"""
tests/test_tiger_scalper.py — Comprehensive ASVL Verification Suite for Strategy #3 (Stalking Tiger).

Validates:
1. Zero Float Financial Math (Decimal) throughout all configs and orderflow metrics.
2. Binance Rate Limit Watchdog & Zero-Ban Bulk REST / WebSocket architecture.
3. Top 150 Volatility Sieve & Top 5 Prey isolation.
4. Footprint CVD delta absorption, Stoikov Micro-Price skew, and OFI.
5. 90-second Signal TTL (cancels stale signals).
6. The 8-12-15 Minute Temporal Decay Ladder.
7. Dual-Regime Volatility Brackets (+1.01%/-0.66% and +1.90%/-1.10%) and 5-loss circuit breaker.
"""

import datetime
from decimal import Decimal
import json
import os
import pytest
import tempfile
from typing import Any, Dict, List, Tuple

from src.quant.tiger_config import (
    TigerMasterConfig,
    TigerApiRateLimitConfig,
    TigerUniverseSieveConfig,
    TigerTemporalConfig,
    TigerOrderflowConfig,
    TigerBracketConfig,
)
from src.quant.tiger_scanner import (
    BinanceRateLimitWatchdog,
    TigerUniverseScanner,
    PreyCandidate,
)
from src.quant.tiger_orderflow import (
    SymbolOrderflowTracker,
    AggTradeEvent,
    DepthSnapshot,
    AbsorptionSignal,
)
from src.quant.tiger_scalper import (
    TigerExecutionEngine,
    PendingTigerSignal,
    ActiveTigerPosition,
)


def test_tiger_config_decimal_serialization():
    """Verify configuration serialization preserves Decimal types without float contamination."""
    cfg = TigerMasterConfig()
    d = cfg.to_dict()
    
    # Check that all decimal values were serialized as strings
    assert isinstance(d["sieve"]["min_24h_turnover_usd"], str)
    assert d["sieve"]["min_24h_turnover_usd"] == "30000000.00"
    assert d["brackets"]["slow_vol_tp_price_pct"] == "0.0101"
    assert d["brackets"]["slow_vol_sl_price_pct"] == "0.0066"
    assert d["brackets"]["consecutive_loss_pause_count"] == 5

    # Reconstruct from dict
    reconstructed = TigerMasterConfig.from_dict(d)
    assert isinstance(reconstructed.sieve.min_24h_turnover_usd, Decimal)
    assert reconstructed.sieve.min_24h_turnover_usd == Decimal("30000000.00")
    assert reconstructed.brackets.slow_vol_tp_price_pct == Decimal("0.0101")
    assert reconstructed.brackets.slow_vol_sl_price_pct == Decimal("0.0066")
    assert reconstructed.brackets.max_sl_roi_pct == Decimal("5.5")


def test_binance_rate_limit_watchdog():
    """Verify the rate limit watchdog adapts polling cadence based on response headers."""
    watchdog = BinanceRateLimitWatchdog(TigerApiRateLimitConfig(bulk_ticker_interval_seconds=30))

    # Case 1: Normal load (200 weight used out of 2400)
    watchdog.update_from_headers({"x-mbx-used-weight-1m": "200"})
    assert watchdog.last_used_weight_1m == 200
    assert watchdog.is_throttled is False
    assert watchdog.is_paused is False
    assert watchdog.can_request(40) is True
    assert watchdog.get_poll_interval_seconds() == 30.0

    # Case 2: Warning load (1300 weight used >= 1200 threshold)
    watchdog.update_from_headers({"x-mbx-used-weight-1m": "1300"})
    assert watchdog.last_used_weight_1m == 1300
    assert watchdog.is_throttled is True
    assert watchdog.is_paused is False
    assert watchdog.can_request(40) is True
    assert watchdog.get_poll_interval_seconds() == 60.0

    # Case 3: Critical load (1850 weight used >= 1800 threshold)
    watchdog.update_from_headers({"x-mbx-used-weight-1m": "1850"})
    assert watchdog.last_used_weight_1m == 1850
    assert watchdog.is_throttled is True
    assert watchdog.is_paused is True
    assert watchdog.can_request(40) is False
    assert watchdog.get_poll_interval_seconds() == 120.0


def test_tiger_universe_sieve():
    """Verify the Top 150 Sieve filters stablecoins, applies volume floors, and ranks correctly."""
    scanner = TigerUniverseScanner()

    mock_tickers = [
        # Stablecoins (must be rejected)
        {"symbol": "USDCUSDT", "quoteVolume": "500000000", "highPrice": "1.001", "lowPrice": "0.999", "lastPrice": "1.000", "priceChangePercent": "0.01"},
        {"symbol": "FDUSDUSDT", "quoteVolume": "300000000", "highPrice": "1.001", "lowPrice": "0.999", "lastPrice": "1.000", "priceChangePercent": "0.00"},
        # Low volume coin (must be rejected, < $30M)
        {"symbol": "LOWVOLUSDT", "quoteVolume": "12000000", "highPrice": "2.50", "lowPrice": "2.00", "lastPrice": "2.20", "priceChangePercent": "5.0"},
        # High volatility hot prey 1 (40% amplitude, $100M turnover)
        {"symbol": "HOT1USDT", "quoteVolume": "100000000", "highPrice": "1.40", "lowPrice": "1.00", "lastPrice": "1.20", "priceChangePercent": "15.0"},
        # High volatility hot prey 2 (60% amplitude, $80M turnover)
        {"symbol": "HOT2USDT", "quoteVolume": "80000000", "highPrice": "2.60", "lowPrice": "1.60", "lastPrice": "2.00", "priceChangePercent": "25.0"},
        # Moderate volatility coin (8% amplitude, $50M turnover)
        {"symbol": "MOD1USDT", "quoteVolume": "50000000", "highPrice": "10.80", "lowPrice": "10.00", "lastPrice": "10.50", "priceChangePercent": "3.0"},
    ]

    candidates = scanner.parse_raw_tickers(mock_tickers)
    
    # Assert stablecoins and low-volume coins are filtered out
    symbols = [c.symbol for c in candidates]
    assert "USDCUSDT" not in symbols
    assert "FDUSDUSDT" not in symbols
    assert "LOWVOLUSDT" not in symbols
    assert "HOT1USDT" in symbols
    assert "HOT2USDT" in symbols
    assert "MOD1USDT" in symbols

    # HOT2 has higher amplitude (0.50 vs 0.33) -> should rank #1
    assert candidates[0].symbol == "HOT2USDT"
    assert candidates[0].rank == 1
    assert candidates[1].symbol == "HOT1USDT"
    assert candidates[1].rank == 2


def test_stoikov_micro_price_and_ofi():
    """Verify Avellaneda-Stoikov Micro-Price skew and Cont-Kukanov-Stoikov OFI calculation."""
    tracker = SymbolOrderflowTracker("ETHUSDT")

    # Update 1: Best bid 3000 (qty 10), Best ask 3000.5 (qty 2)
    # Bids are 5x larger than asks -> Micro-Price should skew HIGHER towards the ask
    ofi_1 = tracker.process_depth_update(
        best_bid=Decimal("3000.00"), best_bid_qty=Decimal("10.0"),
        best_ask=Decimal("3000.50"), best_ask_qty=Decimal("2.0"),
        timestamp_ms=1000
    )
    assert tracker.last_depth is not None
    # Micro-price = (10 * 3000.5 + 2 * 3000.0) / 12 = 3000.4166
    # Mid-price = 3000.25
    assert tracker.last_depth.micro_price > tracker.last_depth.mid_price
    assert tracker.last_depth.micro_price_skew_bps > Decimal("0")

    # Update 2: Ask wall suddenly flashes: Best ask 3000.5 (qty 50.0)
    ofi_2 = tracker.process_depth_update(
        best_bid=Decimal("3000.00"), best_bid_qty=Decimal("10.0"),
        best_ask=Decimal("3000.50"), best_ask_qty=Decimal("50.0"),
        timestamp_ms=1100
    )
    # Asks heavily dominate -> Micro-Price must skew LOWER towards the bid
    assert tracker.last_depth.micro_price < tracker.last_depth.mid_price
    assert tracker.last_depth.micro_price_skew_bps < Decimal("-0.20")
    # OFI should be strongly negative
    assert ofi_2 < Decimal("-0.45")


def test_trapped_trader_absorption_climax():
    """Verify detection of Trapped Bulls Climax (Setup Short) and Anti-Steamroller Guard."""
    tracker = SymbolOrderflowTracker("SOLUSDT")

    # Seed baseline depth and historical trades across 6 buckets
    tracker.process_depth_update(
        best_bid=Decimal("150.00"), best_bid_qty=Decimal("30.0"),
        best_ask=Decimal("150.02"), best_ask_qty=Decimal("10.0"),
        timestamp_ms=1000
    )
    # Baseline trades over earlier 5-second buckets
    for i in range(6):
        tracker.process_agg_trade(
            trade_id=i + 1,
            price=Decimal("150.01"),
            quantity=Decimal("5.0"),
            is_buyer_maker=(i % 2 == 0),
            timestamp_ms=2000 + (i * 5000)
        )

    # Massive ask iceberg appears and bids vanish (OFI flips violently negative)
    tracker.process_depth_update(
        best_bid=Decimal("150.00"), best_bid_qty=Decimal("2.0"),
        best_ask=Decimal("150.02"), best_ask_qty=Decimal("80.0"),
        timestamp_ms=35000
    )

    # Ingest aggressive market BUY trades surging into the ask wall (CVD surging positively)
    for i in range(5):
        tracker.process_agg_trade(
            trade_id=100 + i,
            price=Decimal("150.02"),
            quantity=Decimal("150.0"),
            is_buyer_maker=False,  # Market buy
            timestamp_ms=35000 + (i * 500)
        )

    # 1m Candle with 72% upper rejection wick and weak close in bottom 28% of bar
    # (High=152.0, Open=150.0, Close=150.2, Low=149.5)
    # Upper wick = 152.0 - 150.2 = 1.8. Range = 2.5. Wick ratio = 72% >= 40%. Close loc = 0.7/2.5 = 28% <= 35%.
    signal = tracker.detect_trapped_trader_climax(
        bar_open=Decimal("150.0"),
        bar_high=Decimal("152.0"),
        bar_low=Decimal("149.5"),
        bar_close=Decimal("150.2"),
        bar_volume=Decimal("500.0"),
        avg_volume_20=Decimal("300.0"),
        delta_oi_pct=Decimal("0.0005")
    )

    assert signal.is_valid is True
    assert signal.action == "SELL"
    assert signal.entry_trigger_price == Decimal("149.5")
    assert signal.invalidation_stop_price == Decimal("152.0")
    assert signal.wick_ratio >= Decimal("0.40")

    # Anti-Steamroller Test: massive volume (6x avg) and massive trend body (85% body)
    steamroller_signal = tracker.detect_trapped_trader_climax(
        bar_open=Decimal("150.0"),
        bar_high=Decimal("155.0"),
        bar_low=Decimal("149.8"),
        bar_close=Decimal("154.5"),  # Huge green body
        bar_volume=Decimal("2000.0"), # 6.6x avg volume
        avg_volume_20=Decimal("300.0")
    )
    assert steamroller_signal.is_valid is False
    assert steamroller_signal.is_steamroller_vetoed is True


def test_signal_ttl_90_seconds():
    """Verify that un-triggered pending signals are purged after 90 seconds."""
    with tempfile.TemporaryDirectory() as tmpdir:
        state_file = os.path.join(tmpdir, "tiger_state.json")
        engine = TigerExecutionEngine(state_file=state_file)

        t0 = datetime.datetime(2026, 11, 15, 12, 0, 0, tzinfo=datetime.timezone.utc)

        mock_signal = AbsorptionSignal(
            symbol="BTCUSDT",
            action="SELL",
            entry_trigger_price=Decimal("90000.00"),
            invalidation_stop_price=Decimal("90800.00"),
            cvd_zscore=Decimal("2.5"),
            micro_price_skew_bps=Decimal("-0.30"),
            ofi_score=Decimal("-0.50"),
            wick_ratio=Decimal("0.55"),
            absorption_density=Decimal("0.85"),
            is_steamroller_vetoed=False,
            is_valid=True,
            reason="Test signal"
        )

        pending = engine.create_signal_from_absorption(
            signal=mock_signal,
            atr_pct=Decimal("0.0080"), # Slow vol
            current_time_utc=t0
        )
        assert pending is not None
        assert pending.signal_id in engine.pending_signals

        # Check at t0 + 80s: still active
        t_80s = t0 + datetime.timedelta(seconds=80)
        expired = engine.check_signal_expiration(t_80s)
        assert len(expired) == 0
        assert pending.signal_id in engine.pending_signals

        # Check at t0 + 91s: must be expired and purged
        t_91s = t0 + datetime.timedelta(seconds=91)
        expired = engine.check_signal_expiration(t_91s)
        assert len(expired) == 1
        assert pending.signal_id not in engine.pending_signals


def test_temporal_decay_ladder():
    """Verify the 8-12-15 Minute Decay Ladder (Velocity check, Stall scratch, Hard kill)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        state_file = os.path.join(tmpdir, "tiger_state.json")
        engine = TigerExecutionEngine(state_file=state_file)

        t0 = datetime.datetime(2026, 11, 15, 12, 0, 0, tzinfo=datetime.timezone.utc)

        mock_signal = AbsorptionSignal(
            symbol="DOGEUSDT", action="SELL", entry_trigger_price=Decimal("0.3800"),
            invalidation_stop_price=Decimal("0.3830"), cvd_zscore=Decimal("2.2"),
            micro_price_skew_bps=Decimal("-0.25"), ofi_score=Decimal("-0.48"),
            wick_ratio=Decimal("0.50"), absorption_density=Decimal("0.85"),
            is_steamroller_vetoed=False, is_valid=True, reason="Test signal"
        )

        sig = engine.create_signal_from_absorption(mock_signal, atr_pct=Decimal("0.0080"), current_time_utc=t0)
        pos = engine.fill_signal(sig.signal_id, fill_price=Decimal("0.3800"), quantity=Decimal("1000"), fill_time_utc=t0)
        pos_id = pos.position_id

        # Test Bracket Take-Profit: Target is -1.01% on a SHORT = 0.3800 * (1 - 0.0101) = 0.376162
        tp_action, _ = engine.evaluate_temporal_lifecycle(pos_id, Decimal("0.3760"), t0 + datetime.timedelta(minutes=3))
        assert tp_action == "TAKE_PROFIT"

        # Test Minute 8: Velocity check passes (price moved favorable by +0.60% -> SL ratcheted)
        # For a short, favorable move means price dropped to 0.3800 * (1 - 0.0060) = 0.37772
        v_action, _ = engine.evaluate_temporal_lifecycle(pos_id, Decimal("0.3775"), t0 + datetime.timedelta(minutes=8, seconds=10))
        assert v_action == "RATCHET_BE"
        assert pos.is_breakeven_ratcheted is True
        # New stop should be locked at entry - 0.10% fees = 0.3800 * (1 - 0.0010) = 0.37962
        assert pos.stop_loss < Decimal("0.3800")

        # Test Minute 12: Stall / Chop Scratch exit (price stuck at 0.3802, -0.05% PnL)
        # Create a fresh non-ratcheted position
        engine.last_fleet_action_time_utc = None
        engine.active_positions.clear()
        pos2 = engine.fill_signal(
            engine.create_signal_from_absorption(mock_signal, atr_pct=Decimal("0.0080"), current_time_utc=t0).signal_id,
            fill_price=Decimal("0.3800"), quantity=Decimal("1000"), fill_time_utc=t0
        )
        s_action, reason = engine.evaluate_temporal_lifecycle(pos2.position_id, Decimal("0.3802"), t0 + datetime.timedelta(minutes=12, seconds=5))
        assert s_action == "STALL_SCRATCH"

        # Test Minute 15: Hard kill
        engine.last_fleet_action_time_utc = None
        engine.active_positions.clear()
        pos3 = engine.fill_signal(
            engine.create_signal_from_absorption(mock_signal, atr_pct=Decimal("0.0080"), current_time_utc=t0).signal_id,
            fill_price=Decimal("0.3800"), quantity=Decimal("1000"), fill_time_utc=t0
        )
        k_action, reason = engine.evaluate_temporal_lifecycle(pos3.position_id, Decimal("0.3810"), t0 + datetime.timedelta(minutes=15, seconds=1))
        assert k_action == "HARD_KILL"


def test_dual_regime_brackets_and_5_loss_breaker():
    """Verify calibrated dual-regime brackets (+1.01%/-0.66% vs +1.90%/-1.10%) and 5-loss pause."""
    with tempfile.TemporaryDirectory() as tmpdir:
        state_file = os.path.join(tmpdir, "tiger_state.json")
        engine = TigerExecutionEngine(state_file=state_file)

        t0 = datetime.datetime(2026, 11, 15, 12, 0, 0, tzinfo=datetime.timezone.utc)

        mock_sig = AbsorptionSignal(
            symbol="BTCUSDT", action="BUY", entry_trigger_price=Decimal("90000.00"),
            invalidation_stop_price=Decimal("89500.00"), cvd_zscore=Decimal("-2.5"),
            micro_price_skew_bps=Decimal("0.30"), ofi_score=Decimal("0.55"),
            wick_ratio=Decimal("0.50"), absorption_density=Decimal("0.85"),
            is_steamroller_vetoed=False, is_valid=True, reason="Test signal"
        )

        # 1. Slow Volatility Regime (ATR < 1.00%): TP +1.01%, SL -0.66%
        sig_slow = engine.create_signal_from_absorption(mock_sig, atr_pct=Decimal("0.0080"), current_time_utc=t0)
        assert sig_slow.is_slow_regime is True
        # For a BUY: TP = 90000 * 1.0101 = 90909.00, SL = 90000 * (1 - 0.0066) = 89406.00
        assert sig_slow.take_profit_price == Decimal("90909.00")
        assert sig_slow.stop_loss_price == Decimal("89406.00")

        # 2. High Volatility Regime (ATR >= 1.00%): TP +1.90%, SL -1.10%
        engine.pending_signals.clear()
        engine.last_fleet_action_time_utc = None
        sig_fast = engine.create_signal_from_absorption(mock_sig, atr_pct=Decimal("0.0120"), current_time_utc=t0)
        assert sig_fast.is_slow_regime is False
        # For a BUY: TP = 90000 * 1.0190 = 91710.00, SL = 90000 * (1 - 0.0110) = 89010.00
        assert sig_fast.take_profit_price == Decimal("91710.00")
        assert sig_fast.stop_loss_price == Decimal("89010.00")

        # 3. Consecutive Loss Pause (5 consecutive stop-outs spaced 20m apart)
        engine.pending_signals.clear()
        for i in range(5):
            t_trade = t0 + datetime.timedelta(minutes=(i + 1) * 20)
            assert engine.is_paused(t_trade) is False
            pos = engine.fill_signal(
                engine.create_signal_from_absorption(mock_sig, atr_pct=Decimal("0.0080"), current_time_utc=t_trade).signal_id,
                fill_price=Decimal("90000.00"), quantity=Decimal("0.01"), fill_time_utc=t_trade
            )
            engine.close_position(
                pos.position_id,
                exit_price=Decimal("89400.00"), # Stop-out loss
                exit_time_utc=t_trade + datetime.timedelta(minutes=5),
                reason="Stop Loss hit"
            )

        assert engine.consecutive_losses == 5
        # Engine must now be PAUSED!
        t_after_5 = t0 + datetime.timedelta(minutes=5*20 + 5)
        assert engine.is_paused(t_after_5 + datetime.timedelta(minutes=10)) is True
        # After 60 minutes cooldown, pause should clear
        assert engine.is_paused(t_after_5 + datetime.timedelta(minutes=65)) is False


def test_tiger_learning_and_distillation():
    """Verify TigerLearningEngine records forensics and distills calibrated rules."""
    import gc
    from src.quant.tiger_learning import TigerLearningEngine, TigerTradeForensics

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = os.path.join(tmpdir, "tiger_test.db")
        rules_path = os.path.join(tmpdir, "tiger_rules.json")
        engine = TigerLearningEngine(db_path=db_path, rules_path=rules_path)

        # Record 3 winning trades and 1 losing trade
        t1 = TigerTradeForensics(
            trade_id="T1", symbol="SOLUSDT", side="BUY", entry_price=Decimal("150.0"),
            exit_price=Decimal("151.5"), notional_usd=Decimal("100.0"), net_pnl_usd=Decimal("0.90"),
            net_pnl_pct=Decimal("0.0090"), duration_seconds=420, exit_reason="TAKE_PROFIT",
            is_win=True, mfe_pct=Decimal("0.0105"), mae_pct=Decimal("0.0010"),
            wick_ratio=Decimal("0.48"), cvd_zscore=Decimal("2.4"), is_slow_regime=True,
            created_at_utc="2026-11-15T12:00:00Z", closed_at_utc="2026-11-15T12:07:00Z"
        )
        t2 = TigerTradeForensics(
            trade_id="T2", symbol="DOGEUSDT", side="SELL", entry_price=Decimal("0.380"),
            exit_price=Decimal("0.376"), notional_usd=Decimal("100.0"), net_pnl_usd=Decimal("0.95"),
            net_pnl_pct=Decimal("0.0095"), duration_seconds=510, exit_reason="TAKE_PROFIT",
            is_win=True, mfe_pct=Decimal("0.0110"), mae_pct=Decimal("0.0015"),
            wick_ratio=Decimal("0.52"), cvd_zscore=Decimal("2.6"), is_slow_regime=True,
            created_at_utc="2026-11-15T12:15:00Z", closed_at_utc="2026-11-15T12:23:30Z"
        )
        t3 = TigerTradeForensics(
            trade_id="T3", symbol="BTCUSDT", side="BUY", entry_price=Decimal("90000.0"),
            exit_price=Decimal("89400.0"), notional_usd=Decimal("100.0"), net_pnl_usd=Decimal("-0.75"),
            net_pnl_pct=Decimal("-0.0075"), duration_seconds=300, exit_reason="STOP_LOSS",
            is_win=False, mfe_pct=Decimal("0.0010"), mae_pct=Decimal("0.0066"),
            wick_ratio=Decimal("0.42"), cvd_zscore=Decimal("2.1"), is_slow_regime=True,
            created_at_utc="2026-11-15T12:30:00Z", closed_at_utc="2026-11-15T12:35:00Z"
        )
        t4 = TigerTradeForensics(
            trade_id="T4", symbol="SOLUSDT", side="SELL", entry_price=Decimal("152.0"),
            exit_price=Decimal("150.5"), notional_usd=Decimal("100.0"), net_pnl_usd=Decimal("0.88"),
            net_pnl_pct=Decimal("0.0088"), duration_seconds=480, exit_reason="TAKE_PROFIT",
            is_win=True, mfe_pct=Decimal("0.0102"), mae_pct=Decimal("0.0012"),
            wick_ratio=Decimal("0.50"), cvd_zscore=Decimal("2.3"), is_slow_regime=True,
            created_at_utc="2026-11-15T12:45:00Z", closed_at_utc="2026-11-15T12:53:00Z"
        )

        for t in [t1, t2, t3, t4]:
            engine.record_trade(t)

        all_trades = engine.fetch_all_trades()
        assert len(all_trades) == 4

        # Run distillation audit
        distilled = engine.run_learning_distillation()
        assert distilled is not None
        assert distilled.sample_size == 4
        assert distilled.win_rate_pct == Decimal("75.0")
        assert distilled.profit_factor > Decimal("2.0")
        # Check that rules file was persisted
        assert os.path.exists(rules_path)
        with open(rules_path) as f:
            saved_rules = json.load(f)
        assert saved_rules["win_rate_pct"] == "75.0"
        gc.collect()


def test_freight_train_outlier_sieve_filter():
    """Verify the Top 150 sieve rejects extreme 24h outlier freight train coins (> +/-35%)."""
    scanner = TigerUniverseScanner()
    mock_tickers = [
        # Normal high volatility coin (+18%)
        {"symbol": "NORMALUSDT", "quoteVolume": "80000000", "highPrice": "2.20", "lowPrice": "1.80", "lastPrice": "2.00", "priceChangePercent": "18.0"},
        # Extreme pump freight train (+82%) -> MUST BE FILTERED OUT
        {"symbol": "EVAAUSDT", "quoteVolume": "120000000", "highPrice": "5.00", "lowPrice": "2.00", "lastPrice": "4.50", "priceChangePercent": "82.5"},
        # Extreme dump freight train (-45%) -> MUST BE FILTERED OUT
        {"symbol": "KAVAUSDT", "quoteVolume": "95000000", "highPrice": "1.00", "lowPrice": "0.50", "lastPrice": "0.55", "priceChangePercent": "-45.0"},
    ]
    candidates = scanner.parse_raw_tickers(mock_tickers)
    candidate_symbols = [c.symbol for c in candidates]

    assert "NORMALUSDT" in candidate_symbols
    assert "EVAAUSDT" not in candidate_symbols
    assert "KAVAUSDT" not in candidate_symbols


def test_wyckoff_outer_close_and_macro_trend():
    """Verify Wyckoff outer 35% close confirmation and 1h macro trend filter."""
    tracker = SymbolOrderflowTracker("ETHUSDT")

    # Seed baseline depth
    tracker.process_depth_update(
        best_bid=Decimal("3000.00"), best_bid_qty=Decimal("20.0"),
        best_ask=Decimal("3000.20"), best_ask_qty=Decimal("10.0"),
        timestamp_ms=1000
    )
    for i in range(6):
        tracker.process_agg_trade(i+1, Decimal("3000.10"), Decimal("5.0"), False, 2000 + (i * 5000))
    # Ask wall flashes, bid drops -> strongly negative OFI & downward micro-price skew
    tracker.process_depth_update(
        best_bid=Decimal("3000.00"), best_bid_qty=Decimal("2.0"),
        best_ask=Decimal("3000.20"), best_ask_qty=Decimal("80.0"),
        timestamp_ms=35000
    )
    for i in range(5):
        tracker.process_agg_trade(100+i, Decimal("3000.20"), Decimal("150.0"), False, 35000 + (i * 500))

    # Case 1: Close is in the middle (50% of candle) -> MUST BE REJECTED
    # High=3020, Low=2980 (Range=40). Close=3000 (Close loc = 20/40 = 50% > 35%)
    sig_mid = tracker.detect_trapped_trader_climax(
        bar_open=Decimal("2990.0"), bar_high=Decimal("3020.0"),
        bar_low=Decimal("2980.0"), bar_close=Decimal("3000.0"),
        bar_volume=Decimal("500.0"), avg_volume_20=Decimal("300.0")
    )
    assert sig_mid.is_valid is False

    # Case 2: Close is in bottom 35% (Close loc = 10/40 = 25% <= 35%) -> VALID SELL
    # Upper wick = 3020 - max(2990, 2990) = 30 (75% wick >= 40%)
    sig_weak = tracker.detect_trapped_trader_climax(
        bar_open=Decimal("2990.0"), bar_high=Decimal("3020.0"),
        bar_low=Decimal("2980.0"), bar_close=Decimal("2990.0"),
        bar_volume=Decimal("500.0"), avg_volume_20=Decimal("300.0"),
        delta_oi_pct=Decimal("0.0005")
    )
    assert sig_weak.is_valid is True
    assert sig_weak.action == "SELL"

    # Case 3: Macro 1h Trend is BULLISH -> Short MUST BE VETOED
    sig_vetoed = tracker.detect_trapped_trader_climax(
        bar_open=Decimal("2990.0"), bar_high=Decimal("3020.0"),
        bar_low=Decimal("2980.0"), bar_close=Decimal("2990.0"),
        bar_volume=Decimal("500.0"), avg_volume_20=Decimal("300.0"),
        macro_trend_1h="BULLISH"
    )
    assert sig_vetoed.is_valid is False


def test_symbol_post_exit_cooldown():
    """Verify 15-minute symbol cooldown eliminates re-entry churning."""
    with tempfile.TemporaryDirectory() as tmpdir:
        state_file = os.path.join(tmpdir, "tiger_state.json")
        engine = TigerExecutionEngine(state_file=state_file)
        t0 = datetime.datetime(2026, 11, 15, 12, 0, 0, tzinfo=datetime.timezone.utc)

        mock_sig = AbsorptionSignal(
            symbol="SOLUSDT", action="SELL", entry_trigger_price=Decimal("150.0"),
            invalidation_stop_price=Decimal("152.0"), cvd_zscore=Decimal("2.4"),
            micro_price_skew_bps=Decimal("-0.25"), ofi_score=Decimal("-0.50"),
            wick_ratio=Decimal("0.60"), absorption_density=Decimal("0.85"),
            is_steamroller_vetoed=False, is_valid=True, reason="Test"
        )

        sig = engine.create_signal_from_absorption(mock_sig, atr_pct=Decimal("0.0080"), current_time_utc=t0)
        pos = engine.fill_signal(sig.signal_id, fill_price=Decimal("150.0"), quantity=Decimal("10"), fill_time_utc=t0)

        # Close trade at t0 + 5m
        t_exit = t0 + datetime.timedelta(minutes=5)
        engine.close_position(pos.position_id, exit_price=Decimal("148.5"), exit_time_utc=t_exit, reason="TP")

        # Symbol is now in cooldown until t_exit + 15m (t0 + 20m)
        assert engine.is_symbol_in_cooldown("SOLUSDT", t0 + datetime.timedelta(minutes=10)) is True

        # New signal for SOLUSDT at t0 + 10m MUST BE VETOED
        vetoed_sig = engine.create_signal_from_absorption(
            mock_sig, atr_pct=Decimal("0.0080"), current_time_utc=t0 + datetime.timedelta(minutes=10)
        )
        assert vetoed_sig is None

        # After 15m cooldown expires (t0 + 21m), new signal is accepted
        assert engine.is_symbol_in_cooldown("SOLUSDT", t0 + datetime.timedelta(minutes=21)) is False
        accepted_sig = engine.create_signal_from_absorption(
            mock_sig, atr_pct=Decimal("0.0080"), current_time_utc=t0 + datetime.timedelta(minutes=21)
        )
        assert accepted_sig is not None


def test_profit_cushion_breakeven_ratchet():
    """Verify that reaching +0.80% MFE immediately ratchets SL to breakeven + fees at minute 1."""
    with tempfile.TemporaryDirectory() as tmpdir:
        state_file = os.path.join(tmpdir, "tiger_state.json")
        engine = TigerExecutionEngine(state_file=state_file)
        t0 = datetime.datetime(2026, 11, 15, 12, 0, 0, tzinfo=datetime.timezone.utc)

        mock_sig = AbsorptionSignal(
            symbol="AGTUSDT", action="SELL", entry_trigger_price=Decimal("1.000"),
            invalidation_stop_price=Decimal("1.011"), cvd_zscore=Decimal("2.4"),
            micro_price_skew_bps=Decimal("-0.25"), ofi_score=Decimal("-0.50"),
            wick_ratio=Decimal("0.60"), absorption_density=Decimal("0.85"),
            is_steamroller_vetoed=False, is_valid=True, reason="Test"
        )
        sig = engine.create_signal_from_absorption(mock_sig, atr_pct=Decimal("0.0120"), current_time_utc=t0)
        pos = engine.fill_signal(sig.signal_id, fill_price=Decimal("1.000"), quantity=Decimal("100"), fill_time_utc=t0)

        # Price drops to 0.9915 (+0.85% gain) at minute 1 (well before 8m velocity check)
        t_1m = t0 + datetime.timedelta(minutes=1)
        action, reason = engine.evaluate_temporal_lifecycle(
            pos.position_id, current_price=Decimal("0.9915"), current_time_utc=t_1m
        )
        assert action == "RATCHET_BE"
        assert "Profit Cushion Lock" in reason
        assert pos.is_breakeven_ratcheted is True
        # For a short, SL ratcheted below entry: 1.000 * (1 - 0.0010) = 0.999
        assert pos.stop_loss < Decimal("1.000")


def test_volatility_parity_sizing():
    """Verify that volatility parity locks dollar stop-out risk to exactly $1.50."""
    engine = TigerExecutionEngine()

    # Case 1: Slow volatility regime (SL = 0.66%)
    # Notional = $1.50 / 0.0066 = $227.27
    entry_slow = Decimal("100.00")
    sl_slow = Decimal("99.34") # -0.66%
    notional_1, qty_1 = engine.calculate_volatility_parity_sizing(entry_slow, sl_slow)
    assert notional_1 > Decimal("220.00")
    assert notional_1 < Decimal("230.00")
    expected_loss_1 = notional_1 * ((entry_slow - sl_slow) / entry_slow)
    assert abs(expected_loss_1 - Decimal("1.50")) < Decimal("0.02")

    # Case 2: High volatility regime (SL = 1.10%)
    # Notional = $1.50 / 0.0110 = $136.36
    entry_fast = Decimal("100.00")
    sl_fast = Decimal("98.90") # -1.10%
    notional_2, qty_2 = engine.calculate_volatility_parity_sizing(entry_fast, sl_fast)
    assert notional_2 > Decimal("130.00")
    assert notional_2 < Decimal("140.00")
    expected_loss_2 = notional_2 * ((entry_fast - sl_fast) / entry_fast)
    assert abs(expected_loss_2 - Decimal("1.50")) < Decimal("0.02")


def test_btc_macro_tide_gate_veto():
    """Verify that BTC sudden dumping or selling pressure vetoes altcoin longs."""
    tracker = SymbolOrderflowTracker("ETHUSDT")

    # Set up valid trapped bears condition
    tracker.process_depth_update(
        best_bid=Decimal("3000.20"), best_bid_qty=Decimal("10.0"),
        best_ask=Decimal("3000.40"), best_ask_qty=Decimal("20.0"),
        timestamp_ms=1000
    )
    for i in range(6):
        tracker.process_agg_trade(i+1, Decimal("3000.30"), Decimal("5.0"), True, 2000 + (i * 5000))
    tracker.process_depth_update(
        best_bid=Decimal("3000.20"), best_bid_qty=Decimal("80.0"),
        best_ask=Decimal("3000.40"), best_ask_qty=Decimal("2.0"),
        timestamp_ms=35000
    )
    for i in range(5):
        tracker.process_agg_trade(100+i, Decimal("3000.20"), Decimal("150.0"), True, 35000 + (i * 500))

    # Case 1: Normal BTC (return = 0.00%, CVD z = 0.0) -> Valid BUY
    sig_ok = tracker.detect_trapped_trader_climax(
        bar_open=Decimal("3010.0"), bar_high=Decimal("3020.0"),
        bar_low=Decimal("2980.0"), bar_close=Decimal("3010.0"),
        bar_volume=Decimal("500.0"), avg_volume_20=Decimal("300.0"),
        btc_1m_return=Decimal("0.0000"), btc_cvd_zscore=Decimal("0.0"),
        delta_oi_pct=Decimal("0.0005")
    )
    assert sig_ok.is_valid is True
    assert sig_ok.action == "BUY"

    # Case 2: BTC is flash-dumping (-0.50% in 1m) -> VETO LONG!
    sig_vetoed_dump = tracker.detect_trapped_trader_climax(
        bar_open=Decimal("3010.0"), bar_high=Decimal("3020.0"),
        bar_low=Decimal("2980.0"), bar_close=Decimal("3010.0"),
        bar_volume=Decimal("500.0"), avg_volume_20=Decimal("300.0"),
        btc_1m_return=Decimal("-0.0050"), btc_cvd_zscore=Decimal("0.0")
    )
    assert sig_vetoed_dump.is_valid is False

    # Case 3: BTC has severe selling delta pressure (CVD z = -3.2 sigma) -> VETO LONG!
    sig_vetoed_cvd = tracker.detect_trapped_trader_climax(
        bar_open=Decimal("3010.0"), bar_high=Decimal("3020.0"),
        bar_low=Decimal("2980.0"), bar_close=Decimal("3010.0"),
        bar_volume=Decimal("500.0"), avg_volume_20=Decimal("300.0"),
        btc_1m_return=Decimal("0.0000"), btc_cvd_zscore=Decimal("-3.2")
    )
    assert sig_vetoed_cvd.is_valid is False


def test_tiger_ws_manager_tracker_routing():
    """Verify TigerWebSocketManager routes events to SymbolOrderflowTracker and tracks BTC pulse."""
    from src.quant.tiger_ws import TigerWebSocketManager
    ws_mgr = TigerWebSocketManager(initial_symbols=["SOLUSDT"])

    # Simulate trade message on BTCUSDT
    ws_mgr._handle_agg_trade("BTCUSDT", {
        "a": 1001, "p": "90000.0", "q": "1.0", "m": False, "T": 1000
    })
    ws_mgr._handle_agg_trade("BTCUSDT", {
        "a": 1002, "p": "90100.0", "q": "2.0", "m": False, "T": 1500
    })

    # Pulse should show positive 1m return
    ret, _ = ws_mgr.get_btc_macro_pulse()
    assert ret > Decimal("0")

    # Simulate depth message on SOLUSDT
    ws_mgr._handle_depth_update("SOLUSDT", {
        "b": [["150.00", "10.0"]], "a": [["150.02", "5.0"]], "E": 1000
    })
    tracker = ws_mgr.get_tracker("SOLUSDT")
    assert tracker is not None
    assert tracker.last_depth is not None
    assert tracker.last_depth.best_bid == Decimal("150.00")


def test_tiger_delta_oi_climax_filter():
    """Verify Trapped Trader Open Interest (ΔOI) Climax Gate differentiates trapped traders from liquidation stops."""
    from src.quant.tiger_config import TigerOrderflowConfig
    cfg = TigerOrderflowConfig(
        delta_oi_filter_enabled=True,
        min_delta_oi_pct=Decimal("0.0001"),  # +0.01% expansion required
        oi_lookback_seconds=180
    )
    tracker = SymbolOrderflowTracker("ETHUSDT", config=cfg)

    # Setup micro-price and OFI skew for long absorption
    tracker.process_depth_update(
        best_bid=Decimal("3000.20"), best_bid_qty=Decimal("10.0"),
        best_ask=Decimal("3000.40"), best_ask_qty=Decimal("20.0"),
        timestamp_ms=1000
    )
    for i in range(6):
        tracker.process_agg_trade(i+1, Decimal("3000.30"), Decimal("5.0"), True, 2000 + (i * 5000))
    tracker.process_depth_update(
        best_bid=Decimal("3000.20"), best_bid_qty=Decimal("80.0"),
        best_ask=Decimal("3000.40"), best_ask_qty=Decimal("2.0"),
        timestamp_ms=35000
    )
    for i in range(5):
        tracker.process_agg_trade(100+i, Decimal("3000.20"), Decimal("150.0"), True, 35000 + (i * 500))

    # Ingest baseline Open Interest
    tracker.process_open_interest(open_interest=Decimal("100000.0"), timestamp_ms=1000)

    # Case 1: Open Interest DROPS to 99,500 (-0.50% drop, stop liquidation flush) -> VETO!
    tracker.process_open_interest(open_interest=Decimal("99500.0"), timestamp_ms=36000)
    abs_doi, pct_doi = tracker.compute_delta_oi(window_seconds=180)
    assert abs_doi == Decimal("-500.0")
    assert pct_doi == Decimal("-0.005")

    sig_vetoed = tracker.detect_trapped_trader_climax(
        bar_open=Decimal("3010.0"), bar_high=Decimal("3020.0"),
        bar_low=Decimal("2980.0"), bar_close=Decimal("3010.0"),
        bar_volume=Decimal("500.0"), avg_volume_20=Decimal("300.0")
    )
    assert sig_vetoed.is_valid is False
    assert "Open Interest Veto" in sig_vetoed.reason
    assert sig_vetoed.delta_oi_pct == Decimal("-0.005")

    # Case 2: Open Interest RISES to 101,200 (+1.20% increase, trapped bears entering!) -> SIGNAL ACCEPTED!
    tracker.process_open_interest(open_interest=Decimal("101200.0"), timestamp_ms=37000)
    sig_accepted = tracker.detect_trapped_trader_climax(
        bar_open=Decimal("3010.0"), bar_high=Decimal("3020.0"),
        bar_low=Decimal("2980.0"), bar_close=Decimal("3010.0"),
        bar_volume=Decimal("500.0"), avg_volume_20=Decimal("300.0")
    )
    assert sig_accepted.is_valid is True
    assert sig_accepted.action == "BUY"
    assert "positive ΔOI" in sig_accepted.reason
    assert sig_accepted.delta_oi_pct > Decimal("0")

    # Case 3: Filter disabled -> negative ΔOI does not veto
    cfg_disabled = TigerOrderflowConfig(delta_oi_filter_enabled=False)
    tracker_dis = SymbolOrderflowTracker("ETHUSDT", config=cfg_disabled)
    tracker_dis.last_depth = tracker.last_depth
    tracker_dis.last_ofi = tracker.last_ofi
    tracker_dis.trades = tracker.trades
    tracker_dis.process_open_interest(open_interest=Decimal("100000.0"), timestamp_ms=1000)
    tracker_dis.process_open_interest(open_interest=Decimal("99000.0"), timestamp_ms=36000)

    sig_dis = tracker_dis.detect_trapped_trader_climax(
        bar_open=Decimal("3010.0"), bar_high=Decimal("3020.0"),
        bar_low=Decimal("2980.0"), bar_close=Decimal("3010.0"),
        bar_volume=Decimal("500.0"), avg_volume_20=Decimal("300.0")
    )
    assert sig_dis.is_valid is True
    assert sig_dis.action == "BUY"


def test_tiger_anti_burst_slot_leak_and_fleet_cooldown():
    """Verify anti-burst slot-leak protection, global fleet inter-trade cooldown, and duplicate prevention."""
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tf:
        state_path = tf.name

    try:
        engine = TigerExecutionEngine(state_file=state_path)
        engine.pending_signals.clear()
        engine.active_positions.clear()
        t0 = datetime.datetime(2026, 11, 15, 12, 0, 0, tzinfo=datetime.timezone.utc)

        sig_a = AbsorptionSignal(
            symbol="COINA", action="BUY", entry_trigger_price=Decimal("10.0"),
            invalidation_stop_price=Decimal("9.9"), cvd_zscore=Decimal("-2.2"),
            micro_price_skew_bps=Decimal("0.25"), ofi_score=Decimal("0.50"),
            wick_ratio=Decimal("0.45"), absorption_density=Decimal("0.85"),
            is_steamroller_vetoed=False, is_valid=True, reason="Test Sig A"
        )

        # 1. First signal on COINA succeeds
        res_a = engine.create_signal_from_absorption(sig_a, atr_pct=Decimal("0.005"), current_time_utc=t0)
        assert res_a is not None
        assert len(engine.pending_signals) == 1

        # 2. Duplicate signal on COINA rejected
        res_dup = engine.create_signal_from_absorption(sig_a, atr_pct=Decimal("0.005"), current_time_utc=t0 + datetime.timedelta(seconds=10))
        assert res_dup is None

        # 3. Signal on COINB 20s later vetoed by Global Fleet Cooldown (60s minimum)
        sig_b = AbsorptionSignal(
            symbol="COINB", action="BUY", entry_trigger_price=Decimal("20.0"),
            invalidation_stop_price=Decimal("19.8"), cvd_zscore=Decimal("-2.2"),
            micro_price_skew_bps=Decimal("0.25"), ofi_score=Decimal("0.50"),
            wick_ratio=Decimal("0.45"), absorption_density=Decimal("0.85"),
            is_steamroller_vetoed=False, is_valid=True, reason="Test Sig B"
        )
        res_b_early = engine.create_signal_from_absorption(sig_b, atr_pct=Decimal("0.005"), current_time_utc=t0 + datetime.timedelta(seconds=20))
        assert res_b_early is None

        # 4. Signal on COINB 65s later passes Global Fleet Cooldown
        t1 = t0 + datetime.timedelta(seconds=65)
        res_b = engine.create_signal_from_absorption(sig_b, atr_pct=Decimal("0.005"), current_time_utc=t1)
        assert res_b is not None
        assert len(engine.pending_signals) == 2

        # 5. Slot Leak Test: With 2 pending signals, total committed slots = 2 (max_concurrent_positions = 2)
        # Even if active_positions is 0, a 3rd signal on COINC MUST be rejected!
        sig_c = AbsorptionSignal(
            symbol="COINC", action="BUY", entry_trigger_price=Decimal("30.0"),
            invalidation_stop_price=Decimal("29.7"), cvd_zscore=Decimal("-2.2"),
            micro_price_skew_bps=Decimal("0.25"), ofi_score=Decimal("0.50"),
            wick_ratio=Decimal("0.45"), absorption_density=Decimal("0.85"),
            is_steamroller_vetoed=False, is_valid=True, reason="Test Sig C"
        )
        t2 = t1 + datetime.timedelta(seconds=70)
        res_c = engine.create_signal_from_absorption(sig_c, atr_pct=Decimal("0.005"), current_time_utc=t2)
        assert res_c is None, "Slot leak! 3rd signal permitted when total committed slots == 2"

    finally:
        if os.path.exists(state_path):
            os.remove(state_path)


def test_tiger_forensics_autopsy_taxonomy_and_migration():
    """Verify empirical forensic autopsy classification and SQLite schema migration."""
    from src.quant.tiger_learning import (
        TigerLearningEngine,
        TigerTradeForensics,
        classify_trade_autopsy,
    )

    # 1. Verify Autopsy Taxonomy
    assert classify_trade_autopsy(is_win=True, mfe_pct=Decimal("0.012"), mae_pct=Decimal("0.001"), net_pnl_usd=Decimal("0.90"), exit_reason="TAKE_PROFIT") == "WIN_SQUEEZE"
    assert classify_trade_autopsy(is_win=False, mfe_pct=Decimal("0.001"), mae_pct=Decimal("0.001"), net_pnl_usd=Decimal("-0.05"), exit_reason="STALL_SCRATCH") == "STALL_SCRATCH"
    assert classify_trade_autopsy(is_win=False, mfe_pct=Decimal("0.000"), mae_pct=Decimal("0.0066"), net_pnl_usd=Decimal("-0.90"), exit_reason="STOP_LOSS") == "ZERO_MFE_LIQ_FLUSH"
    assert classify_trade_autopsy(is_win=False, mfe_pct=Decimal("0.0065"), mae_pct=Decimal("0.0066"), net_pnl_usd=Decimal("-0.90"), exit_reason="STOP_LOSS") == "MFE_REVERSAL"
    assert classify_trade_autopsy(is_win=False, mfe_pct=Decimal("0.001"), mae_pct=Decimal("0.025"), net_pnl_usd=Decimal("-3.20"), exit_reason="HARD_KILL") == "STEAMROLLER_OUTLIER"
    assert classify_trade_autopsy(is_win=False, mfe_pct=Decimal("0.002"), mae_pct=Decimal("0.0066"), net_pnl_usd=Decimal("-0.90"), exit_reason="STOP_LOSS") == "STOP_OUT"

    # 2. Verify DB persistence and auto-classification
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = os.path.join(tmpdir, "autopsy_test.db")
        rules_path = os.path.join(tmpdir, "rules_test.json")
        eng = TigerLearningEngine(db_path=db_path, rules_path=rules_path)

        t = TigerTradeForensics(
            trade_id="TR_TEST_1",
            symbol="BTCUSDT",
            side="BUY",
            entry_price=Decimal("90000"),
            exit_price=Decimal("89400"),
            notional_usd=Decimal("100"),
            net_pnl_usd=Decimal("-0.90"),
            net_pnl_pct=Decimal("-0.009"),
            duration_seconds=120,
            exit_reason="STOP_LOSS",
            is_win=False,
            mfe_pct=Decimal("0.000"),
            mae_pct=Decimal("0.0066"),
            wick_ratio=Decimal("0.45"),
            cvd_zscore=Decimal("2.2"),
            is_slow_regime=True,
            created_at_utc="2026-11-15T12:00:00+00:00",
            closed_at_utc="2026-11-15T12:02:00+00:00",
            execution_mode="PAPER"
            # autopsy_code omitted to test auto-classification
        )
        eng.record_trade(t)
        all_tr = eng.fetch_all_trades()
        assert len(all_tr) == 1
        assert all_tr[0].autopsy_code == "ZERO_MFE_LIQ_FLUSH"
        assert all_tr[0].execution_mode == "PAPER"


def test_tiger_quarantine_temporal_decay_and_shadow_graduation():
    """Verify temporal expiration decay and shadow evaluation graduation."""
    from src.quant.tiger_learning import TigerLearningEngine

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = os.path.join(tmpdir, "decay_test.db")
        rules_path = os.path.join(tmpdir, "rules_decay.json")
        eng = TigerLearningEngine(db_path=db_path, rules_path=rules_path)

        t0 = datetime.datetime(2026, 11, 15, 12, 0, 0, tzinfo=datetime.timezone.utc)
        eng.quarantine_symbol("COIN_A", reason="PAPER_TOXIC_STREAK", execution_mode="PAPER", duration_hours=12, now_dt=t0)
        eng.quarantine_symbol("COIN_B", reason="PAPER_TOXIC_STREAK", execution_mode="PAPER", duration_hours=12, now_dt=t0)

        # 1. At t0 + 6 hours: Both are active
        t_6h = t0 + datetime.timedelta(hours=6)
        active, reg = eng.evaluate_quarantines(now_dt=t_6h)
        assert "COIN_A" in active
        assert "COIN_B" in active

        # 2. Shadow Re-qualification for COIN_B at t0 + 7 hours (3 shadow signals: 2 wins, 1 loss -> 66.7% win rate)
        eng.record_shadow_signal("COIN_B", is_win=True, mfe_pct=Decimal("0.012"), now_dt=t0 + datetime.timedelta(hours=7, minutes=5))
        eng.record_shadow_signal("COIN_B", is_win=False, mfe_pct=Decimal("0.002"), now_dt=t0 + datetime.timedelta(hours=7, minutes=10))
        eng.record_shadow_signal("COIN_B", is_win=True, mfe_pct=Decimal("0.010"), now_dt=t0 + datetime.timedelta(hours=7, minutes=15))

        active_7h, reg_7h = eng.evaluate_quarantines(now_dt=t0 + datetime.timedelta(hours=8))
        assert "COIN_B" not in active_7h, "COIN_B failed early shadow graduation!"
        assert reg_7h["COIN_B"]["status"] == "GRADUATED"
        assert "COIN_A" in active_7h

        # 3. At t0 + 13 hours: COIN_A expires via temporal decay
        t_13h = t0 + datetime.timedelta(hours=13)
        active_13h, reg_13h = eng.evaluate_quarantines(now_dt=t_13h)
        assert len(active_13h) == 0
        assert reg_13h["COIN_A"]["status"] == "GRADUATED"


def test_tiger_dual_track_bayesian_weighting():
    """Verify Live trades carry 3.0x weight over Paper trades in Bayesian distillation."""
    from src.quant.tiger_learning import TigerLearningEngine, TigerTradeForensics

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = os.path.join(tmpdir, "bayesian_test.db")
        rules_path = os.path.join(tmpdir, "rules_bayesian.json")
        eng = TigerLearningEngine(db_path=db_path, rules_path=rules_path)

        now = datetime.datetime.now(datetime.timezone.utc)
        # Record 4 paper trades: 2 wins, 2 losses (Paper WR = 50.0%)
        for i in range(4):
            is_w = (i % 2 == 0)
            eng.record_trade(TigerTradeForensics(
                trade_id=f"P_{i}", symbol=f"SYM_{i}USDT", side="BUY",
                entry_price=Decimal("100"), exit_price=Decimal("101") if is_w else Decimal("99"),
                notional_usd=Decimal("100"), net_pnl_usd=Decimal("0.90") if is_w else Decimal("-0.90"),
                net_pnl_pct=Decimal("0.009") if is_w else Decimal("-0.009"), duration_seconds=300,
                exit_reason="TAKE_PROFIT" if is_w else "STOP_LOSS", is_win=is_w,
                mfe_pct=Decimal("0.010") if is_w else Decimal("0.001"), mae_pct=Decimal("0.002"),
                wick_ratio=Decimal("0.45"), cvd_zscore=Decimal("2.2"), is_slow_regime=True,
                created_at_utc=now.isoformat(), closed_at_utc=now.isoformat(),
                execution_mode="PAPER"
            ))

        # Record 1 live trade: 1 win (Live WR = 100.0%)
        eng.record_trade(TigerTradeForensics(
            trade_id="L_0", symbol="LIVETOKENUSDT", side="BUY",
            entry_price=Decimal("50"), exit_price=Decimal("50.5"),
            notional_usd=Decimal("100"), net_pnl_usd=Decimal("0.90"),
            net_pnl_pct=Decimal("0.009"), duration_seconds=300,
            exit_reason="TAKE_PROFIT", is_win=True,
            mfe_pct=Decimal("0.010"), mae_pct=Decimal("0.002"),
            wick_ratio=Decimal("0.45"), cvd_zscore=Decimal("2.2"), is_slow_regime=True,
            created_at_utc=now.isoformat(), closed_at_utc=now.isoformat(),
            execution_mode="LIVE"
        ))

        distilled = eng.run_learning_distillation(now_dt=now)
        assert distilled is not None
        assert distilled.paper_sample_size == 4
        assert distilled.live_sample_size == 1
        assert distilled.paper_win_rate_pct == Decimal("50.0")
        assert distilled.live_win_rate_pct == Decimal("100.0")

        # Bayesian weighted calculation:
        # Weighted wins = (2 paper * 1.0) + (1 live * 3.0) = 5.0
        # Weighted total = (4 paper * 1.0) + (1 live * 3.0) = 7.0
        # Expected WR = 5.0 / 7.0 * 100 = 71.428% -> 71.4%
        assert distilled.win_rate_pct == Decimal("71.4")


def test_strict_negative_affirmation_oi_cold_start_veto():
    """Verify Strict Negative Affirmation: <2 OI snapshots or missing delta_oi strictly vetoes trades."""
    tracker = SymbolOrderflowTracker("ASTERUSDT")

    # Ingest depth & trade absorption
    tracker.process_depth_update(Decimal("0.5000"), Decimal("10.0"), Decimal("0.5001"), Decimal("20.0"), 1000)
    for i in range(6):
        tracker.process_agg_trade(i+1, Decimal("0.50005"), Decimal("5.0"), True, 2000 + (i * 5000))
    tracker.process_depth_update(Decimal("0.5000"), Decimal("80.0"), Decimal("0.5001"), Decimal("2.0"), 35000)
    for i in range(5):
        tracker.process_agg_trade(100+i, Decimal("0.50005"), Decimal("150.0"), True, 35000 + (i * 500))

    # 1. Zero snapshots -> Cold Start Veto!
    sig_cold = tracker.detect_trapped_trader_climax(
        bar_open=Decimal("0.5100"), bar_high=Decimal("0.5200"),
        bar_low=Decimal("0.4900"), bar_close=Decimal("0.5100"),
        bar_volume=Decimal("500.0"), avg_volume_20=Decimal("300.0")
    )
    assert sig_cold.is_valid is False
    assert "Strict negative affirmation enforced" in sig_cold.reason

    # 2. Only 1 snapshot -> Still Cold Start Veto!
    tracker.process_open_interest(Decimal("1000000"), 35000)
    sig_1shot = tracker.detect_trapped_trader_climax(
        bar_open=Decimal("0.5100"), bar_high=Decimal("0.5200"),
        bar_low=Decimal("0.4900"), bar_close=Decimal("0.5100"),
        bar_volume=Decimal("500.0"), avg_volume_20=Decimal("300.0")
    )
    assert sig_1shot.is_valid is False
    assert "Strict negative affirmation enforced" in sig_1shot.reason

    # 3. 2 snapshots with positive expansion (+0.05%) -> Valid BUY!
    tracker.process_open_interest(Decimal("1000500"), 95000)
    sig_valid = tracker.detect_trapped_trader_climax(
        bar_open=Decimal("0.5100"), bar_high=Decimal("0.5200"),
        bar_low=Decimal("0.4900"), bar_close=Decimal("0.5100"),
        bar_volume=Decimal("500.0"), avg_volume_20=Decimal("300.0")
    )
    assert sig_valid.is_valid is True
    assert sig_valid.action == "BUY"


def test_5m_plateau_breakeven_ratchet_anti_chop():
    """Verify 5-minute plateau breakeven ratchet shields capital on stalled trades."""
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tf:
        state_path = tf.name

    try:
        engine = TigerExecutionEngine(state_file=state_path)
        engine.pending_signals.clear()
        engine.active_positions.clear()
        engine.last_fleet_action_time_utc = None
        t0 = datetime.datetime(2026, 11, 16, 12, 0, 0, tzinfo=datetime.timezone.utc)

        # 1. Create and fill signal
        sig = AbsorptionSignal(
            symbol="INITUSDT", action="BUY", entry_trigger_price=Decimal("0.1000"),
            invalidation_stop_price=Decimal("0.09945"), cvd_zscore=Decimal("-2.2"),
            micro_price_skew_bps=Decimal("0.25"), ofi_score=Decimal("0.50"),
            wick_ratio=Decimal("0.45"), absorption_density=Decimal("0.85"),
            is_steamroller_vetoed=False, is_valid=True, reason="Test Setup"
        )
        res = engine.create_signal_from_absorption(sig, atr_pct=Decimal("0.005"), current_time_utc=t0)
        assert res is not None

        pos = engine.fill_signal(
            signal_id=res.signal_id, fill_price=Decimal("0.1000"),
            quantity=Decimal("1000"), fill_time_utc=t0, notional_usd=Decimal("100.0")
        )
        assert pos.stop_loss == Decimal("0.09934")  # -0.66% slow SL

        # 2. At minute 2: Price reaches 0.10025 (+0.25% MFE)
        t_2m = t0 + datetime.timedelta(minutes=2)
        action, _ = engine.evaluate_temporal_lifecycle(pos.position_id, Decimal("0.10025"), t_2m)
        assert action == "HOLD"
        assert pos.highest_favorable_price == Decimal("0.10025")

        # 3. At minute 5.5: Price stalls at 0.10010 (+0.10%). 5m Plateau Ratchet triggers!
        t_5m30 = t0 + datetime.timedelta(minutes=5, seconds=30)
        action, reason = engine.evaluate_temporal_lifecycle(pos.position_id, Decimal("0.10010"), t_5m30)
        assert action == "RATCHET_BE"
        assert "5m Plateau Ratchet" in reason
        assert pos.is_breakeven_ratcheted is True
        # Stop loss ratcheted to entry * (1 - 0.0010) = 0.09990 (-0.10% breakeven buffer)
        assert pos.stop_loss == Decimal("0.09990")

        # 4. At minute 8.75: Price pulls back to 0.09985 (-0.15%)
        t_8m45 = t0 + datetime.timedelta(minutes=8, seconds=45)
        action, reason = engine.evaluate_temporal_lifecycle(pos.position_id, Decimal("0.09985"), t_8m45)
        assert action == "STOP_LOSS"
        assert "Stop Hit" in reason
        # Instead of hitting the old 0.09934 (-0.66%) stop, it safely exited at the tightened breakeven stop!
    finally:
        if os.path.exists(state_path):
            os.remove(state_path)


def test_tiger_sieve_active_trade_and_quarantine_exclusion():
    """Verify that symbols with active trades, pending orders, or quarantines are excluded from the Top 5 Prey slots."""
    scanner = TigerUniverseScanner()

    mock_tickers = [
        {"symbol": "COIN1USDT", "quoteVolume": "100000000", "highPrice": "2.00", "lowPrice": "1.00", "lastPrice": "1.50", "priceChangePercent": "10.0"},  # Vol: 0.667 (Rank 1)
        {"symbol": "COIN2USDT", "quoteVolume": "90000000", "highPrice": "2.00", "lowPrice": "1.10", "lastPrice": "1.50", "priceChangePercent": "8.0"},    # Vol: 0.600 (Rank 2)
        {"symbol": "COIN3USDT", "quoteVolume": "80000000", "highPrice": "2.00", "lowPrice": "1.20", "lastPrice": "1.50", "priceChangePercent": "6.0"},    # Vol: 0.533 (Rank 3)
        {"symbol": "COIN4USDT", "quoteVolume": "70000000", "highPrice": "2.00", "lowPrice": "1.30", "lastPrice": "1.50", "priceChangePercent": "4.0"},    # Vol: 0.467 (Rank 4)
        {"symbol": "COIN5USDT", "quoteVolume": "60000000", "highPrice": "2.00", "lowPrice": "1.40", "lastPrice": "1.50", "priceChangePercent": "2.0"},    # Vol: 0.400 (Rank 5)
        {"symbol": "COIN6USDT", "quoteVolume": "50000000", "highPrice": "2.00", "lowPrice": "1.50", "lastPrice": "1.50", "priceChangePercent": "1.0"},    # Vol: 0.333 (Rank 6)
        {"symbol": "COIN7USDT", "quoteVolume": "40000000", "highPrice": "2.00", "lowPrice": "1.60", "lastPrice": "1.50", "priceChangePercent": "0.5"},    # Vol: 0.267 (Rank 7)
    ]
    scanner.set_fetcher(lambda: (mock_tickers, {"x-mbx-used-weight-1m": "100"}))

    # 1. Baseline: No exclusions -> Top 5 = COIN1, COIN2, COIN3, COIN4, COIN5
    u150, p5_base = scanner.run_sieve()
    assert [c.symbol for c in p5_base] == ["COIN1USDT", "COIN2USDT", "COIN3USDT", "COIN4USDT", "COIN5USDT"]

    # 2. Exclude COIN1 (active trade) and COIN3 (quarantined)
    # COIN6 and COIN7 MUST be promoted into the Top 5 slots!
    u150, p5_filtered = scanner.run_sieve(excluded_symbols={"COIN1USDT", "COIN3USDT"})
    assert [c.symbol for c in p5_filtered] == ["COIN2USDT", "COIN4USDT", "COIN5USDT", "COIN6USDT", "COIN7USDT"]
    assert "COIN1USDT" not in [c.symbol for c in p5_filtered]
    assert "COIN3USDT" not in [c.symbol for c in p5_filtered]


def test_tiger_execution_engine_ratchet_to_breakeven():
    """Verify TigerExecutionEngine.ratchet_to_breakeven sets SL and flags atomically with Zero Float math."""
    with tempfile.TemporaryDirectory() as tmpdir:
        state_file = os.path.join(tmpdir, "tiger_state.json")
        engine = TigerExecutionEngine(state_file=state_file)
        t0 = datetime.datetime(2026, 11, 17, 2, 0, 0, tzinfo=datetime.timezone.utc)

        # 1. Test SELL position with explicit new_sl
        mock_sig = AbsorptionSignal(
            symbol="RAREUSDT", action="SELL", entry_trigger_price=Decimal("0.0133500"),
            invalidation_stop_price=Decimal("0.0134234"), cvd_zscore=Decimal("2.4"),
            micro_price_skew_bps=Decimal("-0.25"), ofi_score=Decimal("-0.50"),
            wick_ratio=Decimal("0.60"), absorption_density=Decimal("0.85"),
            is_steamroller_vetoed=False, is_valid=True, reason="Test Short"
        )
        sig = engine.create_signal_from_absorption(mock_sig, atr_pct=Decimal("0.0100"), current_time_utc=t0)
        pos = engine.fill_signal(sig.signal_id, fill_price=Decimal("0.0133500"), quantity=Decimal("20000"), fill_time_utc=t0)
        assert pos.is_breakeven_ratcheted is False

        # Ratchet with explicit new_sl
        new_sl = Decimal("0.01333398")
        success = engine.ratchet_to_breakeven(pos.position_id, new_sl=new_sl)
        assert success is True
        assert pos.stop_loss == new_sl
        assert pos.is_breakeven_ratcheted is True

        # Verify disk persistence
        engine_reloaded = TigerExecutionEngine(state_file=state_file)
        assert engine_reloaded.active_positions[pos.position_id].stop_loss == new_sl
        assert engine_reloaded.active_positions[pos.position_id].is_breakeven_ratcheted is True

        # 2. Test BUY position without explicit new_sl (auto breakeven + buffer)
        t1 = t0 + datetime.timedelta(minutes=2)
        mock_sig_buy = AbsorptionSignal(
            symbol="LINKUSDT", action="BUY", entry_trigger_price=Decimal("15.0000"),
            invalidation_stop_price=Decimal("14.7000"), cvd_zscore=Decimal("-2.4"),
            micro_price_skew_bps=Decimal("0.25"), ofi_score=Decimal("0.50"),
            wick_ratio=Decimal("0.60"), absorption_density=Decimal("0.85"),
            is_steamroller_vetoed=False, is_valid=True, reason="Test Long"
        )
        sig_buy = engine.create_signal_from_absorption(mock_sig_buy, atr_pct=Decimal("0.0100"), current_time_utc=t1)
        assert sig_buy is not None
        pos_buy = engine.fill_signal(sig_buy.signal_id, fill_price=Decimal("15.0000"), quantity=Decimal("10"), fill_time_utc=t1)
        
        success_buy = engine.ratchet_to_breakeven(pos_buy.position_id)
        assert success_buy is True
        expected_sl = Decimal("15.0000") * (Decimal("1") + Decimal("0.0022"))
        assert pos_buy.stop_loss == expected_sl
        assert pos_buy.is_breakeven_ratcheted is True

        # 3. Test non-existent position ID
        assert engine.ratchet_to_breakeven("NON_EXISTENT_ID") is False


def test_close_position_net_of_friction_win_truth():
    """Verify close_position evaluates is_win strictly NET of realistic 0.22% friction (no fake scratch wins)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        state_file = os.path.join(tmpdir, "tiger_net_win_state.json")
        engine = TigerExecutionEngine(state_file=state_file)
        t0 = datetime.datetime(2026, 11, 18, 8, 0, tzinfo=datetime.timezone.utc)

        mock_sig = AbsorptionSignal(
            symbol="EVAAUSDT", action="SELL", entry_trigger_price=Decimal("2.0000"),
            invalidation_stop_price=Decimal("2.0200"), cvd_zscore=Decimal("2.5"),
            micro_price_skew_bps=Decimal("-0.30"), ofi_score=Decimal("-0.55"),
            wick_ratio=Decimal("0.60"), absorption_density=Decimal("0.85"),
            is_steamroller_vetoed=False, is_valid=True, reason="Test Short"
        )
        sig = engine.create_signal_from_absorption(mock_sig, atr_pct=Decimal("0.0080"), current_time_utc=t0)
        assert sig is not None
        pos = engine.fill_signal(sig.signal_id, fill_price=Decimal("2.0000"), quantity=Decimal("50"), fill_time_utc=t0)

        # +0.10% gross favorable move (2.0000 -> 1.9980), but after 0.22% friction net is -0.12% -> MUST BE LOSS!
        res = engine.close_position(
            pos.position_id,
            exit_price=Decimal("1.9980"),
            exit_time_utc=t0 + datetime.timedelta(minutes=5),
            reason="STALL_SCRATCH",
            fee_friction_pct=Decimal("0.0022")
        )
        assert res["is_win"] is False
        assert engine.total_wins_count == 0
        assert engine.consecutive_losses == 1









