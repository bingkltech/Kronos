"""
tests/test_system_hygiene.py — Unit tests for the Autonomous System Hygiene Engine.
Verifies whitelist protection, buffer purge, log truncation, and SQLite vacuuming.
"""

import os
import time
import json
import sqlite3
import pytest
import tempfile
from unittest.mock import patch

from scripts.system_hygiene import (
    is_pid_alive,
    clean_orphaned_buffers,
    clean_dead_pid_locks,
    clean_stale_kline_fetches,
    truncate_oversized_logs,
    vacuum_sqlite_databases,
    bound_json_state_files,
    run_system_hygiene_cycle,
    IMMUTABLE_DATA_WHITELIST,
    CORE_1H_KLINE_CACHES
)


def test_immutable_whitelist_invariants():
    """Verify that core mission-critical state files are present in the immutable whitelist."""
    assert "lessons.db" in IMMUTABLE_DATA_WHITELIST
    assert "tiger_trades.db" in IMMUTABLE_DATA_WHITELIST
    assert "tiger_config.json" in IMMUTABLE_DATA_WHITELIST
    assert "tiger_state.json" in IMMUTABLE_DATA_WHITELIST
    assert "scalp_orders.json" in IMMUTABLE_DATA_WHITELIST
    assert "bot_settings.json" in IMMUTABLE_DATA_WHITELIST
    assert "binance_BTCUSDT_1h.csv" in CORE_1H_KLINE_CACHES


def test_is_pid_alive_current_and_invalid():
    """Verify PID alive check correctly identifies current process and invalid PIDs."""
    # Current process must be alive
    assert is_pid_alive(str(os.getpid())) is True

    # Negative / extreme PIDs must be dead
    assert is_pid_alive("-1") is False
    assert is_pid_alive("999999999") is False
    assert is_pid_alive("invalid_pid_string") is False


def test_clean_orphaned_buffers(tmp_path):
    """Verify that orphaned _temp_*.csv and .tmp files older than 1h are deleted."""
    mock_data = tmp_path / "data"
    mock_data.mkdir()

    # 1. Old temp file (>1h)
    old_temp = mock_data / "_temp_quant_lookback_99999.csv"
    old_temp.write_text("dummy,data\n1,2", encoding="utf-8")
    past_time = time.time() - 7200
    os.utime(str(old_temp), (past_time, past_time))

    # 2. Fresh temp file (<1h)
    fresh_temp = mock_data / "_temp_fresh.csv"
    fresh_temp.write_text("dummy,data\n1,2", encoding="utf-8")

    # 3. Whitelisted critical file
    whitelist_file = mock_data / "lessons.db"
    whitelist_file.write_text("sqlite mock", encoding="utf-8")

    with patch("scripts.system_hygiene.DATA_DIR", str(mock_data)), \
         patch("scripts.system_hygiene.WORKSPACE_ROOT", str(tmp_path)):
        del_count, reclaimed = clean_orphaned_buffers(dry_run=False)

    assert del_count == 1
    assert not old_temp.exists()
    assert fresh_temp.exists()
    assert whitelist_file.exists()


def test_stale_kline_purge_protects_core_caches(tmp_path):
    """Verify stale un-whitelisted klines older than 24h are deleted while core 1h caches are preserved."""
    mock_data = tmp_path / "data"
    mock_data.mkdir()

    past_2d = time.time() - 172800

    # 1. Stale 15m file
    stale_15m = mock_data / "binance_DOGEUSDT_15m.csv"
    stale_15m.write_text("stale klines", encoding="utf-8")
    os.utime(str(stale_15m), (past_2d, past_2d))

    # 2. Protected core 1h cache
    core_1h = mock_data / "binance_BTCUSDT_1h.csv"
    core_1h.write_text("core klines", encoding="utf-8")
    os.utime(str(core_1h), (past_2d, past_2d))

    with patch("scripts.system_hygiene.DATA_DIR", str(mock_data)):
        del_count, reclaimed = clean_stale_kline_fetches(dry_run=False)

    assert del_count == 1
    assert not stale_15m.exists()
    assert core_1h.exists()


def test_truncate_oversized_logs(tmp_path):
    """Verify that logs exceeding max size are safely truncated to last N lines."""
    mock_logs = tmp_path / "logs"
    mock_logs.mkdir()

    log_file = mock_logs / "test_overflow.log"
    # Write 1000 lines
    with open(log_file, "w", encoding="utf-8") as f:
        for i in range(1000):
            f.write(f"Line {i}: Log telemetry test content.\n")

    initial_size = os.path.getsize(str(log_file))

    # Run truncation with max_bytes=1000 and keep_lines=50
    with patch("scripts.system_hygiene.LOGS_DIR", str(mock_logs)):
        trunc_count, reclaimed = truncate_oversized_logs(dry_run=False, max_bytes=1000, keep_lines=50)

    assert trunc_count == 1
    assert reclaimed > 0
    with open(log_file, "r", encoding="utf-8") as f:
        remaining_lines = f.readlines()
    assert len(remaining_lines) == 50
    assert "Line 999:" in remaining_lines[-1]


def test_vacuum_sqlite_databases(tmp_path):
    """Verify SQLite VACUUM executes cleanly on mock databases."""
    mock_data = tmp_path / "data"
    mock_data.mkdir()

    db_path = mock_data / "lessons.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE mock_table (id INT, val TEXT);")
    for i in range(100):
        conn.execute("INSERT INTO mock_table VALUES (?, ?);", (i, f"dummy_{i}"))
    conn.commit()
    conn.execute("DELETE FROM mock_table WHERE id > 10;")
    conn.commit()
    conn.close()

    with patch("scripts.system_hygiene.DATA_DIR", str(mock_data)):
        res = vacuum_sqlite_databases(dry_run=False)

    assert len(res) == 1
    assert res[0]["db"] == "lessons.db"
    assert "error" not in res[0]
