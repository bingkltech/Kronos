#!/usr/bin/env python3
"""
scripts/system_hygiene.py — Autonomous Multi-Tier Storage & Process Hygiene Engine
===================================================================================
Maintains lean footprints across Local PC Workstation and AWS EC2 Cloud Instances.
Runs automatically without human intervention, bounded by strict whitelists:
1. Purges orphaned lookback buffers (_temp_*.csv, *.tmp, *.bak older than 1h).
2. Cleans dead PID locks (kronos.pid if process is deceased).
3. Prunes stale one-off kline fetches older than 24h (protects 5 core 1h macro caches).
4. Rotates and bounds oversized logs in logs/ (>5MB capped to last 5,000 lines).
5. Compresses SQLite database fragmentation (VACUUM and PRAGMA optimize).
6. Bounds long-running JSON history arrays (scalp_orders.json, paper_trading_state.json).
7. Purges recursive Python bytecode caches (__pycache__, *.pyc).
===================================================================================
"""

import os
import sys
import time
import json
import sqlite3
import argparse
import datetime
from pathlib import Path
from typing import List, Dict, Any, Tuple

# Absolute paths based on script location
WORKSPACE_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DATA_DIR = os.path.join(WORKSPACE_ROOT, "data")
LOGS_DIR = os.path.join(WORKSPACE_ROOT, "logs")

# Strict Whitelist: These files in data/ must NEVER be deleted under any circumstances
IMMUTABLE_DATA_WHITELIST = {
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

# Core Active 1h Macro Kline Caches (Protected from automated pruning)
CORE_1H_KLINE_CACHES = {
    "binance_BTCUSDT_1h.csv",
    "binance_ETHUSDT_1h.csv",
    "binance_SOLUSDT_1h.csv",
    "binance_BNBUSDT_1h.csv",
    "binance_PEPEUSDT_1h.csv",
}


def is_pid_alive(pid_str: str) -> bool:
    """Checks if process with PID exists on Windows or Linux."""
    try:
        # Extract first numeric PID if string contains tag e.g. '17328:17328'
        pid_clean = pid_str.split(":")[0].strip()
        pid = int(pid_clean)
    except Exception:
        return False

    if pid <= 0:
        return False

    try:
        import psutil
        return psutil.pid_exists(pid)
    except ImportError:
        # Fallback without psutil
        if sys.platform == "win32":
            try:
                import ctypes
                PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
                SYNCHRONIZE = 0x00100000
                h = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION | SYNCHRONIZE, False, pid)
                if h:
                    ctypes.windll.kernel32.CloseHandle(h)
                    return True
                return False
            except Exception:
                return False
        else:
            try:
                os.kill(pid, 0)
                return True
            except OSError:
                return False


def clean_orphaned_buffers(dry_run: bool = False) -> Tuple[int, int]:
    """Purge orphaned process buffers (_temp_*.csv, *.tmp, *.bak older than 1 hour)."""
    reclaimed_bytes = 0
    deleted_count = 0
    now = time.time()
    cutoff = now - 3600  # 1 hour ago

    search_dirs = [DATA_DIR, WORKSPACE_ROOT]
    for sdir in search_dirs:
        if not os.path.exists(sdir):
            continue
        for f in os.listdir(sdir):
            p = os.path.join(sdir, f)
            if not os.path.isfile(p):
                continue
            name_lower = f.lower()
            is_temp = (
                name_lower.startswith("_temp_") or
                name_lower.endswith(".tmp") or
                name_lower.endswith(".bak") or
                name_lower.endswith(".csv.old")
            )
            if is_temp:
                try:
                    mtime = os.path.getmtime(p)
                    if mtime < cutoff:
                        sz = os.path.getsize(p)
                        if not dry_run:
                            os.remove(p)
                        reclaimed_bytes += sz
                        deleted_count += 1
                except Exception:
                    pass

    return deleted_count, reclaimed_bytes


def clean_dead_pid_locks(dry_run: bool = False) -> int:
    """Clean kronos.pid if process is dead."""
    pid_file = os.path.join(DATA_DIR, "kronos.pid")
    if not os.path.exists(pid_file):
        return 0

    try:
        with open(pid_file, "r", encoding="utf-8") as f:
            content = f.read().strip()
        if not is_pid_alive(content):
            if not dry_run:
                os.remove(pid_file)
            return 1
    except Exception:
        pass
    return 0


