"""
risk_engine/telemetry.py — Structured CSV & JSONL Audit Trail for Risk Decisions.

Every RiskDecision (especially RESIZED, VETOED, and KILL_SWITCH events) is persisted
with full state snapshots for post-trade forensics, compliance review, and replay.
"""

from __future__ import annotations

import csv
import json
import os
import threading
from typing import Any, Dict, List, Optional

from risk_engine.models import DecisionStatus, RiskDecision


CSV_COLUMNS = [
    "timestamp_utc",
    "symbol",
    "side",
    "order_type",
    "status",
    "risk_mode",
    "proposed_qty",
    "approved_qty",
    "order_notional_usd",
    "drawdown_pct",
    "realized_vol",
    "kelly_fraction",
    "spread_bps",
    "empirical_cvar_pct",
    "gross_leverage",
    "net_leverage",
    "reason_codes",
    "actions_required",
]


class RiskAuditLogger:
    """Thread-safe structured JSONL + CSV audit logger for RiskEngine decisions."""

    def __init__(self, log_dir: Optional[str] = None, log_all_decisions: bool = True):
        self.log_dir = log_dir
        self.log_all_decisions = log_all_decisions
        self._lock = threading.Lock()
        self.jsonl_path = os.path.join(log_dir, "risk_decisions.jsonl") if log_dir else None
        self.csv_path = os.path.join(log_dir, "risk_decisions.csv") if log_dir else None
        self.memory_buffer: List[Dict[str, Any]] = []

    def log_decision(self, decision: RiskDecision) -> None:
        """Persist a RiskDecision to memory buffer and structured JSONL/CSV files."""
        if not self.log_all_decisions and decision.status == DecisionStatus.APPROVED:
            return

        record = decision.to_dict()
        metrics = record["metrics_snapshot"]

        with self._lock:
            self.memory_buffer.append(record)
            if len(self.memory_buffer) > 5000:
                self.memory_buffer = self.memory_buffer[-2500:]

            if not self.log_dir:
                return

            os.makedirs(self.log_dir, exist_ok=True)

            # 1. Structured JSONL (full lossless metrics snapshot)
            if self.jsonl_path:
                with open(self.jsonl_path, "a", encoding="utf-8") as jf:
                    jf.write(json.dumps(record, ensure_ascii=False) + "\n")

            # 2. Structured CSV (tabular diagnostics for fast analytics)
            if self.csv_path:
                write_header = not os.path.exists(self.csv_path) or os.path.getsize(self.csv_path) == 0
                row = {
                    "timestamp_utc": record["timestamp_utc"],
                    "symbol": metrics.get("symbol", ""),
                    "side": metrics.get("side", ""),
                    "order_type": metrics.get("order_type", ""),
                    "status": record["status"],
                    "risk_mode": record["risk_mode"],
                    "proposed_qty": metrics.get("proposed_qty", ""),
                    "approved_qty": record["approved_qty"],
                    "order_notional_usd": metrics.get("order_notional_usd", ""),
                    "drawdown_pct": metrics.get("drawdown_pct", ""),
                    "realized_vol": metrics.get("realized_vol", ""),
                    "kelly_fraction": metrics.get("kelly_fraction", ""),
                    "spread_bps": metrics.get("spread_bps", ""),
                    "empirical_cvar_pct": metrics.get("empirical_cvar_pct", ""),
                    "gross_leverage": metrics.get("gross_leverage", ""),
                    "net_leverage": metrics.get("net_leverage", ""),
                    "reason_codes": "|".join(record["reason_codes"]),
                    "actions_required": "|".join(record["actions_required"]),
                }
                with open(self.csv_path, "a", encoding="utf-8", newline="") as cf:
                    writer = csv.DictWriter(cf, fieldnames=CSV_COLUMNS)
                    if write_header:
                        writer.writeheader()
                    writer.writerow(row)
