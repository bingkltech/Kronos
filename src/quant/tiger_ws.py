"""
src/quant/tiger_ws.py — Real-Time Multiplex WebSocket Engine & BTC Macro Tide Streamer.

Maintains persistent zero-weight WebSocket connections to Binance USD(S)-M Futures:
1. Top 5 Hot Prey streams: <symbol>@aggTrade + <symbol>@depth5@100ms
2. Sovereign BTC Macro Gate stream: btcusdt@aggTrade
3. Sub-second tick ingestion directly into SymbolOrderflowTracker instances.
4. Auto-reconnection with exponential backoff and zero REST IP rate consumption.
5. Strict AGENTS.md Invariant 1 (Zero Float Financial Math with Decimal).
"""

import asyncio
from collections import deque
from decimal import Decimal
import json
import logging
import threading
import time
from typing import Any, Callable, Deque, Dict, List, Optional, Set, Tuple
import websockets

from src.quant.tiger_config import TigerMasterConfig, DEFAULT_TIGER_CONFIG
from src.quant.tiger_orderflow import (
    SymbolOrderflowTracker,
    AggTradeEvent,
    DepthSnapshot,
)
from src.quant.crypto_index_engine import OrderBookMicrostructure

logger = logging.getLogger("kronos.tiger_ws")


