"""
src/quant/anti_bloat.py — Autonomous 24/7 Anti-Bloat & Self-Pruning Hygiene Engine
===================================================================================
Continuously monitors and protects system resources across Local PC and AWS EC2:
1. Aligned to Data Fetching: Micro-pruning of in-memory kline and orderbook depth caches.
2. Multi-Level Bloat Detector:
   - Level 0 (Normal): Periodic in-memory cache eviction (300s TTL).
   - Level 1 (Warning): Log files approaching threshold (>3MB) or RAM approaching ceiling.
   - Level 2 (Critical Breach): Immediate autonomous cleanse of oversized logs, orphaned buffers,
     stale CSVs, fragmented SQLite WALs, and JSON state arrays.
3. Strict AGENTS.md Invariants:
   - Invariant 1: Zero float financial math.
   - Invariant 5: Token & Context Bloat Hygiene (Zero Blackhole Credit Burning).
   - Strict Whitelist: Mission-critical state files (lessons.db, tiger_state.json, etc.) are IMMUTABLE.
===================================================================================
"""

from dataclasses import dataclass, field
import datetime
import gc
import json
import logging
import os
import shutil
import sqlite3
import sys
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

logger = logging.getLogger("kronos.anti_bloat")

# Workspace root discovery
WORKSPACE_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
DATA_DIR = os.path.join(WORKSPACE_ROOT, "data")
LOGS_DIR = os.path.join(WORKSPACE_ROOT, "logs")

# Strict Whitelist: Mission-critical files that must NEVER be deleted under any circumstances
IMMUTABLE_DATA_WHITELIST: Set[str] = {
    "lessons.db",
    "tiger_trades.db",
    "tiger_state.json",
    "tiger_config.json",
    "tiger_distilled_rules.json",
    "tiger_radar.json",
    "scalp_orders.json",
    "scalper_config.json",
    "scalper_distilled_rules.json",
    "bot_settings.json",
    "paper_trading_state.json",
    "storm_state.json",
}

# Core 1h Macro Kline Caches (Protected from automated pruning)
CORE_1H_KLINE_CACHES: Set[str] = {
    "binance_BTCUSDT_1h.csv",
    "binance_ETHUSDT_1h.csv",
    "binance_SOLUSDT_1h.csv",
    "binance_BNBUSDT_1h.csv",
    "binance_PEPEUSDT_1h.csv",
}


def _get_default_rss_ceilings() -> Tuple[float, float]:
    """Dynamically set RSS thresholds based on runtime environment."""
    is_aws = os.getenv("KRONOS_INSTANCE_TAG", "PC").strip().upper() == "AWS"
    if is_aws:
        return 240.0, 180.0  # AWS Free Tier (1GB RAM) target < 250MB
    return 750.0, 550.0      # Local PC / Workstation threshold


@dataclass
class AntiBloatConfig:
    """Configurable resource and storage thresholds for Anti-Bloat governance."""
    # Memory Thresholds (MB)
    max_process_rss_mb: float = field(default_factory=lambda: _get_default_rss_ceilings()[0])
    warning_process_rss_mb: float = field(default_factory=lambda: _get_default_rss_ceilings()[1])

    # Disk Usage Thresholds
    max_disk_used_pct: float = 85.0
    min_disk_free_gb: float = 1.5

    # Log File Thresholds
    max_single_log_mb: float = 4.0      # Truncate if any single log exceeds 4MB
    log_keep_lines: int = 2500          # Keep last 2,500 lines upon truncation

    # Stale File Thresholds (seconds)
    temp_buffer_max_age_seconds: float = 3600.0   # 1 hour
    stale_csv_max_age_seconds: float = 86400.0     # 24 hours

    # Cadence
    check_interval_seconds: float = 30.0          # Fast detector cadence (30s)
    deep_clean_interval_seconds: float = 1800.0   # Full deep clean cadence (30m)


