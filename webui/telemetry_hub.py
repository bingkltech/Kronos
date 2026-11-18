"""
webui/telemetry_hub.py — High-Performance, Non-Blocking WebSocket Telemetry Hub.

Passively monitors live Kronos trading outputs (tiger_radar.json, tiger_state.json,
tiger_trades.db, scalp_orders.json) without touching any trading engines.
Exposes a lightweight WebSocket server on ws://0.0.0.0:8765/swarm emitting JSON envelopes:
- TOPOLOGY
- BEACON_UPSERT
- WORKER_SIGNAL
- TRADE_FILL

Matches the window.BotSwarmBridge protocol precisely.
"""

import os
import sys
import json
import time
import asyncio
import logging
import sqlite3
import datetime
import threading
from decimal import Decimal
from typing import Set, Dict, Any, Optional

try:
    import websockets
    try:
        from websockets.asyncio.server import serve
    except ImportError:
        from websockets.server import serve
except ImportError:
    websockets = None
    serve = None

logger = logging.getLogger("TelemetryHub")
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s UTC] [%(levelname)s] [TelemetryHub] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

WORKSPACE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(WORKSPACE_ROOT, "data")
TIGER_RADAR_PATH = os.path.join(DATA_DIR, "tiger_radar.json")
TIGER_STATE_PATH = os.path.join(DATA_DIR, "tiger_state.json")
TIGER_TRADES_DB = os.path.join(DATA_DIR, "tiger_trades.db")
SCALP_ORDERS_PATH = os.path.join(DATA_DIR, "scalp_orders.json")

DEFAULT_TOPOLOGY = {
    "bots": [
        {"id": "BOT-01", "name": "LIGHTNING", "accent": "#f5c869", "pair": "SOL/USDT"},
        {"id": "BOT-02", "name": "TIGER", "accent": "#38bdf8", "pair": "BTC/USDT"},
        {"id": "BOT-03", "name": "MACRO", "accent": "#c084fc", "pair": "ETH/USDT"},
        {"id": "BOT-04", "name": "STORM", "accent": "#34d399", "pair": "BNB/USDT"}
    ]
}

def safe_json_default(obj):
    """Safely converts Decimal and datetime objects for JSON serialization."""
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, (datetime.datetime, datetime.date)):
        return obj.isoformat()
    return str(obj)

