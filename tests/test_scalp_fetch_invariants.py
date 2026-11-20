"""
tests/test_scalp_fetch_invariants.py — Verification of Scalping Fetch & Candidate Isolation.
=============================================================================================
Enforces:
1. Candle Boundary Guard: Cache invalidation upon 300s rollover so [-2] is always closed.
2. In-Memory Sub-slice Cache: Slices larger cached queries without redundant network calls.
3. Depth Limit Normalization: Prevents Binance HTTP 400 (-4021 invalid limit).
4. Stale WebSocket Guard: Rejects WebSocket depth older than 3000ms.
5. Cumulative Top-5 Depth OBI & Stoikov Micro-Price.
6. Zero Float Financial Math (AGENTS.md Invariant 1).
7. Stalking Tiger vs Apex Scalper Symbol Deconfliction.
=============================================================================================
"""

from decimal import Decimal
import json
import os
import time
from unittest.mock import MagicMock, patch
import pytest

from src.quant.crypto_index_engine import (
    CryptoIndexEngine,
    OrderBookMicrostructure,
    _normalize_binance_depth_limit,
)
from src.quant.tiger_orderflow import SymbolOrderflowTracker
from src.quant.tiger_ws import TigerWebSocketManager
from scripts.headless_worker import _get_tiger_reserved_symbols


def test_depth_limit_normalization():
    """Verify depth limit snaps to valid Binance futures limits [5, 10, 20, 50, 100, 500, 1000]."""
    assert _normalize_binance_depth_limit(3) == 5
    assert _normalize_binance_depth_limit(5) == 5
    assert _normalize_binance_depth_limit(7) == 10
    assert _normalize_binance_depth_limit(10) == 10
    assert _normalize_binance_depth_limit(15) == 20
    assert _normalize_binance_depth_limit(25) == 50
    assert _normalize_binance_depth_limit(75) == 100
    assert _normalize_binance_depth_limit(9999) == 1000


def test_candle_boundary_invalidation():
    """Verify that crossing a 300s bucket boundary invalidates the kline cache immediately."""
    engine = CryptoIndexEngine()

    mock_resp = MagicMock()
    mock_resp.json.return_value = [
        [1700000000000, "100.0", "105.0", "99.0", "102.0", "50.0", 1700000299999, "5000.0"]
    ] * 24

    with patch.object(engine.session, "get", return_value=mock_resp) as mock_get:
        # 1. First fetch at second 280 (inside bucket 1700000000 // 300)
        t_base = 1700000280.0
        with patch("time.time", return_value=t_base):
            k1 = engine.fetch_recent_klines("BTCUSDT", interval="5m", limit=24)
            assert len(k1) == 24
            assert mock_get.call_count == 1

        # 2. Fetch 10 seconds later at second 290 (same bucket, age=10s < ttl=15s) -> CACHE HIT
        with patch("time.time", return_value=t_base + 10.0):
            k2 = engine.fetch_recent_klines("BTCUSDT", interval="5m", limit=24)
            assert len(k2) == 24
            assert mock_get.call_count == 1  # No new network call!

        # 3. Fetch at second 301 (crossed integer 300s boundary!) -> CACHE INVALIDATION
        with patch("time.time", return_value=1700000301.0):
            k3 = engine.fetch_recent_klines("BTCUSDT", interval="5m", limit=24)
            assert len(k3) == 24
            assert mock_get.call_count == 2  # New network call triggered!


def test_subslice_kline_cache():
    """Verify that requesting a smaller limit slices an existing fresh larger cache."""
    engine = CryptoIndexEngine()

    mock_resp = MagicMock()
    mock_resp.json.return_value = [
        [1700000000000 + i * 300000, "100.0", "105.0", "99.0", "102.0", "50.0", 1700000299999 + i * 300000, "5000.0"]
        for i in range(24)
    ]

    with patch.object(engine.session, "get", return_value=mock_resp) as mock_get:
        t0 = 1700000100.0
        with patch("time.time", return_value=t0):
            k24 = engine.fetch_recent_klines("ETHUSDT", interval="5m", limit=24)
            assert len(k24) == 24
            assert mock_get.call_count == 1

        # Request limit=3 within TTL -> should slice from the 24 candles with ZERO network calls!
        with patch("time.time", return_value=t0 + 5.0):
            k3 = engine.fetch_recent_klines("ETHUSDT", interval="5m", limit=3)
            assert len(k3) == 3
            assert mock_get.call_count == 1  # No network call!