@dataclass
class BloatDetectionReport:
    """Snapshot of current system resources and detected bloat levels."""
    timestamp_utc: str
    process_rss_mb: float
    disk_total_gb: float
    disk_used_gb: float
    disk_free_gb: float
    disk_used_pct: float
    oversized_logs: List[Dict[str, Any]]
    stale_temp_files_count: int
    stale_temp_bytes: int
    severity: str                       # "NORMAL", "WARNING", "CRITICAL"
    breaches: List[str] = field(default_factory=list)

    @property
    def is_actionable(self) -> bool:
        return self.severity in ("WARNING", "CRITICAL")


class AntiBloatEngine:
    """
    Autonomous 24/7 Anti-Bloat Guardian.
    Runs aligned with data fetching cycles and/or as a persistent background daemon thread.
    """

    def __init__(
        self,
        config: Optional[AntiBloatConfig] = None,
        workspace_root: Optional[str] = None
    ):
        self.cfg = config or AntiBloatConfig()
        self.workspace_root = workspace_root or WORKSPACE_ROOT
        self.data_dir = os.path.join(self.workspace_root, "data")
        self.logs_dir = os.path.join(self.workspace_root, "logs")

        self._lock = threading.Lock()
        self._cache_pruners: Dict[str, Callable[[], int]] = {}
        self._last_check_ts: float = 0.0
        self._last_deep_clean_ts: float = 0.0
        self._last_report: Optional[BloatDetectionReport] = None
        self._last_clean_summary: Optional[Dict[str, Any]] = None
        self._total_cleans_executed: int = 0
        self._total_bytes_reclaimed: int = 0

        # Background daemon control
        self._daemon_thread: Optional[threading.Thread] = None
        self._is_running = False

    def register_cache_pruner(self, name: str, pruner_callable: Callable[[], int]) -> None:
        """Register an in-memory cache pruner (e.g. CryptoIndexEngine.prune_expired_caches)."""
        with self._lock:
            self._cache_pruners[name] = pruner_callable

    def get_process_rss_mb(self) -> float:
        """Measure current process Resident Set Size (RSS) in megabytes."""
        try:
            import psutil
            p = psutil.Process(os.getpid())
            return p.memory_info().rss / (1024.0 * 1024.0)
        except Exception:
            pass

        # Linux /proc fallback
        if os.path.exists("/proc/self/status"):
            try:
                with open("/proc/self/status", "r") as f:
                    for line in f:
                        if line.startswith("VmRSS:"):
                            parts = line.split()
                            return float(parts[1]) / 1024.0  # kB to MB
            except Exception:
                pass

        return 0.0

    def get_disk_usage(self) -> Tuple[float, float, float, float]:
        """Returns (total_gb, used_gb, free_gb, used_pct)."""
        try:
            total, used, free = shutil.disk_usage(self.workspace_root)
            total_gb = total / (1024.0 ** 3)
            used_gb = used / (1024.0 ** 3)
            free_gb = free / (1024.0 ** 3)
            used_pct = (used / total) * 100.0 if total > 0 else 0.0
            return total_gb, used_gb, free_gb, used_pct
        except Exception:
            return 0.0, 0.0, 0.0, 0.0

    def detect_bloat(self) -> BloatDetectionReport:
        """Evaluates live system resources and returns a structured BloatDetectionReport."""
        now_utc = datetime.datetime.now(datetime.timezone.utc).isoformat()
        rss_mb = self.get_process_rss_mb()
        total_gb, used_gb, free_gb, used_pct = self.get_disk_usage()

        breaches: List[str] = []
        severity = "NORMAL"

        # 1. Memory Check
        if rss_mb >= self.cfg.max_process_rss_mb:
            severity = "CRITICAL"
            breaches.append(f"Process RSS breached ceiling: {rss_mb:.1f} MB >= {self.cfg.max_process_rss_mb:.1f} MB")
        elif rss_mb >= self.cfg.warning_process_rss_mb:
            if severity != "CRITICAL":
                severity = "WARNING"
            breaches.append(f"Process RSS elevated: {rss_mb:.1f} MB >= {self.cfg.warning_process_rss_mb:.1f} MB")

        # 2. Disk Check
        if used_pct >= self.cfg.max_disk_used_pct or free_gb <= self.cfg.min_disk_free_gb:
            severity = "CRITICAL"
            breaches.append(f"Disk space constrained: {used_pct:.1f}% used ({free_gb:.2f} GB free)")

        # 3. Oversized Logs Check
        oversized_logs: List[Dict[str, Any]] = []
        max_log_bytes = int(self.cfg.max_single_log_mb * 1024 * 1024)
        if os.path.exists(self.logs_dir):
            for fname in os.listdir(self.logs_dir):
                fpath = os.path.join(self.logs_dir, fname)
                if os.path.isfile(fpath) and fname.endswith(".log"):
                    try:
                        sz = os.path.getsize(fpath)
                        if sz > max_log_bytes:
                            sz_mb = sz / (1024.0 * 1024.0)
                            oversized_logs.append({"file": fname, "size_mb": round(sz_mb, 2)})
                            if severity != "CRITICAL":
                                severity = "WARNING"
                            breaches.append(f"Oversized log: {fname} ({sz_mb:.2f} MB > {self.cfg.max_single_log_mb:.1f} MB)")
                    except Exception:
                        pass

        # 4. Stale Temp Files Check
        now = time.time()
        stale_cutoff = now - self.cfg.temp_buffer_max_age_seconds
        stale_count = 0
        stale_bytes = 0
        search_dirs = [self.data_dir, self.workspace_root]
        for sdir in search_dirs:
            if not os.path.exists(sdir):
                continue
            for fname in os.listdir(sdir):
                fpath = os.path.join(sdir, fname)
                if not os.path.isfile(fpath):
                    continue
                name_l = fname.lower()
                is_tmp = (
                    name_l.startswith("_temp_") or
                    name_l.endswith(".tmp") or
                    name_l.endswith(".bak") or
                    name_l.endswith(".csv.old")
                )
                if is_tmp:
                    try:
                        if os.path.getmtime(fpath) < stale_cutoff:
                            stale_count += 1
                            stale_bytes += os.path.getsize(fpath)
                    except Exception:
                        pass

        if stale_count > 10:
            if severity != "CRITICAL":
                severity = "WARNING"
            breaches.append(f"Accumulated {stale_count} orphaned temp buffers ({stale_bytes / 1024:.1f} KB)")

        report = BloatDetectionReport(
            timestamp_utc=now_utc,
            process_rss_mb=round(rss_mb, 2),
            disk_total_gb=round(total_gb, 2),
            disk_used_gb=round(used_gb, 2),
            disk_free_gb=round(free_gb, 2),
            disk_used_pct=round(used_pct, 1),
            oversized_logs=oversized_logs,
            stale_temp_files_count=stale_count,
            stale_temp_bytes=stale_bytes,
            severity=severity,
            breaches=breaches
        )
        with self._lock:
            self._last_report = report
        return report

    def prune_in_memory_caches(self) -> Dict[str, int]:
        """Executes all registered in-memory cache pruners."""
        results: Dict[str, int] = {}
        with self._lock:
            pruners = dict(self._cache_pruners)
        for name, pruner in pruners.items():
            try:
                count = pruner()
                results[name] = count
            except Exception as e:
                results[name] = 0
                logger.warning(f"[ANTI-BLOAT] Pruner {name} failed: {e}")
        return results

    def truncate_logs(self) -> Tuple[int, int]:
        """Truncates logs exceeding max_single_log_mb to the last keep_lines lines."""
        truncated_count = 0
        reclaimed_bytes = 0
        max_bytes = int(self.cfg.max_single_log_mb * 1024 * 1024)

        if not os.path.exists(self.logs_dir):
            return 0, 0

        for fname in os.listdir(self.logs_dir):
            fpath = os.path.join(self.logs_dir, fname)
            if not os.path.isfile(fpath):
                continue

            # Delete .old or .bak files in logs older than 24h
            if fname.endswith(".old") or fname.endswith(".bak"):
                try:
                    if time.time() - os.path.getmtime(fpath) > 86400:
                        sz = os.path.getsize(fpath)
                        os.remove(fpath)
                        reclaimed_bytes += sz
                        truncated_count += 1
                        continue
                except Exception:
                    pass

            if fname.endswith(".log"):
                try:
                    sz = os.path.getsize(fpath)
                    if sz > max_bytes:
                        with open(fpath, "r", encoding="utf-8", errors="ignore") as lf:
                            lines = lf.readlines()
                        if len(lines) > self.cfg.log_keep_lines:
                            tail = lines[-self.cfg.log_keep_lines:]
                            tmp_p = fpath + ".clean.tmp"
                            with open(tmp_p, "w", encoding="utf-8") as tf:
                                tf.writelines(tail)
                            os.replace(tmp_p, fpath)
                            new_sz = os.path.getsize(fpath)
                            reclaimed = max(0, sz - new_sz)
                            reclaimed_bytes += reclaimed
                            truncated_count += 1
                            logger.info(
                                f"[ANTI-BLOAT] Truncated {fname} ({sz / (1024*1024):.1f}MB -> {new_sz / (1024*1024):.1f}MB, reclaimed {reclaimed / (1024*1024):.1f}MB)"
                            )
                except Exception as e:
                    logger.warning(f"[ANTI-BLOAT] Failed to truncate {fname}: {e}")

        return truncated_count, reclaimed_bytes

    def purge_orphaned_files(self) -> Tuple[int, int]:
        """Purges stale temp buffers, old un-whitelisted CSVs, while strictly protecting immutable whitelist."""
        deleted_count = 0
        reclaimed_bytes = 0
        now = time.time()
        temp_cutoff = now - self.cfg.temp_buffer_max_age_seconds
        csv_cutoff = now - self.cfg.stale_csv_max_age_seconds

        search_dirs = [self.data_dir, self.workspace_root]
        for sdir in search_dirs:
            if not os.path.exists(sdir):
                continue
            for fname in os.listdir(sdir):
                fpath = os.path.join(sdir, fname)
                if not os.path.isfile(fpath):
                    continue

                # Strict Whitelist Guard: Never touch mission-critical state files!
                if fname in IMMUTABLE_DATA_WHITELIST or fname in CORE_1H_KLINE_CACHES:
                    continue

                name_l = fname.lower()
                is_temp = (
                    name_l.startswith("_temp_") or
                    name_l.endswith(".tmp") or
                    name_l.endswith(".bak") or
                    name_l.endswith(".csv.old")
                )
                is_stale_csv = name_l.endswith(".csv") and not name_l.startswith("binance_")

                try:
                    mtime = os.path.getmtime(fpath)
                    if (is_temp and mtime < temp_cutoff) or (is_stale_csv and mtime < csv_cutoff):
                        sz = os.path.getsize(fpath)
                        os.remove(fpath)
                        reclaimed_bytes += sz
                        deleted_count += 1
                except Exception:
                    pass

        return deleted_count, reclaimed_bytes

    def checkpoint_and_vacuum_sqlite(self) -> List[Dict[str, Any]]:
        """
        Executes PRAGMA wal_checkpoint(TRUNCATE), VACUUM, and PRAGMA optimize on active SQLite DBs.
        Truncates oversized WAL files and reclaims deleted database pages.
        """
        results: List[Dict[str, Any]] = []
        db_files = [
            os.path.join(self.data_dir, "lessons.db"),
            os.path.join(self.data_dir, "tiger_trades.db"),
            os.path.join(self.data_dir, "risk_ledger.db"),
        ]

        for db_path in db_files:
            if not os.path.exists(db_path):
                continue
            try:
                sz_before = os.path.getsize(db_path)
                # Check for WAL file
                wal_path = db_path + "-wal"
                wal_sz_before = os.path.getsize(wal_path) if os.path.exists(wal_path) else 0

                conn = sqlite3.connect(db_path, timeout=5.0)
                try:
                    conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
                    conn.execute("VACUUM;")
                    conn.execute("PRAGMA optimize;")
                finally:
                    conn.close()

                sz_after = os.path.getsize(db_path)
                wal_sz_after = os.path.getsize(wal_path) if os.path.exists(wal_path) else 0
                total_reclaimed = max(0, (sz_before + wal_sz_before) - (sz_after + wal_sz_after))

                results.append({
                    "db": os.path.basename(db_path),
                    "size_before": sz_before + wal_sz_before,
                    "size_after": sz_after + wal_sz_after,
                    "reclaimed_bytes": total_reclaimed
                })
            except Exception as e:
                results.append({"db": os.path.basename(db_path), "error": str(e)})

        return results

    def bound_json_histories(self) -> int:
        """Bounds long-running JSON history arrays to prevent infinite unbounded serialization growth."""
        bounded = 0
        # 1. scalp_orders.json
        orders_path = os.path.join(self.data_dir, "scalp_orders.json")
        if os.path.exists(orders_path):
            try:
                with open(orders_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, list) and len(data) > self.cfg.max_scalp_orders_count:
                    trimmed = data[-self.cfg.keep_scalp_orders_count:]
                    tmp = orders_path + ".tmp"
                    with open(tmp, "w", encoding="utf-8") as f:
                        json.dump(trimmed, f, indent=2)
                    os.replace(tmp, orders_path)
                    bounded += 1
            except Exception:
                pass

        # 2. paper_trading_state.json
        state_path = os.path.join(self.data_dir, "paper_trading_state.json")
        if os.path.exists(state_path):
            try:
                with open(state_path, "r", encoding="utf-8") as f:
                    sdata = json.load(f)
                closed = sdata.get("closed_trades", [])
                if isinstance(closed, list) and len(closed) > 200:
                    sdata["closed_trades"] = closed[-100:]
                    tmp = state_path + ".tmp"
                    with open(tmp, "w", encoding="utf-8") as f:
                        json.dump(sdata, f, indent=2)
                    os.replace(tmp, state_path)
                    bounded += 1
            except Exception:
                pass

        return bounded

    def execute_cleanse_cycle(self, force_deep_clean: bool = False) -> Dict[str, Any]:
        """
        Executes a targeted or deep anti-bloat cleanse pass.
        Returns a detailed summary of actions taken and bytes reclaimed.
        """
        start_t = time.time()
        now_utc = datetime.datetime.now(datetime.timezone.utc).isoformat()

        # 1. In-Memory Caches
        cache_results = self.prune_in_memory_caches()

        # 2. Logs
        log_count, log_bytes = self.truncate_logs()

        # 3. Orphaned Files
        file_count, file_bytes = self.purge_orphaned_files()

        # 4. JSON Histories
        json_count = self.bound_json_histories()

        # 5. SQLite Deep Clean (if forced or deep clean interval elapsed)
        sqlite_results: List[Dict[str, Any]] = []
        is_deep = force_deep_clean or (start_t - self._last_deep_clean_ts) >= self.cfg.deep_clean_interval_seconds
        if is_deep:
            sqlite_results = self.checkpoint_and_vacuum_sqlite()
            self._last_deep_clean_ts = start_t

        # 6. Garbage Collection (free cyclical references and return heap memory)
        gc_collected = gc.collect()

        total_bytes = log_bytes + file_bytes + sum(r.get("reclaimed_bytes", 0) for r in sqlite_results)
        duration = time.time() - start_t

        summary = {
            "timestamp_utc": now_utc,
            "duration_seconds": round(duration, 3),
            "total_bytes_reclaimed": total_bytes,
            "reclaimed_mb": round(total_bytes / (1024.0 * 1024.0), 2),
            "details": {
                "in_memory_caches_pruned": cache_results,
                "logs_truncated": {"count": log_count, "bytes": log_bytes},
                "orphaned_files_deleted": {"count": file_count, "bytes": file_bytes},
                "json_state_bounded": json_count,
                "sqlite_compaction": sqlite_results,
                "gc_objects_collected": gc_collected,
            }
        }

        with self._lock:
            self._last_clean_summary = summary
            self._total_cleans_executed += 1
            self._total_bytes_reclaimed += total_bytes

        if total_bytes > 0 or is_deep:
            logger.info(
                f"[ANTI-BLOAT] Cleanse complete in {duration:.2f}s: Reclaimed {summary['reclaimed_mb']} MB ({gc_collected} gc objects freed)"
            )

        return summary

    def tick(self, now_ts: Optional[float] = None) -> Optional[Dict[str, Any]]:
        """
        Fast non-blocking tick called aligned with data fetching cycles.
        Checks resource levels every check_interval_seconds (30s) and cleans autonomously if needed.
        """
        current_t = now_ts or time.time()
        if (current_t - self._last_check_ts) < self.cfg.check_interval_seconds:
            return None

        self._last_check_ts = current_t
        report = self.detect_bloat()

        is_deep_due = (current_t - self._last_deep_clean_ts) >= self.cfg.deep_clean_interval_seconds

        # Autonomous Cleaning Trigger:
        # If actionable breaches exist OR deep clean interval is due, execute cleanse!
        if report.is_actionable or is_deep_due:
            return self.execute_cleanse_cycle(force_deep_clean=is_deep_due)

        return None

    def start_daemon(self, interval_seconds: Optional[float] = None) -> None:
        """Starts 24/7 autonomous anti-bloat background daemon thread."""
        if self._is_running:
            return
        self._is_running = True
        interval = interval_seconds or self.cfg.check_interval_seconds

        def _daemon_loop():
            logger.info(f"[ANTI-BLOAT] 24/7 background hygiene daemon active (cadence: {interval}s).")
            while self._is_running:
                try:
                    self.tick()
                except Exception as e:
                    logger.error(f"[ANTI-BLOAT] Daemon tick error: {e}")
                time.sleep(interval)

        self._daemon_thread = threading.Thread(target=_daemon_loop, name="AntiBloatDaemon", daemon=True)
        self._daemon_thread.start()

    def stop_daemon(self) -> None:
        """Stops background daemon thread cleanly."""
        self._is_running = False
        if self._daemon_thread and self._daemon_thread.is_alive():
            self._daemon_thread.join(timeout=2.0)
        logger.info("[ANTI-BLOAT] Background hygiene daemon stopped.")

    def get_status(self) -> Dict[str, Any]:
        """Provides full real-time telemetry dictionary for API endpoints and WebUI."""
        report = self.detect_bloat()
        with self._lock:
            return {
                "active_daemon": self._is_running,
                "current_report": {
                    "timestamp_utc": report.timestamp_utc,
                    "process_rss_mb": report.process_rss_mb,
                    "disk_total_gb": report.disk_total_gb,
                    "disk_used_gb": report.disk_used_gb,
                    "disk_free_gb": report.disk_free_gb,
                    "disk_used_pct": report.disk_used_pct,
                    "oversized_logs": report.oversized_logs,
                    "stale_temp_files": report.stale_temp_files_count,
                    "severity": report.severity,
                    "breaches": report.breaches,
                },
                "total_cleans_executed": self._total_cleans_executed,
                "total_reclaimed_mb": round(self._total_bytes_reclaimed / (1024.0 * 1024.0), 2),
                "last_clean_summary": self._last_clean_summary,
            }


# Global Singleton
_GLOBAL_ANTI_BLOAT: Optional[AntiBloatEngine] = None
_GLOBAL_LOCK = threading.Lock()


def get_anti_bloat_engine(config: Optional[AntiBloatConfig] = None) -> AntiBloatEngine:
    """Safely retrieves or instantiates the global singleton AntiBloatEngine."""
    global _GLOBAL_ANTI_BLOAT
    with _GLOBAL_LOCK:
        if _GLOBAL_ANTI_BLOAT is None:
            _GLOBAL_ANTI_BLOAT = AntiBloatEngine(config=config)
        return _GLOBAL_ANTI_BLOAT