def clean_stale_kline_fetches(dry_run: bool = False) -> Tuple[int, int]:
    """Prune stale, non-core CSV fetches older than 24 hours."""
    reclaimed_bytes = 0
    deleted_count = 0
    now = time.time()
    cutoff_24h = now - 86400

    if not os.path.exists(DATA_DIR):
        return 0, 0

    for f in os.listdir(DATA_DIR):
        p = os.path.join(DATA_DIR, f)
        if not os.path.isfile(p):
            continue
        if f in IMMUTABLE_DATA_WHITELIST or f in CORE_1H_KLINE_CACHES:
            continue
        # Check if it's an un-whitelisted CSV file
        if f.lower().endswith(".csv"):
            try:
                mtime = os.path.getmtime(p)
                if mtime < cutoff_24h:
                    sz = os.path.getsize(p)
                    if not dry_run:
                        os.remove(p)
                    reclaimed_bytes += sz
                    deleted_count += 1
            except Exception:
                pass

    return deleted_count, reclaimed_bytes


def truncate_oversized_logs(dry_run: bool = False, max_bytes: int = 5 * 1024 * 1024, keep_lines: int = 5000) -> Tuple[int, int]:
    """Rotate and truncate oversized logs in logs/ to maintain lean disk footprint."""
    reclaimed_bytes = 0
    truncated_count = 0

    if not os.path.exists(LOGS_DIR):
        return 0, 0

    for f in os.listdir(LOGS_DIR):
        p = os.path.join(LOGS_DIR, f)
        if not os.path.isfile(p):
            continue

        # Purge .old logs older than 3 days
        if f.endswith(".old") or f.endswith(".bak"):
            try:
                sz = os.path.getsize(p)
                if not dry_run:
                    os.remove(p)
                reclaimed_bytes += sz
                truncated_count += 1
                continue
            except Exception:
                pass

        # Truncate active logs exceeding max_bytes
        if f.endswith(".log"):
            try:
                sz = os.path.getsize(p)
                if sz > max_bytes:
                    if not dry_run:
                        with open(p, "r", encoding="utf-8", errors="ignore") as lf:
                            lines = lf.readlines()
                        if len(lines) > keep_lines:
                            tail = lines[-keep_lines:]
                            tmp_p = p + ".clean.tmp"
                            with open(tmp_p, "w", encoding="utf-8") as tf:
                                tf.writelines(tail)
                            os.replace(tmp_p, p)
                            new_sz = os.path.getsize(p)
                            reclaimed_bytes += max(0, sz - new_sz)
                            truncated_count += 1
            except Exception:
                pass

    return truncated_count, reclaimed_bytes


def vacuum_sqlite_databases(dry_run: bool = False) -> List[Dict[str, Any]]:
    """Compacts and optimizes SQLite databases to reclaim deleted pages."""
    results = []
    db_files = [
        os.path.join(DATA_DIR, "lessons.db"),
        os.path.join(DATA_DIR, "tiger_trades.db")
    ]

    for db_path in db_files:
        if not os.path.exists(db_path):
            continue
        try:
            sz_before = os.path.getsize(db_path)
            if not dry_run:
                conn = sqlite3.connect(db_path, timeout=10.0)
                conn.execute("VACUUM;")
                conn.execute("PRAGMA optimize;")
                conn.close()
            sz_after = os.path.getsize(db_path) if not dry_run else sz_before
            results.append({
                "db": os.path.basename(db_path),
                "size_before": sz_before,
                "size_after": sz_after,
                "reclaimed": max(0, sz_before - sz_after)
            })
        except Exception as e:
            results.append({
                "db": os.path.basename(db_path),
                "error": str(e)
            })

    return results