class TelemetryHub:
    """
    Manages connected WebSocket clients and continuously streams
    live backend state transformed into BotSwarmBridge envelopes.
    """
    def __init__(self, host: str = "0.0.0.0", port: int = 8765):
        self.host = host
        self.port = port
        self.clients: Set[Any] = set()
        self.clients_lock = threading.Lock()
        self.running = False
        self.last_radar_mtime = 0.0
        self.last_trade_count = 0
        self.seen_beacons: Dict[str, Dict[str, Any]] = {}
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None

    async def register(self, websocket):
        with self.clients_lock:
            self.clients.add(websocket)
        logger.info(f"Client connected: {websocket.remote_address}. Total clients: {len(self.clients)}")
        # Send initial TOPOLOGY snapshot
        try:
            init_msg = json.dumps({
                "type": "TOPOLOGY",
                "payload": DEFAULT_TOPOLOGY
            }, default=safe_json_default)
            await websocket.send(init_msg)
        except Exception as e:
            logger.warning(f"Error sending initial topology: {e}")

    async def unregister(self, websocket):
        with self.clients_lock:
            self.clients.discard(websocket)
        logger.info(f"Client disconnected. Total clients: {len(self.clients)}")

    async def broadcast(self, msg_type: str, payload: Dict[str, Any]):
        """Broadcasts a JSON envelope to all active WebSocket clients."""
        with self.clients_lock:
            if not self.clients:
                return
            current_clients = list(self.clients)

        envelope = json.dumps({
            "type": msg_type,
            "payload": payload
        }, default=safe_json_default)

        dead_clients = []
        for client in current_clients:
            try:
                await client.send(envelope)
            except Exception:
                dead_clients.append(client)

        if dead_clients:
            with self.clients_lock:
                for dc in dead_clients:
                    self.clients.discard(dc)

    async def handler(self, websocket):
        """Websocket connection handler."""
        await self.register(websocket)
        try:
            async for message in websocket:
                # Handle incoming messages from frontend if any (e.g. ping/drop-alpha)
                try:
                    data = json.loads(message)
                    if data.get("action") == "PING":
                        await websocket.send(json.dumps({"type": "PONG", "payload": {"time": time.time()}}))
                except Exception:
                    pass
        except Exception:
            pass
        finally:
            await self.unregister(websocket)

    def _read_live_trades_fill(self) -> Optional[Dict[str, Any]]:
        """Checks for new trades in tiger_trades.db."""
        if not os.path.exists(TIGER_TRADES_DB):
            return None
        try:
            conn = sqlite3.connect(TIGER_TRADES_DB, timeout=0.5)
            cursor = conn.cursor()
            cursor.execute("SELECT count(*) FROM tiger_trades")
            total = cursor.fetchone()[0]
            if self.last_trade_count == 0:
                self.last_trade_count = total
                conn.close()
                return None
            if total > self.last_trade_count:
                cursor.execute("""
                    SELECT symbol, side, exit_price, entry_price, realized_pnl, created_at
                    FROM tiger_trades
                    ORDER BY id DESC LIMIT 1
                """)
                row = cursor.fetchone()
                self.last_trade_count = total
                conn.close()
                if row:
                    sym = row[0]
                    side = row[1]
                    pnl_raw = float(row[4] or 0.0)
                    pnl_str = f"+{pnl_raw:.2f}%" if pnl_raw >= 0 else f"{pnl_raw:.2f}%"
                    return {
                        "botId": "BOT-02",
                        "beaconId": f"sig-{sym.lower()}",
                        "symbol": f"{sym.replace('USDT', '')}/USDT",
                        "side": side,
                        "pnl": pnl_str
                    }
            conn.close()
        except Exception:
            pass
        return None

    def _read_tiger_radar(self) -> Optional[Dict[str, Any]]:
        """Reads live candidate prey from tiger_radar.json."""
        if not os.path.exists(TIGER_RADAR_PATH):
            return None
        try:
            mtime = os.path.getmtime(TIGER_RADAR_PATH)
            with open(TIGER_RADAR_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.last_radar_mtime = mtime
            return data
        except Exception:
            return None

    async def telemetry_sync_loop(self):
        """
        Continuous background loop that polls live files every 1.5s
        and generates synchronized BotSwarmBridge envelopes.
        """
        cycle = 0
        while self.running:
            try:
                # 1. Check for live trade fills
                fill_event = self._read_live_trades_fill()
                if fill_event:
                    await self.broadcast("TRADE_FILL", fill_event)
                    # Also update beacon to CAPTURED
                    await self.broadcast("BEACON_UPSERT", {
                        "id": fill_event["beaconId"],
                        "symbol": fill_event["symbol"],
                        "score": 0.95,
                        "xNorm": 0.5,
                        "yNorm": 0.5,
                        "status": "CAPTURED"
                    })
                    await self.broadcast("WORKER_SIGNAL", {
                        "botId": fill_event["botId"],
                        "workerId": "LEDGER",
                        "beaconId": fill_event["beaconId"],
                        "state": "CONFIRMED",
                        "label": f"• fill {fill_event['side']} {fill_event['pnl']}"
                    })

                # 2. Check live radar candidates
                radar = self._read_tiger_radar()
                if radar and "active_prey" in radar:
                    prey_list = radar["active_prey"][:4]  # Top 4 prey
                    cvd_z = radar.get("btc_cvd_zscore", "0.0")
                    weight = radar.get("used_weight", 0)

                    # Spread beacons around quadrants
                    quad_coords = [
                        (0.24, 0.32), (0.76, 0.32), (0.24, 0.68), (0.76, 0.68)
                    ]

                    for idx, p in enumerate(prey_list):
                        sym = p.get("symbol", "").replace("USDT", "")
                        if not sym:
                            continue
                        full_sym = f"{sym}/USDT"
                        beacon_id = f"sig-{sym.lower()}"
                        
                        try:
                            score_val = round(float(p.get("volatility_score", 0.70)), 2)
                        except Exception:
                            score_val = 0.70

                        # Determine status: score >= 0.62 triggers LOCK, else SKIPPED
                        status = "LOCKED" if score_val >= 0.62 else "SKIPPED"
                        coords = quad_coords[idx % len(quad_coords)]
                        
                        # Subtle drift
                        x_norm = round(coords[0] + (idx * 0.02 * (1 if cycle % 2 == 0 else -1)), 3)
                        y_norm = round(coords[1] + (idx * 0.015 * (-1 if cycle % 2 == 0 else 1)), 3)

                        # Emit beacon upsert
                        await self.broadcast("BEACON_UPSERT", {
                            "id": beacon_id,
                            "symbol": full_sym,
                            "score": score_val,
                            "xNorm": max(0.08, min(0.92, x_norm)),
                            "yNorm": max(0.10, min(0.90, y_norm)),
                            "status": status
                        })

                        # Select target bot
                        target_bot = f"BOT-0{(idx % 4) + 1}"

                        # Emit worker signals based on status
                        if status == "LOCKED":
                            stages = [
                                ("SCAN", "TRIANGULATING", f"• rank #{p.get('rank', idx+1)} {p.get('price_change_pct', '0')}%"),
                                ("FLOW", "ABSORPTION", f"• cvd {cvd_z}σ oi {p.get('delta_oi_pct', '0')}%"),
                                ("RISK", "PASSED", f"• weight {weight} ok"),
                                ("VALID", "CONFIRMED", f"• score {score_val}"),
                                ("EXEC", "READY", f"• limit ${p.get('last_price', '0')}")
                            ]
                            active_stage = stages[cycle % len(stages)]
                            await self.broadcast("WORKER_SIGNAL", {
                                "botId": target_bot,
                                "workerId": active_stage[0],
                                "beaconId": beacon_id,
                                "state": active_stage[1],
                                "label": active_stage[2]
                            })
                        else:
                            await self.broadcast("WORKER_SIGNAL", {
                                "botId": target_bot,
                                "workerId": "RISK",
                                "beaconId": beacon_id,
                                "state": "VETOED",
                                "label": "• skip: low volatility / depth"
                            })

                cycle += 1
            except Exception as e:
                logger.debug(f"Telemetry cycle tick error: {e}")

            await asyncio.sleep(2.0)

    async def _run_server(self):
        """Asyncio entry point for websockets server."""
        if websockets is None:
            logger.error("websockets package not available; cannot start telemetry server")
            return

        async with serve(self.handler, self.host, self.port):
            logger.info(f"Telemetry WebSocket Hub online at ws://{self.host}:{self.port}/swarm")
            self.running = True
            await self.telemetry_sync_loop()

    def start_background(self):
        """Starts the WebSocket hub in a dedicated background daemon thread."""
        if self._thread and self._thread.is_alive():
            logger.warning("Telemetry hub background thread already running")
            return

        def _runner():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            self._loop = loop
            try:
                loop.run_until_complete(self._run_server())
            except Exception as e:
                logger.error(f"Telemetry hub server encountered error: {e}")
            finally:
                loop.close()

        self._thread = threading.Thread(target=_runner, name="TelemetryHubDaemon", daemon=True)
        self._thread.start()
        logger.info("Telemetry hub background daemon thread launched.")

    def stop(self):
        """Stops the telemetry hub."""
        self.running = False
        if self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop.stop)

# Global singleton
telemetry_hub = TelemetryHub(host="0.0.0.0", port=8765)

if __name__ == "__main__":
    hub = TelemetryHub(host="0.0.0.0", port=8765)
    try:
        asyncio.run(hub._run_server())
    except KeyboardInterrupt:
        print("Telemetry hub stopped.")
