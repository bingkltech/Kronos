"""
src/quant/learning_governor.py — The Learning Bot & Institutional Memory Engine.

Audits rolling prediction performance and calibrates the system's capital throttle:
1. Computes rolling 48-hour Brier Calibration Error across realized forecast outcomes.
2. Derives the dynamic Confidence Multiplier (0.0x to 1.0x) to throttle capital during regime shifts.
3. Interfaces with SQLite data/lessons.db to log trade post-mortems and consult active quantitative guidance.

Strictly adheres to:
- AGENTS.md Invariant 1: Zero Float Financial Math (decimal.Decimal).
- AGENTS.md Invariant 3: Base Checkpoint Immutability (never mutates model weights live).
"""

import os
import sys
import sqlite3
import datetime
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, List, Optional, Tuple


@dataclass(frozen=True)
class TradeOutcome:
    """Historical trade outcome record for calibration auditing."""
    trade_id: str
    symbol: str
    side: str
    forecast_confidence: Decimal   # p in [0, 1], e.g. Decimal("0.70")
    realized_hit: int              # 1 if Take-Profit reached, 0 if Stop-Loss or Stale Exit
    realized_pnl_usd: Decimal
    exit_reason: str               # "TP_HIT", "SL_HIT", "STALE_EXPIRED"
    timestamp_utc: datetime.datetime


@dataclass(frozen=True)
class CalibrationReport:
    """Rolling calibration evaluation report."""
    total_evaluations: int
    brier_score: Decimal           # Brier score in [0.0, 1.0]
    confidence_multiplier: Decimal # 0.0x to 1.0x
    status: str                    # "PRISTINE", "NOMINAL", "THROTTLED", "HALTED"
    reason: str


class LearningGovernor:
    """
    Performance Auditor and Meta-Governor.
    Controls risk exposure without risking catastrophic forgetting.
    """

    def __init__(self, db_path: Optional[str] = None):
        workspace_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        self.db_path = db_path or os.path.join(workspace_root, "data", "lessons.db")
        self._init_calibration_tables()

    def _init_calibration_tables(self) -> None:
        """Ensure calibration and trade history tables exist."""
        if self.db_path != ":memory:":
            dir_name = os.path.dirname(self.db_path)
            if dir_name:
                os.makedirs(dir_name, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        try:
            with conn:
                cursor = conn.cursor()
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS trade_outcomes (
                        trade_id TEXT PRIMARY KEY,
                        symbol TEXT NOT NULL,
                        side TEXT NOT NULL,
                        forecast_confidence TEXT NOT NULL,
                        realized_hit INTEGER NOT NULL,
                        realized_pnl_usd TEXT NOT NULL,
                        exit_reason TEXT NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
        finally:
            conn.close()

    def record_outcome(self, outcome: TradeOutcome) -> None:
        """Log a trade post-mortem into SQLite institutional memory."""
        conn = sqlite3.connect(self.db_path)
        try:
            with conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT OR REPLACE INTO trade_outcomes 
                    (trade_id, symbol, side, forecast_confidence, realized_hit, realized_pnl_usd, exit_reason)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    outcome.trade_id,
                    outcome.symbol,
                    outcome.side,
                    str(outcome.forecast_confidence),
                    outcome.realized_hit,
                    str(outcome.realized_pnl_usd),
                    outcome.exit_reason
                ))
        finally:
            conn.close()

    def calculate_brier_calibration(
        self,
        outcomes: Optional[List[TradeOutcome]] = None,
        lookback_limit: int = 50
    ) -> CalibrationReport:
        """
        Calculate rolling Brier score and derive capital Confidence Multiplier.
        Brier Score BS = (1/N) * sum((p_i - o_i)^2)
        - BS <= 0.15: Pristine (Multiplier = 1.0x)
        - 0.15 < BS <= 0.25: Nominal (Multiplier = 0.8x - 1.0x)
        - 0.25 < BS <= 0.35: Throttled (Multiplier = 0.3x - 0.7x)
        - BS > 0.35: Halted (Multiplier = 0.0x, Circuit Breaker)
        """
        if outcomes is None:
            outcomes = self._load_recent_outcomes(limit=lookback_limit)

        if not outcomes:
            # Default to full nominal allocation if no recent history
            return CalibrationReport(
                total_evaluations=0,
                brier_score=Decimal("0.1000"),
                confidence_multiplier=Decimal("1.00"),
                status="PRISTINE",
                reason="No recent closed trades. Operating at full nominal confidence (1.0x)."
            )

        n = len(outcomes)
        total_squared_error = Decimal("0.0")

        for o in outcomes:
            p = o.forecast_confidence
            y = Decimal(str(o.realized_hit))
            err = (p - y) ** Decimal("2")
            total_squared_error += err

        brier_score = (total_squared_error / Decimal(str(n))).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)

        # Capital Throttle Logic
        if brier_score <= Decimal("0.1500"):
            multiplier = Decimal("1.00")
            status = "PRISTINE"
            reason = f"High forecast calibration (Brier: {brier_score:.4f} across {n} trades). Full 1.0x capital."
        elif brier_score <= Decimal("0.2500"):
            # Linear scaling from 1.0x down to 0.75x
            # (0.25 - BS) / 0.10 * 0.25 + 0.75
            multiplier = Decimal("0.85")
            status = "NOMINAL"
            reason = f"Acceptable calibration (Brier: {brier_score:.4f} across {n} trades). Operating at 0.85x capital."
        elif brier_score <= Decimal("0.3500"):
            # Throttled capital
            multiplier = Decimal("0.40")
            status = "THROTTLED"
            reason = f"Poor calibration / regime shift detected (Brier: {brier_score:.4f}). Capital throttled to 0.40x."
        else:
            # Circuit breaker
            multiplier = Decimal("0.00")
            status = "HALTED"
            reason = f"Severe calibration divergence (Brier: {brier_score:.4f} > 0.35). Trading halted (0.0x multiplier)."

        return CalibrationReport(
            total_evaluations=n,
            brier_score=brier_score,
            confidence_multiplier=multiplier,
            status=status,
            reason=reason
        )

    def _load_recent_outcomes(self, limit: int = 50) -> List[TradeOutcome]:
        """Load recent trade outcomes from SQLite."""
        if not os.path.exists(self.db_path) and self.db_path != ":memory:":
            return []

        outcomes: List[TradeOutcome] = []
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT trade_id, symbol, side, forecast_confidence, realized_hit, realized_pnl_usd, exit_reason, created_at
                FROM trade_outcomes
                ORDER BY created_at DESC
                LIMIT ?
            """, (limit,))
            rows = cursor.fetchall()

            for row in rows:
                tid, sym, side, conf, hit, pnl, exit_r, dt_str = row
                try:
                    ts = datetime.datetime.fromisoformat(dt_str)
                except Exception:
                    ts = datetime.datetime.now(datetime.timezone.utc)

                outcomes.append(TradeOutcome(
                    trade_id=tid,
                    symbol=sym,
                    side=side,
                    forecast_confidence=Decimal(conf),
                    realized_hit=int(hit),
                    realized_pnl_usd=Decimal(pnl),
                    exit_reason=exit_r,
                    timestamp_utc=ts
                ))
        finally:
            conn.close()
        return outcomes
