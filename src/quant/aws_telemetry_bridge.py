"""
AWS Telemetry Bridge — Zero-Whitelist Remote Execution & Telemetry Tap
Author: Kronos Lead Trade Quant Designer

Maintains a secure, self-healing SSH encrypted tunnel (Port 7072 -> AWS EC2 7070).
Allows local PC to display real-time Binance Futures account telemetry, positions,
and Stalking Tiger Radar without requiring the local PC IP to be whitelisted on Binance.
All private Binance orders and account calls are executed by AWS EC2 (Whitelisted Static IP).
"""

import os
import sys
import time
import json
import logging
import threading
import subprocess
import urllib.request
import urllib.error

logger = logging.getLogger("AWSTelemetryBridge")
if not logger.handlers:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("[%(asctime)s] [AWS-TAP] %(levelname)s - %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

DEFAULT_AWS_HOST = "13.63.158.94"
DEFAULT_AWS_USER = "ec2-user"
DEFAULT_AWS_KEY = r"F:\012D_TRADE\Kalshi Simulator\kalshi_aws_key.pem"
LOCAL_TUNNEL_PORT = 7072
REMOTE_TARGET_PORT = 7070


class AWSTelemetryBridge:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(AWSTelemetryBridge, cls).__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self, key_path: str = DEFAULT_AWS_KEY, host: str = DEFAULT_AWS_HOST, user: str = DEFAULT_AWS_USER):
        if self._initialized:
            return
        self.key_path = os.getenv("KRONOS_AWS_KEY", key_path)
        self.host = os.getenv("KRONOS_AWS_HOST", host)
        self.user = os.getenv("KRONOS_AWS_USER", user)
        self.local_port = LOCAL_TUNNEL_PORT
        self.remote_port = REMOTE_TARGET_PORT

        self._ssh_proc = None
        self._running = False
        self._tunnel_healthy = False
        self._last_health_check = 0.0
        self._cached_live_status = None
        self._cached_tiger_radar = None
        self._cached_tiger_state = None
        self._cached_live_trades = []
        self._thread = None
        self._sync_thread = None
        self._initialized = True

    def start(self):
        """Starts the background SSH tunnel watchdog and sync worker."""
        if self._running:
            return
        if not os.path.exists(self.key_path):
            logger.warning("AWS SSH Key not found at %s. Remote tap will be disabled.", self.key_path)
            return

        self._running = True
        self._thread = threading.Thread(target=self._watchdog_loop, daemon=True, name="AWSTapWatchdog")
        self._thread.start()

        self._sync_thread = threading.Thread(target=self._telemetry_sync_loop, daemon=True, name="AWSTelemetrySync")
        self._sync_thread.start()
        logger.info("AWS Telemetry Tap supervisor started for %s@%s (Local Port %d -> Remote %d)",
                    self.user, self.host, self.local_port, self.remote_port)

    def stop(self):
        """Stops the tunnel and background threads."""
        self._running = False
        if self._ssh_proc:
            try:
                self._ssh_proc.terminate()
            except Exception:
                pass
            self._ssh_proc = None
        self._tunnel_healthy = False

    def is_connected(self) -> bool:
        """Returns True if the encrypted SSH tunnel is actively responding."""
        return self._tunnel_healthy

    def _watchdog_loop(self):
        """Continuously supervises the SSH tunnel process."""
        while self._running:
            try:
                if self._ssh_proc is None or self._ssh_proc.poll() is not None:
                    # Tunnel died or not started: spawn it
                    self._tunnel_healthy = False
                    cmd = [
                        "ssh",
                        "-i", self.key_path,
                        "-o", "StrictHostKeyChecking=no",
                        "-o", "ServerAliveInterval=15",
                        "-o", "ServerAliveCountMax=3",
                        "-o", "ExitOnForwardFailure=yes",
                        "-N",
                        "-L", f"{self.local_port}:localhost:{self.remote_port}",
                        f"{self.user}@{self.host}"
                    ]
                    logger.info("Spawning SSH tunnel to %s...", self.host)
                    self._ssh_proc = subprocess.Popen(
                        cmd,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        stdin=subprocess.DEVNULL
                    )
                    time.sleep(1.5)

                # Check HTTP health over tunnel
                self._tunnel_healthy = self._probe_health()
            except Exception as e:
                self._tunnel_healthy = False
                logger.error("Tunnel watchdog exception: %s", e)

            time.sleep(3.0)

    def _probe_health(self) -> bool:
        """Probes the tunnel endpoint to ensure bidirectional communication."""
        try:
            url = f"http://127.0.0.1:{self.local_port}/api/health"
            req = urllib.request.Request(url, headers={"User-Agent": "Kronos-Tap/1.0"})
            with urllib.request.urlopen(req, timeout=1.8) as resp:
                if resp.status == 200:
                    return True
        except Exception:
            pass
        return False

    def _telemetry_sync_loop(self):
        """Periodically polls live telemetry from AWS EC2 and caches it locally."""
        while self._running:
            if self._tunnel_healthy:
                try:
                    # 1. Fetch live status (balance, positions, autopilot)
                    self._cached_live_status = self.fetch_remote_json("/api/live/status")

                    # 2. Fetch tiger radar
                    radar_data = self.fetch_remote_json("/api/tiger/radar")
                    if radar_data and radar_data.get("success"):
                        self._cached_tiger_radar = radar_data.get("radar", {})
                        # Also sync to local data/tiger_radar.json for offline resilience
                        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
                        local_rf = os.path.join(project_root, "data", "tiger_radar.json")
                        try:
                            with open(local_rf, "w", encoding="utf-8") as f:
                                json.dump(self._cached_tiger_radar, f, indent=2)
                        except Exception:
                            pass

                    # 3. Fetch tiger state and sync to local data/tiger_state.json
                    state_data = self.fetch_remote_json("/api/tiger/state")
                    if state_data and state_data.get("success"):
                        self._cached_tiger_state = state_data.get("state", {})
                        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
                        local_sf = os.path.join(project_root, "data", "tiger_state.json")
                        try:
                            with open(local_sf, "w", encoding="utf-8") as f:
                                json.dump(self._cached_tiger_state, f, indent=2)
                        except Exception:
                            pass

                    # 4. Fetch live trades for local cache
                    trades_data = self.fetch_remote_json("/api/live/trades?limit=50")
                    if trades_data and trades_data.get("success"):
                        self._cached_live_trades = trades_data.get("trades", [])
                except Exception as e:
                    logger.debug("Sync poll error: %s", e)
            time.sleep(2.0)

    def fetch_remote_json(self, endpoint: str, timeout: float = 2.5) -> dict:
        """Fetches a JSON endpoint from EC2 over the local tunnel."""
        if not endpoint.startswith("/"):
            endpoint = "/" + endpoint
        url = f"http://127.0.0.1:{self.local_port}{endpoint}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Kronos-Tap/1.0"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                if resp.status == 200:
                    return json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            logger.debug("fetch_remote_json %s failed: %s", endpoint, e)
        return {}

    def post_remote_json(self, endpoint: str, payload: dict = None, timeout: float = 4.0) -> dict:
        """Dispatches a POST command to EC2 over the local tunnel."""
        if not endpoint.startswith("/"):
            endpoint = "/" + endpoint
        url = f"http://127.0.0.1:{self.local_port}{endpoint}"
        try:
            data_bytes = json.dumps(payload or {}).encode("utf-8")
            req = urllib.request.Request(url, data=data_bytes, headers={
                "User-Agent": "Kronos-Tap/1.0",
                "Content-Type": "application/json"
            })
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                if resp.status in (200, 201):
                    return json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            logger.error("post_remote_json %s failed: %s", endpoint, e)
            return {"success": False, "error": str(e)}
        return {"success": False, "error": "No response"}

    def get_live_account_summary(self) -> dict:
        """Returns the real-time live account data from AWS EC2."""
        if self._cached_live_status and "live_account" in self._cached_live_status:
            return self._cached_live_status.get("live_account", {})
        return {}

    def get_tiger_radar_data(self) -> dict:
        """Returns the real-time tiger radar data from AWS EC2."""
        return self._cached_tiger_radar or {}

    def get_live_trades(self, limit: int = 50) -> list:
        """Returns the real-time trade history from AWS EC2."""
        return (self._cached_live_trades or [])[:limit]

    def get_tiger_state(self) -> dict:
        """Returns real-time tiger worker state from AWS EC2."""
        return self._cached_tiger_state or {}


# Singleton helper instance
aws_bridge = AWSTelemetryBridge()