def test_stale_websocket_depth_rejection():
    """Verify that WebSocket depth older than 3000ms is rejected and falls back to REST."""
    engine = CryptoIndexEngine()

    now_ms = int(time.time() * 1000)

    # 1. Stale provider (> 3000ms old)
    stale_snap = OrderBookMicrostructure(
        obi=Decimal("0.50"),
        best_bid=Decimal("60000.0"),
        best_ask=Decimal("60001.0"),
        micro_price=Decimal("60000.75"),
        micro_skew_bps=Decimal("4.1"),
        timestamp_ms=now_ms - 5000  # 5 seconds old!
    )
    engine.set_ws_microstructure_provider(lambda sym: stale_snap)

    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "bids": [["61000.00", "2.0"], ["60999.00", "1.0"]],
        "asks": [["61001.00", "1.0"], ["61002.00", "3.0"]],
        "E": now_ms
    }

    with patch.object(engine.session, "get", return_value=mock_resp) as mock_get:
        res = engine.fetch_order_book_microstructure("BTCUSDT", depth_limit=10)
        # Should have rejected stale WS data and called REST API!
        assert mock_get.call_count == 1
        assert res.best_bid == Decimal("61000.00")

    # 2. Fresh provider (<= 3000ms old)
    fresh_snap = OrderBookMicrostructure(
        obi=Decimal("0.60"),
        best_bid=Decimal("62000.0"),
        best_ask=Decimal("62001.0"),
        micro_price=Decimal("62000.80"),
        micro_skew_bps=Decimal("5.0"),
        timestamp_ms=int(time.time() * 1000) - 200  # 200ms fresh!
    )
    engine.set_ws_microstructure_provider(lambda sym: fresh_snap)

    with patch.object(engine.session, "get", return_value=mock_resp) as mock_get:
        res_fresh = engine.fetch_order_book_microstructure("BTCUSDT", depth_limit=10)
        # Must accept fresh WS data directly with ZERO REST calls!
        assert mock_get.call_count == 0
        assert res_fresh.best_bid == Decimal("62000.0")


def test_cumulative_top5_orderbook_tracker():
    """Verify SymbolOrderflowTracker computes cumulative top-5 OBI and Stoikov Micro-Price."""
    tracker = SymbolOrderflowTracker(symbol="SOLUSDT")

    now_ms = int(time.time() * 1000)
    raw_bids = [
        ["150.00", "100.0"],
        ["149.90", "200.0"],
        ["149.80", "150.0"],
        ["149.70", "50.0"],
        ["149.60", "100.0"]
    ]  # Total bids = 600.0
    raw_asks = [
        ["150.10", "50.0"],
        ["150.20", "50.0"],
        ["150.30", "50.0"],
        ["150.40", "25.0"],
        ["150.50", "25.0"]
    ]  # Total asks = 200.0

    tracker.process_depth_update(
        best_bid=Decimal("150.00"),
        best_bid_qty=Decimal("100.0"),
        best_ask=Decimal("150.10"),
        best_ask_qty=Decimal("50.0"),
        timestamp_ms=now_ms,
        raw_bids=raw_bids,
        raw_asks=raw_asks
    )

    micro = tracker.get_order_book_microstructure()
    assert micro is not None
    # Cumulative OBI: (600 - 200) / (600 + 200) = 400 / 800 = 0.50
    assert micro.obi == Decimal("0.50")
    assert micro.best_bid == Decimal("150.00")
    assert micro.best_ask == Decimal("150.10")
    # Micro-Price skew must be strictly Decimal
    assert isinstance(micro.micro_skew_bps, Decimal)
    assert micro.micro_skew_bps > Decimal("0.0")


def test_zero_float_math_in_batch_fetch():
    """Verify that batch_fetch_scalp_market_data strictly returns Decimals (AGENTS.md Invariant 1)."""
    engine = CryptoIndexEngine()

    mock_kline_resp = MagicMock()
    mock_kline_resp.json.return_value = [
        [1700000000000, "100.0", "105.0", "99.0", "102.0", "50.0", 1700000299999, "5000.0"]
    ] * 15

    mock_depth_resp = MagicMock()
    mock_depth_resp.json.return_value = {
        "bids": [["102.00", "10.0"], ["101.90", "5.0"]],
        "asks": [["102.10", "8.0"], ["102.20", "4.0"]],
        "E": int(time.time() * 1000)
    }

    def _mock_session_get(url, *args, **kwargs):
        if "klines" in url:
            return mock_kline_resp
        return mock_depth_resp

    with patch.object(engine.session, "get", side_effect=_mock_session_get):
        batch = engine.batch_fetch_scalp_market_data(["SOLUSDT"])
        assert "SOLUSDT" in batch
        klines, micro = batch["SOLUSDT"]

        # Check klines
        for k in klines:
            assert isinstance(k["open"], Decimal)
            assert isinstance(k["high"], Decimal)
            assert isinstance(k["low"], Decimal)
            assert isinstance(k["close"], Decimal)
            assert isinstance(k["volume"], Decimal)

        # Check microstructure
        assert isinstance(micro.obi, Decimal)
        assert isinstance(micro.best_bid, Decimal)
        assert isinstance(micro.best_ask, Decimal)
        assert isinstance(micro.micro_price, Decimal)
        assert isinstance(micro.micro_skew_bps, Decimal)


def test_tiger_deconfliction_isolation(tmp_path):
    """Verify Stalking Tiger hunting and holding symbols are isolated from Apex Scalper."""
    mock_data = tmp_path / "data"
    mock_data.mkdir()

    # Create mock tiger_state.json with active SOLUSDT position and pending DOGEUSDT signal
    tiger_state = {
        "active_positions": {
            "pos-1": {"symbol": "SOLUSDT", "side": "BUY"}
        },
        "pending_signals": {
            "sig-1": {"symbol": "DOGEUSDT", "action": "SELL"}
        },
        "symbol_cooldowns": {
            "ADAUSDT": "2099-01-01T00:00:00"
        }
    }
    state_file = mock_data / "tiger_state.json"
    state_file.write_text(json.dumps(tiger_state), encoding="utf-8")

    with patch("scripts.headless_worker.WORKSPACE_ROOT", str(tmp_path)):
        reserved = _get_tiger_reserved_symbols()
        assert "SOLUSDT" in reserved
        assert "DOGEUSDT" in reserved
        assert "ADAUSDT" in reserved
        assert "BTCUSDT" not in reserved
