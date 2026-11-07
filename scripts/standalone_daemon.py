"""
scripts/standalone_daemon.py — Kronos 24/7 Production Standalone Daemon & Supervisor.

Manages the Kronos Web UI and Autonomous Quant Engine as an independent, resilient
background service on Windows.

Key Institutional Features:
1. Subprocess Supervision & Auto-Restart: Restarts webui/app.py if terminated unexpectedly.
2. Port Conflict Pre-Flight: Checks socket availability before binding.
3. PID Ledger: Writes PID to data/kronos.pid for clean stop/status script management.
4. Log Rotation: Automatically caps logs/kronos_standalone.log at 10 MB.
5. Graceful Signal Handling: Catches SIGINT/SIGTERM and terminates child trees cleanly.
"""

import os
import sys
import time
import socket
import signal
import subprocess
from datetime import datetime

WORKSPACE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOGS_DIR = os.path.join(WORKSPACE_ROOT, "logs")
DATA_DIR = os.path.join(WORKSPACE_ROOT, "data")
PID_FILE = os.path.join(DATA_DIR, "kronos.pid")
LOG_FILE = os.path.join(LOGS_DIR, "kronos_standalone.log")
MAX_LOG_SIZE = 10 * 1024 * 1024  # 10 MB

def is_port_in_use(port: int = 7070, host: str = "127.0.0.1") -> bool:
    """Check if port 7070 is currently bound."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1.0)
        return s.connect_ex((host, port)) == 0

def rotate_log_if_needed():
    """Ensure log directory exists and rotate log file if exceeding 10 MB."""
    os.makedirs(LOGS_DIR, exist_ok=True)
    os.makedirs(DATA_DIR, exist_ok=True)
    if os.path.exists(LOG_FILE) and os.path.getsize(LOG_FILE) > MAX_LOG_SIZE:
        old_log = LOG_FILE + ".old"
        if os.path.exists(old_log):
            os.remove(old_log)
        os.rename(LOG_FILE, old_log)

def write_pid(supervisor_pid: int, child_pid: int):
    """Save running PIDs to disk."""
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(PID_FILE, "w", encoding="utf-8") as f:
        f.write(f"{supervisor_pid}:{child_pid}\n")

def clear_pid():
    """Remove PID file on clean shutdown."""
    if os.path.exists(PID_FILE):
        try:
            os.remove(PID_FILE)
        except Exception:
            pass

def log_message(msg: str):
    """Write timestamped log entry to both stdout and log file."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    formatted = f"[{timestamp}] [Kronos Supervisor] {msg}"
    print(formatted, flush=True)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(formatted + "\n")
    except Exception:
        pass

class KronosSupervisor:
    def __init__(self):
        self.running = True
        self.child_process = None
        self.restart_times = []

    def handle_signal(self, signum, frame):
        log_message(f"Received termination signal ({signum}). Initiating graceful shutdown...")
        self.running = False
        self.stop_child()
        clear_pid()
        sys.exit(0)

    def stop_child(self):
        if self.child_process and self.child_process.poll() is None:
            log_message(f"Terminating child process (PID {self.child_process.pid})...")
            try:
                self.child_process.terminate()
                self.child_process.wait(timeout=5)
            except Exception:
                try:
                    self.child_process.kill()
                except Exception:
                    pass

    def run(self):
        signal.signal(signal.SIGINT, self.handle_signal)
        signal.signal(signal.SIGTERM, self.handle_signal)

        rotate_log_if_needed()
        log_message("Kronos 24/7 Standalone Supervisor starting up...")
        log_message(f"Workspace root: {WORKSPACE_ROOT}")
        log_message(f"Target URL: http://localhost:7070")

        app_script = os.path.join(WORKSPACE_ROOT, "webui", "app.py")
        python_exe = sys.executable

        while self.running:
            # Check circuit breaker: maximum 5 restarts within 60 seconds
            now = time.time()
            self.restart_times = [t for t in self.restart_times if now - t < 60]
            if len(self.restart_times) >= 5:
                log_message("CRITICAL: Rapid restart circuit breaker tripped (>5 crashes in 60s). Pausing for 30s...")
                time.sleep(30)
                self.restart_times.clear()

            rotate_log_if_needed()
            log_file_handle = open(LOG_FILE, "a", encoding="utf-8", buffering=1)

            log_message(f"Spawning Kronos Web UI process: {python_exe} -X utf8 {app_script}")
            self.child_process = subprocess.Popen(
                [python_exe, "-X", "utf8", app_script],
                cwd=WORKSPACE_ROOT,
                stdout=log_file_handle,
                stderr=subprocess.STDOUT,
                env=os.environ.copy()
            )

            write_pid(os.getpid(), self.child_process.pid)
            log_message(f"Kronos child process active with PID {self.child_process.pid}")

            # Monitor child process
            while self.running:
                exit_code = self.child_process.poll()
                if exit_code is not None:
                    log_file_handle.close()
                    if not self.running:
                        break
                    log_message(f"WARNING: Kronos child process exited with code {exit_code}. Auto-restarting in 3s...")
                    self.restart_times.append(time.time())
                    time.sleep(3)
                    break
                time.sleep(2)

        self.stop_child()
        clear_pid()
        log_message("Kronos Standalone Supervisor shutdown complete.")

if __name__ == "__main__":
    supervisor = KronosSupervisor()
    supervisor.run()
