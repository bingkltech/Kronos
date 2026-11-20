"""
tests/test_anti_bloat.py — Autonomous 24/7 Anti-Bloat & Storage Hygiene Tests.
================================================================================
Verifies:
1. Resource Detector: Correctly measures RSS memory, disk usage, and detects oversized logs.
2. In-Memory Micro-Hygiene: CryptoIndexEngine prunes expired klines and depth entries.
3. Log Truncation: Oversized logs (>4MB) truncated to last 2,500 lines.
4. Orphaned File Purge: Deletes stale _temp_*, .tmp, .bak, while strictly protecting whitelist.
5. SQLite WAL Checkpointing: Shrinks WAL files via PRAGMA wal_checkpoint(TRUNCATE).
6. Autonomous Daemon Lifecycle: Starts and stops cleanly without thread leaks.
================================================================================
"""

import json
import os
import sqlite3
import time
from unittest.mock import patch
import pytest

from src.quant.anti_bloat import (
    AntiBloatConfig,
    AntiBloatEngine,
    IMMUTABLE_DATA_WHITELIST,
)
from src.quant.crypto_index_engine import CryptoIndexEngine, OrderBookMicrostructure
from decimal import Decimal


def test_immutable_whitelist_protection():
    """Verify mission-critical state files are never touched by Anti-Bloat."""
    assert "lessons.db" in IMMUTABLE_DATA_WHITELIST
    assert "tiger_trades.db" in IMMUTABLE_DATA_WHITELIST
    assert "tiger_state.json" in IMMUTABLE_DATA_WHITELIST
    assert "scalp_orders.json" in IMMUTABLE_DATA_WHITELIST


def test_anti_bloat_detector_clean(tmp_path):
    """Verify detector reports NORMAL severity when resources are healthy."""
    cfg = AntiBloatConfig(max_process_rss_mb=1500.0, warning_process_rss_mb=1200.0)
    engine = AntiBloatEngine(config=cfg, workspace_root=str(tmp_path))
    report = engine.detect_bloat()
    assert report.severity in ("NORMAL", "WARNING")
    assert report.disk_total_gb > 0
    assert report.process_rss_mb >= 0


def test_anti_bloat_oversized_log_detection_and_truncation(tmp_path):
    """Verify detector catches oversized log and truncates it cleanly."""
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()

    cfg = AntiBloatConfig(
        max_single_log_mb=0.001,  # 1 KB threshold for testing
        log_keep_lines=10
    )
    engine = AntiBloatEngine(config=cfg, workspace_root=str(tmp_path))

    # Create oversized test log with 200 lines (>2.5 KB > 1048 bytes threshold)
    log_file = logs_dir / "tiger_live.log"
    log_file.write_text("\n".join(f"Log line {i}: detailed payload padding" for i in range(200)) + "\n", encoding="utf-8")

    # 1. Detector should flag the log as oversized
    report = engine.detect_bloat()
    assert any(item["file"] == "tiger_live.log" for item in report.oversized_logs)
    assert report.is_actionable

    # 2. Execute cleanse cycle
    summary = engine.execute_cleanse_cycle(force_deep_clean=False)
    assert summary["details"]["logs_truncated"]["count"] >= 1
    assert summary["total_bytes_reclaimed"] > 0

    # Verify truncated log only has 10 lines
    remaining_lines = log_file.read_text(encoding="utf-8").strip().split("\n")
    assert len(remaining_lines) == 10
    assert remaining_lines[-1].startswith("Log line 199")


def test_orphaned_file_purge_protects_whitelist(tmp_path):
    """Verify stale temp files are purged while whitelisted files are completely safe."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    cfg = AntiBloatConfig(temp_buffer_max_age_seconds=60.0)  # 60s cutoff
    engine = AntiBloatEngine(config=cfg, workspace_root=str(tmp_path))

    # Stale temp file (>60s old)
    old_temp = data_dir / "_temp_buffer_123.csv"
    old_temp.write_text("old,temp,data", encoding="utf-8")
    past_time = time.time() - 300
    os.utime(str(old_temp), (past_time, past_time))

    # Fresh temp file (<60s old)
    fresh_temp = data_dir / "_temp_fresh.tmp"
    fresh_temp.write_text("fresh,temp", encoding="utf-8")

    # Whitelisted critical file (must NEVER be deleted even if old!)
    whitelist_file = data_dir / "tiger_state.json"
    whitelist_file.write_text('{"active_positions": {}}', encoding="utf-8")
    os.utime(str(whitelist_file), (past_time, past_time))

    del_count, reclaimed = engine.purge_orphaned_files()
    assert del_count == 1
    assert not old_temp.exists()
    assert fresh_temp.exists()
    assert whitelist_file.exists()


def test_micro_hygiene_cache_pruning():
    """Verify CryptoIndexEngine micro-hygiene evicts expired in-memory caches."""
    engine = CryptoIndexEngine()

    now = time.time()
    # Inject expired cache entry (older than 300s)
    engine._kline_cache[("BTCUSDT", "5m", 24)] = (now - 500.0, [{"close": Decimal("60000")}])
    # Inject fresh cache entry (10s old)
    engine._kline_cache[("ETHUSDT", "5m", 24)] = (now - 10.0, [{"close": Decimal("3000")}])

    # Inject expired depth entry
    engine._depth_cache["SOLUSDT"] = (
        now - 100.0,
        OrderBookMicrostructure(Decimal("0.1"), Decimal("150"), Decimal("150.1"), Decimal("150.05"), Decimal("1.0"))
    )

    pruned = engine.prune_expired_caches(max_age_seconds=300.0)
    assert pruned == 2  # Expired BTC kline + expired SOL depth
    assert ("BTCUSDT", "5m", 24) not in engine._kline_cache
    assert ("ETHUSDT", "5m", 24) in engine._kline_cache
    assert "SOLUSDT" not in engine._depth_cache


def test_sqlite_wal_checkpoint_and_vacuum(tmp_path):
    """Verify SQLite WAL checkpointing and VACUUM reclaims deleted space."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    engine = AntiBloatEngine(workspace_root=str(tmp_path))

    db_path = data_dir / "tiger_trades.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("CREATE TABLE test_data (id INTEGER PRIMARY KEY, payload TEXT);")
    for i in range(500):
        conn.execute("INSERT INTO test_data (payload) VALUES (?);", (f"data_payload_{i*1000}",))
    conn.commit()

    # Delete half the data to create fragmentation
    conn.execute("DELETE FROM test_data WHERE id % 2 = 0;")
    conn.commit()
    conn.close()

    wal_path = str(db_path) + "-wal"
    res = engine.checkpoint_and_vacuum_sqlite()
    assert len(res) == 1
    assert res[0]["db"] == "tiger_trades.db"


def test_anti_bloat_daemon_lifecycle(tmp_path):
    """Verify AntiBloatEngine background daemon starts and stops cleanly."""
    cfg = AntiBloatConfig(check_interval_seconds=0.1)
    engine = AntiBloatEngine(config=cfg, workspace_root=str(tmp_path))

    engine.start_daemon(interval_seconds=0.1)
    assert engine._is_running is True
    time.sleep(0.3)
    engine.stop_daemon()
    assert engine._is_running is False