class TigerWebSocketManager:
    """
    Sub-second multiplex WebSocket listener for Strategy #3 (Stalking Tiger).
    Runs asynchronously on a background worker thread.
    """
    BASE_WS_URL = "wss://fstream.binance.com/stream"

    def __init__(
        self,
        config: Optional[TigerMasterConfig] = None,
        initial_symbols: Optional[List[str]] = None
    ):
        self.cfg = config or DEFAULT_TIGER_CONFIG
        self.active_symbols: Set[str] = set(initial_symbols or [])
        self.trackers: Dict[str, SymbolOrderflowTracker] = {
            s: SymbolOrderflowTracker(s, self.cfg.orderflow) for s in self.active_symbols
        }
        self.btc_tracker = SymbolOrderflowTracker("BTCUSDT", self.cfg.orderflow, max_trades_buffer=5000)
        self.btc_trades_1m: Deque[Tuple[int, Decimal]] = deque(maxlen=2000) # (timestamp_ms, price)

        self._lock = threading.Lock()
        self._is_running = False
        self._thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._ws = None
        self._reconnect_delay = 1.0
        self.total_ticks_received = 0
        self.last_tick_time = 0.0

    def update_symbols(self, new_symbols: List[str]) -> None:
        """Dynamically update active prey target symbols and purge memory of evicted trackers."""
        with self._lock:
            incoming = set(new_symbols)
            if incoming != self.active_symbols:
                self.active_symbols = incoming
                # Add trackers for new symbols without destroying existing tracker history
                for s in incoming:
                    if s not in self.trackers:
                        self.trackers[s] = SymbolOrderflowTracker(s, self.cfg.orderflow)

                # AWS Memory Hygiene: Purge dead trackers of symbols that are no longer monitored
                dead_symbols = [s for s in list(self.trackers.keys()) if s not in incoming and s != "BTCUSDT"]
                for s in dead_symbols:
                    del self.trackers[s]
                if dead_symbols:
                    logger.info(f"[AWS PURGE] Flushed {len(dead_symbols)} dead trackers from memory: {dead_symbols}")
                logger.info(f"[TIGER WS] Updated prey pool to {list(self.active_symbols)}")

    def get_tracker(self, symbol: str) -> Optional[SymbolOrderflowTracker]:
        """Safely fetch the active SymbolOrderflowTracker for a symbol."""
        with self._lock:
            return self.trackers.get(symbol)

    def get_btc_macro_pulse(self) -> Tuple[Decimal, Decimal]:
        """
        Computes real-time BTC 1-minute return and CVD delta z-score.
        Returns:
            (btc_1m_return, btc_cvd_zscore)
        """
        with self._lock:
            _, cvd_z = self.btc_tracker.compute_cvd_metrics(window_seconds=60)

            if len(self.btc_trades_1m) < 2:
                return Decimal("0"), cvd_z

            latest_ms = self.btc_trades_1m[-1][0]
            cutoff_ms = latest_ms - 60000

            # Find oldest trade within the 1-minute window
            recent = [p for t_ms, p in self.btc_trades_1m if t_ms >= cutoff_ms]
            if not recent or len(recent) < 2:
                return Decimal("0"), cvd_z

            p_start = recent[0]
            p_curr = recent[-1]

            if p_start <= Decimal("0"):
                return Decimal("0"), cvd_z

            ret_1m = (p_curr - p_start) / p_start
            return ret_1m, cvd_z

    def get_microstructure_snapshot(self, symbol: str) -> Optional[OrderBookMicrostructure]:
        """Thread-safe snapshot of order book microstructure from active WebSocket stream."""
        with self._lock:
            tracker = self.btc_tracker if symbol.upper() == "BTCUSDT" else self.trackers.get(symbol.upper())
            if tracker is not None:
                return tracker.get_order_book_microstructure()
            return None

    def _build_stream_url(self) -> str:
        """Build multiplex stream URL for all active prey + BTC."""
        streams = ["btcusdt@aggTrade", "btcusdt@depth5@100ms"]
        with self._lock:
            for s in sorted(self.active_symbols):
                low_s = s.lower()
                streams.append(f"{low_s}@aggTrade")
                streams.append(f"{low_s}@depth5@100ms")

        stream_path = "/".join(streams)
        return f"{self.BASE_WS_URL}?streams={stream_path}"

    def _handle_agg_trade(self, symbol: str, data: Dict[str, Any]) -> None:
        """Route trade execution print to the corresponding tracker."""
        trade_id = int(data.get("a", 0))
        price = Decimal(str(data.get("p", "0")))
        quantity = Decimal(str(data.get("q", "0")))
        is_buyer_maker = bool(data.get("m", False))
        timestamp_ms = int(data.get("T", 0))

        if symbol == "BTCUSDT":
            self.btc_tracker.process_agg_trade(trade_id, price, quantity, is_buyer_maker, timestamp_ms)
            self.btc_trades_1m.append((timestamp_ms, price))
            return

        with self._lock:
            tracker = self.trackers.get(symbol)
            if tracker:
                tracker.process_agg_trade(trade_id, price, quantity, is_buyer_maker, timestamp_ms)

    def _handle_depth_update(self, symbol: str, data: Dict[str, Any]) -> None:
        """Route top-of-book depth snapshot to the corresponding tracker."""
        bids = data.get("b", [])
        asks = data.get("a", [])
        if not bids or not asks:
            return

        best_bid = Decimal(str(bids[0][0]))
        best_bid_qty = Decimal(str(bids[0][1]))
        best_ask = Decimal(str(asks[0][0]))
        best_ask_qty = Decimal(str(asks[0][1]))
        timestamp_ms = int(data.get("E", int(time.time() * 1000)))

        with self._lock:
            tracker = self.btc_tracker if symbol == "BTCUSDT" else self.trackers.get(symbol)
            if tracker:
                tracker.process_depth_update(
                    best_bid=best_bid,
                    best_bid_qty=best_bid_qty,
                    best_ask=best_ask,
                    best_ask_qty=best_ask_qty,
                    timestamp_ms=timestamp_ms,
                    raw_bids=bids,
                    raw_asks=asks
                )

    async def _ws_loop(self) -> None:
        """Main async resilient WebSocket streaming loop."""
        while self._is_running:
            url = self._build_stream_url()
            try:
                logger.info(f"[TIGER WS] Connecting to multiplex stream with {len(self.active_symbols)} targets...")
                async with websockets.connect(url, ping_interval=20, ping_timeout=10) as ws:
                    self._ws = ws
                    self._reconnect_delay = 1.0
                    logger.info("[TIGER WS] Connected! Sub-second orderflow stream active.")

                    # Keep checking if the symbol list changed; if so, reconnect with updated streams
                    current_active_snapshot = set(self.active_symbols)

                    while self._is_running:
                        # Check if active symbols changed
                        with self._lock:
                            if set(self.active_symbols) != current_active_snapshot:
                                logger.info("[TIGER WS] Active prey changed, reconnecting to new streams...")
                                break

                        try:
                            raw_msg = await asyncio.wait_for(ws.recv(), timeout=5.0)
                        except asyncio.TimeoutError:
                            # Send ping to ensure alive
                            continue

                        self.total_ticks_received += 1
                        self.last_tick_time = time.time()

                        try:
                            payload = json.loads(raw_msg)
                            stream_name = payload.get("stream", "")
                            data = payload.get("data", {})

                            # Determine symbol from stream name (e.g. 'solusdt@aggTrade')
                            parts = stream_name.split("@")
                            if len(parts) == 2:
                                sym = parts[0].upper()
                                stream_type = parts[1]

                                if stream_type == "aggTrade":
                                    self._handle_agg_trade(sym, data)
                                elif stream_type.startswith("depth"):
                                    self._handle_depth_update(sym, data)
                        except Exception as e:
                            logger.error(f"[TIGER WS] Error processing message: {e}")

            except (websockets.ConnectionClosed, Exception) as e:
                if not self._is_running:
                    break
                logger.warning(f"[TIGER WS] Stream disconnected: {e}. Reconnecting in {self._reconnect_delay:.1f}s...")
                await asyncio.sleep(self._reconnect_delay)
                self._reconnect_delay = min(30.0, self._reconnect_delay * 1.5)

    def start(self) -> None:
        """Start the WebSocket manager on a background thread."""
        if self._is_running:
            return
        self._is_running = True

        def _thread_target():
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            self._loop.run_until_complete(self._ws_loop())

        self._thread = threading.Thread(target=_thread_target, name="TigerWebSocketThread", daemon=True)
        self._thread.start()
        logger.info("[TIGER WS] Background WebSocket worker thread started.")

    def stop(self) -> None:
        """Stop the WebSocket manager cleanly."""
        self._is_running = False
        if self._loop:
            self._loop.stop()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        logger.info("[TIGER WS] WebSocket manager stopped.")
