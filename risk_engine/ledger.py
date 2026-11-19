"""
risk_engine/ledger.py — Atomic Cross-Process SQLite Risk State & Reservation Ledger.

Eliminates TOCTOU race conditions between concurrent workers (e.g. Macro & Tiger daemons)
sharing one exchange account by serializing:
1. Mark-to-Market equity watermarks (rolling peak & intraday start persisted across restarts).
2. Persistent HALTED latch & desync flags synchronized across processes.
3. Short-lived atomic slot & symbol reservation leases (SQLite BEGIN IMMEDIATE).

Strictly adheres to Zero Float Financial Math (all monetary values stored as Decimal strings).
"""

from __future__ import annotations

import datetime
from decimal import Decimal
import os
import sqlite3
import time
from typing import Dict, List, Optional, Tuple


class RiskLedger:
    """Thread-safe and multi-process-safe SQLite ledger for institutional risk state."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        parent = os.path.dirname(os.path.abspath(db_path))
        if parent:
            os.makedirs(parent, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=5.0, isolation_level=None)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=FULL;")
        conn.execute("PRAGMA busy_timeout=5000;")
        return conn

    def _init_schema(self) -> None:
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE;")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS risk_watermarks (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    peak_equity_usd TEXT NOT NULL,
                    intraday_start_equity_usd TEXT NOT NULL,
                    intraday_utc_date TEXT NOT NULL,
                    updated_at_ms INTEGER NOT NULL
                );
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS risk_halt_state (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    is_halted INTEGER NOT NULL DEFAULT 0,
                    halt_reason TEXT,
                    is_desync_halt INTEGER NOT NULL DEFAULT 0,
                    updated_at_ms INTEGER NOT NULL
                );
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS slot_reservations (
                    reservation_id TEXT PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    notional_usd TEXT NOT NULL,
                    stop_risk_usd TEXT NOT NULL,
                    created_at_ms INTEGER NOT NULL,
                    expires_at_ms INTEGER NOT NULL
                );
                """
            )
            conn.execute("COMMIT;")
        finally:
            conn.close()

    def sync_watermarks(
        self,
        current_mtm_equity: Decimal,
        now_ms: Optional[int] = None,
    ) -> Tuple[Decimal, Decimal]:
        """
        Atomically update and return (peak_equity_usd, intraday_start_equity_usd)
        using live Mark-to-Market equity (wallet + unrealized PnL).
        Rolls intraday watermark automatically on UTC date boundary.
        """
        ts = now_ms if now_ms is not None else int(time.time() * 1000)
        utc_date = datetime.datetime.fromtimestamp(ts / 1000.0, tz=datetime.timezone.utc).date().isoformat()
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE;")
            row = conn.execute(
                "SELECT peak_equity_usd, intraday_start_equity_usd, intraday_utc_date FROM risk_watermarks WHERE id = 1;"
            ).fetchone()
            if row is None:
                peak = current_mtm_equity
                intra = current_mtm_equity
                conn.execute(
                    "INSERT INTO risk_watermarks (id, peak_equity_usd, intraday_start_equity_usd, intraday_utc_date, updated_at_ms) VALUES (1, ?, ?, ?, ?);",
                    (str(peak), str(intra), utc_date, ts),
                )
            else:
                peak = max(Decimal(row[0]), current_mtm_equity)
                intra = current_mtm_equity if row[2] != utc_date else Decimal(row[1])
                conn.execute(
                    "UPDATE risk_watermarks SET peak_equity_usd = ?, intraday_start_equity_usd = ?, intraday_utc_date = ?, updated_at_ms = ? WHERE id = 1;",
                    (str(peak), str(intra), utc_date, ts),
                )
            conn.execute("COMMIT;")
            return peak, intra
        except Exception:
            conn.execute("ROLLBACK;")
            raise
        finally:
            conn.close()

    def get_halt_state(self) -> Tuple[bool, Optional[str], bool]:
        """Return (is_halted, halt_reason, is_desync_halt)."""
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT is_halted, halt_reason, is_desync_halt FROM risk_halt_state WHERE id = 1;"
            ).fetchone()
            if row is None:
                return False, None, False
            return bool(row[0]), row[1], bool(row[2])
        finally:
            conn.close()

    def set_halt_state(
        self,
        is_halted: bool,
        reason: Optional[str] = None,
        is_desync_halt: bool = False,
        now_ms: Optional[int] = None,
    ) -> None:
        ts = now_ms if now_ms is not None else int(time.time() * 1000)
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE;")
            conn.execute(
                """
                INSERT INTO risk_halt_state (id, is_halted, halt_reason, is_desync_halt, updated_at_ms)
                VALUES (1, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    is_halted = excluded.is_halted,
                    halt_reason = excluded.halt_reason,
                    is_desync_halt = excluded.is_desync_halt,
                    updated_at_ms = excluded.updated_at_ms;
                """,
                (1 if is_halted else 0, reason, 1 if is_desync_halt else 0, ts),
            )
            conn.execute("COMMIT;")
        except Exception:
            conn.execute("ROLLBACK;")
            raise
        finally:
            conn.close()

    def try_reserve_slot(
        self,
        reservation_id: str,
        symbol: str,
        side: str,
        notional_usd: Decimal,
        stop_risk_usd: Decimal,
        active_exchange_symbols: List[str],
        max_concurrent_positions: int,
        max_positions_per_symbol: int,
        ttl_ms: int = 15000,
        now_ms: Optional[int] = None,
    ) -> Tuple[bool, Optional[str]]:
        """
        Atomically check & reserve an execution slot across all worker processes.
        Prevents simultaneous workers from racing past concurrency or same-symbol limits.
        """
        ts = now_ms if now_ms is not None else int(time.time() * 1000)
        sym = symbol.strip().upper()
        active_set = {s.strip().upper() for s in active_exchange_symbols}

        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE;")
            # Purge expired leases
            conn.execute("DELETE FROM slot_reservations WHERE expires_at_ms <= ?;", (ts,))

            rows = conn.execute(
                "SELECT reservation_id, symbol FROM slot_reservations;"
            ).fetchall()
            reserved_syms = [r[1] for r in rows]

            # Count combined active exchange symbols + distinct in-flight reservations
            combined_syms = set(active_set) | set(reserved_syms)
            sym_count = (1 if sym in active_set else 0) + sum(1 for rs in reserved_syms if rs == sym)

            if sym_count >= max_positions_per_symbol:
                conn.execute("ROLLBACK;")
                return False, "LEDGER_SAME_SYMBOL_RESERVATION_CONFLICT"

            if len(combined_syms) >= max_concurrent_positions:
                conn.execute("ROLLBACK;")
                return False, "LEDGER_MAX_CONCURRENT_SLOTS_RESERVED"

            conn.execute(
                """
                INSERT INTO slot_reservations (reservation_id, symbol, side, notional_usd, stop_risk_usd, created_at_ms, expires_at_ms)
                VALUES (?, ?, ?, ?, ?, ?, ?);
                """,
                (reservation_id, sym, side.upper(), str(notional_usd), str(stop_risk_usd), ts, ts + ttl_ms),
            )
            conn.execute("COMMIT;")
            return True, None
        except Exception:
            conn.execute("ROLLBACK;")
            raise
        finally:
            conn.close()

    def release_slot(self, reservation_id: str) -> None:
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE;")
            conn.execute("DELETE FROM slot_reservations WHERE reservation_id = ?;", (reservation_id,))
            conn.execute("COMMIT;")
        finally:
            conn.close()

    def active_reservations(self, now_ms: Optional[int] = None) -> List[Dict[str, str]]:
        ts = now_ms if now_ms is not None else int(time.time() * 1000)
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE;")
            conn.execute("DELETE FROM slot_reservations WHERE expires_at_ms <= ?;", (ts,))
            rows = conn.execute(
                "SELECT reservation_id, symbol, side, notional_usd, stop_risk_usd FROM slot_reservations;"
            ).fetchall()
            conn.execute("COMMIT;")
            return [
                {
                    "reservation_id": r[0],
                    "symbol": r[1],
                    "side": r[2],
                    "notional_usd": r[3],
                    "stop_risk_usd": r[4],
                }
                for r in rows
            ]
        finally:
            conn.close()