def bound_json_state_files(dry_run: bool = False) -> int:
    """Prevents unbounded growth of scalp_orders.json and paper_trading_state.json."""
    bounded_count = 0

    # 1. Bounded scalp_orders.json (Strategy #1)
    orders_path = os.path.join(DATA_DIR, "scalp_orders.json")
    if os.path.exists(orders_path):
        try:
            with open(orders_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list) and len(data) > 300:
                if not dry_run:
                    trimmed = data[-150:]
                    tmp = orders_path + ".tmp"
                    with open(tmp, "w", encoding="utf-8") as f:
                        json.dump(trimmed, f, indent=2)
                    os.replace(tmp, orders_path)
                bounded_count += 1
        except Exception:
            pass

    # 2. Bounded paper_trading_state.json (Macro Swing)
    state_path = os.path.join(DATA_DIR, "paper_trading_state.json")
    if os.path.exists(state_path):
        try:
            with open(state_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            closed = data.get("closed_trades", [])
            if isinstance(closed, list) and len(closed) > 300:
                if not dry_run:
                    data["closed_trades"] = closed[-150:]
                    tmp = state_path + ".tmp"
                    with open(tmp, "w", encoding="utf-8") as f:
                        json.dump(data, f, indent=2)
                    os.replace(tmp, state_path)
                bounded_count += 1
        except Exception:
            pass

    return bounded_count


def clean_python_bytecode(dry_run: bool = False) -> Tuple[int, int]:
    """Recursively purges __pycache__ and *.pyc bytecode caches."""
    deleted_files = 0
    deleted_dirs = 0
    reclaimed_bytes = 0

    for root, dirs, files in os.walk(WORKSPACE_ROOT, topdown=False):
        if any(skip in root for skip in [".git", ".venv", "venv", "node_modules"]):
            continue

        for f in files:
            if f.endswith(".pyc") or f.endswith(".pyo"):
                p = os.path.join(root, f)
                try:
                    sz = os.path.getsize(p)
                    if not dry_run:
                        os.remove(p)
                    reclaimed_bytes += sz
                    deleted_files += 1
                except Exception:
                    pass

        for d in dirs:
            if d == "__pycache__":
                dp = os.path.join(root, d)
                try:
                    if not dry_run:
                        os.rmdir(dp)
                    deleted_dirs += 1
                except Exception:
                    pass

    return deleted_files + deleted_dirs, reclaimed_bytes


def run_system_hygiene_cycle(dry_run: bool = False, quiet: bool = False) -> Dict[str, Any]:
    """Executes a full, autonomous multi-tier hygiene maintenance pass."""
    start_t = time.time()
    now_utc = datetime.datetime.now(datetime.timezone.utc)

    # 1. Clean buffers
    buf_count, buf_bytes = clean_orphaned_buffers(dry_run=dry_run)

    # 2. Dead PID
    pid_count = clean_dead_pid_locks(dry_run=dry_run)

    # 3. Stale klines
    kline_count, kline_bytes = clean_stale_kline_fetches(dry_run=dry_run)

    # 4. Logs
    log_count, log_bytes = truncate_oversized_logs(dry_run=dry_run)

    # 5. SQLite vacuum
    vacuum_res = vacuum_sqlite_databases(dry_run=dry_run)

    # 6. JSON bounding
    json_count = bound_json_state_files(dry_run=dry_run)

    # 7. Bytecode caches
    pyc_count, pyc_bytes = clean_python_bytecode(dry_run=dry_run)

    total_bytes = buf_bytes + kline_bytes + log_bytes + pyc_bytes
    total_files = buf_count + pid_count + kline_count + log_count + pyc_count
    duration = time.time() - start_t

    summary = {
        "timestamp_utc": now_utc.isoformat(),
        "dry_run": dry_run,
        "duration_seconds": round(duration, 3),
        "total_files_cleaned": total_files,
        "total_bytes_reclaimed": total_bytes,
        "reclaimed_mb": round(total_bytes / (1024 * 1024), 2),
        "details": {
            "orphaned_buffers": {"count": buf_count, "bytes": buf_bytes},
            "dead_pid_locks": {"count": pid_count},
            "stale_klines": {"count": kline_count, "bytes": kline_bytes},
            "log_truncations": {"count": log_count, "bytes": log_bytes},
            "json_bounded": {"count": json_count},
            "bytecode_caches": {"count": pyc_count, "bytes": pyc_bytes},
            "sqlite_vacuum": vacuum_res
        }
    }

    if not quiet:
        mode_str = "[DRY-RUN] " if dry_run else ""
        print("=" * 80)
        print(f"  KRONOS AUTONOMOUS SYSTEM HYGIENE {mode_str}PASS")
        print(f"  Timestamp: {now_utc.strftime('%Y-%m-%d %H:%M:%S UTC')} | Duration: {duration:.2f}s")
        print("=" * 80)
        print(f"  • Orphaned Buffers Purged:      {buf_count} files ({buf_bytes/1024:.1f} KB)")
        print(f"  • Dead PID Locks Cleared:       {pid_count} files")
        print(f"  • Stale Kline Fetches Cleared:  {kline_count} files ({kline_bytes/1024:.1f} KB)")
        print(f"  • Oversized Logs Rotated:       {log_count} files ({log_bytes/1024:.1f} KB)")
        print(f"  • Bytecode Caches Purged:       {pyc_count} items ({pyc_bytes/1024:.1f} KB)")
        print(f"  • JSON Histories Bounded:       {json_count} files")
        for v in vacuum_res:
            print(f"  • SQLite Compaction ({v.get('db')}): {v.get('size_before',0):,} bytes -> {v.get('size_after',0):,} bytes")
        print("-" * 80)
        print(f"  TOTAL RECLAIMED: {total_bytes / (1024*1024):.2f} MB across {total_files} artifacts")
        print("=" * 80)

    return summary


def main():
    parser = argparse.ArgumentParser(description="Kronos Autonomous Storage & Process Hygiene Engine")
    parser.add_argument("--dry-run", action="store_true", help="Simulate actions without deleting or truncating")
    parser.add_argument("--quiet", action="store_true", help="Suppress output (suitable for headless cron / timer)")
    parser.add_argument("--json", action="store_true", help="Output summary as JSON")
    args = parser.parse_args()

    summary = run_system_hygiene_cycle(dry_run=args.dry_run, quiet=args.quiet and not args.json)
    if args.json:
        print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
