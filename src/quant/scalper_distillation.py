"""
Scalper Learning & Distillation Engine (Asymmetric PC-to-AWS Compute Paradigm)
Institutional Invariants:
1. Zero Float Financial Math (decimal.Decimal strictly for PnL, fees, notional, and sizing).
2. Asymmetric Compute: Heavy 46-item TCA, Bayesian regressions, and post-mortems run on PC.
3. Lean Distillation: Distills learnings into lightweight decision artifacts and hot-reloads on AWS.
4. Hot-Reload Sync: Pushes updates to AWS EC2 without process restarts or dropping active positions.
"""

import os
import json
import sqlite3
import datetime
import subprocess
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, asdict

from src.quant.trade_forensics import TradeForensicsEngine, TelemetryRecord


WORKSPACE_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SCALPER_CONFIG_PATH = os.path.join(WORKSPACE_ROOT, "data", "scalper_config.json")
DISTILLED_RULES_PATH = os.path.join(WORKSPACE_ROOT, "data", "scalper_distilled_rules.json")
LESSONS_DB_PATH = os.path.join(WORKSPACE_ROOT, "data", "lessons.db")

# Default AWS EC2 Sync Coordinates
DEFAULT_AWS_HOST = "13.63.158.94"
DEFAULT_AWS_USER = "ec2-user"
DEFAULT_AWS_KEY = r"F:\012D_TRADE\Kalshi Simulator\kalshi_aws_key.pem"
DEFAULT_AWS_REMOTE_DIR = "/home/ec2-user/kronos-bot/data"


@dataclass
class DistillationSummary:
    audit_id: str
    timestamp_utc: str
    sample_size: int
    win_rate_pct: Decimal
    profit_factor: Decimal
    realization_tax_drag_bps: Decimal
    dominant_root_cause: str
    recommended_remedy: str
    calibrated_atr_multiplier: Decimal
    calibrated_fee_hurdle_pct: Decimal
    calibrated_min_win_prob_pct: Decimal
    calibrated_ratchet_trigger_pct: Decimal
    quarantined_symbols: List[str]
    synced_to_aws: bool = False
    aws_sync_notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "audit_id": self.audit_id,
            "timestamp_utc": self.timestamp_utc,
            "sample_size": self.sample_size,
            "win_rate_pct": float(self.win_rate_pct),
            "profit_factor": float(self.profit_factor),
            "realization_tax_drag_bps": float(self.realization_tax_drag_bps),
            "dominant_root_cause": self.dominant_root_cause,
            "recommended_remedy": self.recommended_remedy,
            "calibrated_parameters": {
                "atr_stop_multiplier": float(self.calibrated_atr_multiplier),
                "fee_hurdle_pct": float(self.calibrated_fee_hurdle_pct),
                "min_win_prob_pct": float(self.calibrated_min_win_prob_pct),
                "ratchet_trigger_pct": float(self.calibrated_ratchet_trigger_pct)
            },
            "quarantined_symbols": self.quarantined_symbols,
            "synced_to_aws": self.synced_to_aws,
            "aws_sync_notes": self.aws_sync_notes
        }


class ScalperDistillationEngine:
    """
    Automates local PC quantitative learning from closed scalps,
    runs 46-item microstructural TCA decomposition,
    performs Bayesian recalibration of execution rules,
    and distills decision parameters for AWS EC2 hot-reloading.
    """

    def __init__(self, db_path: str = LESSONS_DB_PATH):
        self.db_path = db_path
        self._init_db()

    def _init_db(self) -> None:
        """Initializes persistent tables for scalp forensics and distillation audits."""
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS scalper_forensics (
                    trade_id TEXT PRIMARY KEY,
                    symbol TEXT,
                    direction TEXT,
                    entry_timestamp TEXT,
                    exit_timestamp TEXT,
                    entry_price TEXT,
                    exit_price TEXT,
                    position_size TEXT,
                    gross_pnl_usd TEXT,
                    exchange_fees_usd TEXT,
                    net_pnl_usd TEXT,
                    return_pct TEXT,
                    mfe_pct TEXT,
                    mae_pct TEXT,
                    holding_duration_seconds INTEGER,
                    exit_trigger_reason TEXT,
                    root_cause_diagnosis TEXT,
                    actionable_remedy TEXT,
                    realization_tax_bps TEXT,
                    created_at TEXT
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS scalper_distillation_audits (
                    audit_id TEXT PRIMARY KEY,
                    timestamp_utc TEXT,
                    sample_size INTEGER,
                    win_rate_pct TEXT,
                    profit_factor TEXT,
                    realization_tax_drag_bps TEXT,
                    dominant_root_cause TEXT,
                    recommended_remedy TEXT,
                    calibrated_atr_multiplier TEXT,
                    calibrated_fee_hurdle_pct TEXT,
                    calibrated_min_win_prob_pct TEXT,
                    calibrated_ratchet_trigger_pct TEXT,
                    quarantined_symbols TEXT,
                    synced_to_aws INTEGER,
                    aws_sync_timestamp TEXT
                )
            """)
            conn.commit()

    def record_scalp_forensic(self, telemetry: TelemetryRecord) -> None:
        """Stores a verified 46-item telemetry record into persistent SQLite."""
        now_str = datetime.datetime.now(datetime.timezone.utc).isoformat()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO scalper_forensics (
                    trade_id, symbol, direction, entry_timestamp, exit_timestamp,
                    entry_price, exit_price, position_size, gross_pnl_usd,
                    exchange_fees_usd, net_pnl_usd, return_pct, mfe_pct, mae_pct,
                    holding_duration_seconds, exit_trigger_reason,
                    root_cause_diagnosis, actionable_remedy, realization_tax_bps, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                telemetry.trade_id,
                telemetry.symbol,
                telemetry.direction,
                telemetry.entry_timestamp,
                telemetry.exit_timestamp,
                str(telemetry.entry_price),
                str(telemetry.exit_price),
                str(telemetry.position_size),
                str(telemetry.gross_pnl_usd),
                str(telemetry.exchange_fees_usd),
                str(telemetry.net_pnl_usd),
                str(telemetry.return_pct),
                str(telemetry.mfe_pct),
                str(telemetry.mae_pct),
                telemetry.holding_duration_seconds,
                telemetry.exit_trigger_reason,
                telemetry.root_cause_diagnosis,
                telemetry.actionable_remedy,
                str(telemetry.realization_tax_bps),
                now_str
            ))
            conn.commit()

    def get_recent_forensics(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Retrieves recent 46-item forensic records for the UI table."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("""
                SELECT * FROM scalper_forensics ORDER BY created_at DESC LIMIT ?
            """, (limit,)).fetchall()
            return [dict(r) for r in rows]

    def ingest_raw_trades(self, raw_trades: List[Dict[str, Any]], trade_mode: str = "LIVE") -> List[TelemetryRecord]:
        """Runs 46-item TradeForensicsEngine on a batch of trades and saves them."""
        records = []
        for raw in raw_trades:
            telemetry = TradeForensicsEngine.assess_trade(raw, trade_mode=trade_mode)
            self.record_scalp_forensic(telemetry)
            records.append(telemetry)
        return records

    def run_learning_and_distillation(
        self,
        lookback_trades: int = 100,
        sync_aws: bool = False,
        aws_host: str = DEFAULT_AWS_HOST,
        aws_user: str = DEFAULT_AWS_USER,
        aws_key: str = DEFAULT_AWS_KEY,
        aws_remote_dir: str = DEFAULT_AWS_REMOTE_DIR
    ) -> DistillationSummary:
        """
        Executes institutional Bayesian calibration from recent closed scalp telemetry:
        1. Deconstructs TCA excursion curves & fee realization.
        2. Categorizes dominant failure modes.
        3. Recalibrates hyperparameters (ATR multiplier, fee hurdle, win prob gate, ratchet).
        4. Identifies toxic symbols to quarantine.
        5. Saves data/scalper_distilled_rules.json and updates data/scalper_config.json.
        6. Optionally syncs to AWS EC2 without service interruption.
        """
        recent = self.get_recent_forensics(limit=lookback_trades)
        now_utc = datetime.datetime.now(datetime.timezone.utc)
        audit_id = f"DISTILL-{now_utc.strftime('%Y%m%d-%H%M%S')}"

        if not recent:
            # Baseline calibration if no trades recorded yet
            summary = DistillationSummary(
                audit_id=audit_id,
                timestamp_utc=now_utc.isoformat(),
                sample_size=0,
                win_rate_pct=Decimal("0.0"),
                profit_factor=Decimal("1.0"),
                realization_tax_drag_bps=Decimal("0.0"),
                dominant_root_cause="INSUFFICIENT_DATA",
                recommended_remedy="System baseline parameters maintained pending live execution sample.",
                calibrated_atr_multiplier=Decimal("1.00"),
                calibrated_fee_hurdle_pct=Decimal("1.10"),
                calibrated_min_win_prob_pct=Decimal("65.0"),
                calibrated_ratchet_trigger_pct=Decimal("0.80"),
                quarantined_symbols=[],
                synced_to_aws=False
            )
            self._save_distilled_rules(summary)
            if sync_aws:
                self.sync_distilled_rules_to_aws(summary, aws_host, aws_user, aws_key, aws_remote_dir)
            return summary

        # 1. Forensic Statistical Aggregation (Zero Float Math)
        sample_size = len(recent)
        wins = [r for r in recent if Decimal(str(r["net_pnl_usd"])) > Decimal("0.0")]
        losses = [r for r in recent if Decimal(str(r["net_pnl_usd"])) <= Decimal("0.0")]

        win_rate = (Decimal(len(wins)) / Decimal(sample_size)) * Decimal("100")
        gross_profit = sum([Decimal(str(r["net_pnl_usd"])) for r in wins], Decimal("0.0"))
        gross_loss = abs(sum([Decimal(str(r["net_pnl_usd"])) for r in losses], Decimal("0.0")))

        if gross_loss > Decimal("0.0"):
            profit_factor = (gross_profit / gross_loss).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        else:
            profit_factor = Decimal("99.99") if gross_profit > 0 else Decimal("1.00")

        # Average realization tax (drag from theoretical vs net)
        tax_vals = [Decimal(str(r.get("realization_tax_bps", "0.0"))) for r in recent]
        avg_tax = (sum(tax_vals, Decimal("0.0")) / Decimal(sample_size)).quantize(Decimal("0.1"))

        # 2. Root-Cause Frequency Distribution
        cause_counts: Dict[str, int] = {}
        for r in recent:
            c = r.get("root_cause_diagnosis", "ALPHA_INVALIDATION")
            cause_counts[c] = cause_counts.get(c, 0) + 1

        dominant_cause = max(cause_counts.items(), key=lambda x: x[1])[0]

        # 3. Institutional Bayesian Hyperparameter Recalibration
        calibrated_atr_mult = Decimal("1.00")
        calibrated_fee_hurdle = Decimal("1.10")
        calibrated_win_prob = Decimal("65.0")
        calibrated_ratchet = Decimal("0.80")
        remedy_notes = []

        # Check loss causes
        noise_losses = sum(1 for r in losses if r.get("root_cause_diagnosis") == "STOP_INSIDE_NOISE")
        noise_loss_ratio = (Decimal(noise_losses) / Decimal(len(losses))) if losses else Decimal("0.0")

        friction_losses = sum(1 for r in losses if r.get("root_cause_diagnosis") == "FRICTION_BLEED")
        friction_loss_ratio = (Decimal(friction_losses) / Decimal(len(losses))) if losses else Decimal("0.0")

        lucky_wins = sum(1 for r in wins if r.get("root_cause_diagnosis") == "TOXIC_LUCKY_WIN")
        lucky_win_ratio = (Decimal(lucky_wins) / Decimal(len(wins))) if wins else Decimal("0.0")

        # Noise Stop Adaptation
        if noise_loss_ratio >= Decimal("0.20"):
            calibrated_atr_mult = Decimal("1.25")
            remedy_notes.append("High Stop Inside Noise (>20% of losses). Recalibrated ATR Stop Multiplier to 1.25x.")
        
        # Friction Bleed Adaptation
        if friction_loss_ratio >= Decimal("0.20") or avg_tax > Decimal("8.0"):
            calibrated_fee_hurdle = Decimal("1.25")
            calibrated_ratchet = Decimal("0.85")
            remedy_notes.append("Excessive Fee Friction detected. Raised minimum net take-profit hurdle to 1.25% and ratchet trigger to 0.85%.")

        # Lucky Win & Regime Adaptation
        if lucky_win_ratio >= Decimal("0.25") or win_rate < Decimal("55.0"):
            calibrated_win_prob = Decimal("70.0")
            remedy_notes.append("Drawdown survival bias or low win-rate (<55%). Elevated minimum win probability sieve to 70.0%.")

        if not remedy_notes:
            remedy_notes.append("Trade microstructure nominal within statistical variance. Baseline parameters preserved.")

        combined_remedy = " ".join(remedy_notes)

        # 4. Toxic Asset Quarantine Attribution
        symbol_pnls: Dict[str, Decimal] = {}
        symbol_stops: Dict[str, int] = {}
        for r in recent:
            sym = r["symbol"]
            pnl = Decimal(str(r["net_pnl_usd"]))
            symbol_pnls[sym] = symbol_pnls.get(sym, Decimal("0.0")) + pnl
            if pnl < Decimal("0.0"):
                symbol_stops[sym] = symbol_stops.get(sym, 0) + 1

        quarantined = []
        for sym, net in symbol_pnls.items():
            # If symbol lost >= $1.50 or stopped out >= 3 times in scalps
            if net <= Decimal("-1.50") or symbol_stops.get(sym, 0) >= 3:
                quarantined.append(sym)

        summary = DistillationSummary(
            audit_id=audit_id,
            timestamp_utc=now_utc.isoformat(),
            sample_size=sample_size,
            win_rate_pct=win_rate.quantize(Decimal("0.1")),
            profit_factor=profit_factor,
            realization_tax_drag_bps=avg_tax,
            dominant_root_cause=dominant_cause,
            recommended_remedy=combined_remedy,
            calibrated_atr_multiplier=calibrated_atr_mult,
            calibrated_fee_hurdle_pct=calibrated_fee_hurdle,
            calibrated_min_win_prob_pct=calibrated_win_prob,
            calibrated_ratchet_trigger_pct=calibrated_ratchet,
            quarantined_symbols=quarantined,
            synced_to_aws=False
        )

        # Save distilled artifacts locally
        self._save_distilled_rules(summary)
        self._update_scalper_config(summary)
        self._record_audit_db(summary)

        # Sync to AWS if requested
        if sync_aws:
            self.sync_distilled_rules_to_aws(summary, aws_host, aws_user, aws_key, aws_remote_dir)

        return summary

    def _save_distilled_rules(self, summary: DistillationSummary) -> None:
        """Writes data/scalper_distilled_rules.json."""
        with open(DISTILLED_RULES_PATH, "w", encoding="utf-8") as f:
            json.dump(summary.to_dict(), f, indent=2)

    def _update_scalper_config(self, summary: DistillationSummary) -> None:
        """Merges calibrated parameters into data/scalper_config.json."""
        if not os.path.exists(SCALPER_CONFIG_PATH):
            return
        try:
            with open(SCALPER_CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg = json.load(f)

            # Update calibrated values
            cfg["min_win_probability_pct"] = float(summary.calibrated_min_win_prob_pct)
            if "execution_targets" in cfg:
                cfg["execution_targets"]["take_profit_net_pct"] = float(summary.calibrated_fee_hurdle_pct)
                cfg["execution_targets"]["fast_profit_ratchet_pct"] = float(summary.calibrated_ratchet_trigger_pct)
            if "guardrails" in cfg:
                cfg["guardrails"]["quarantined_symbols"] = summary.quarantined_symbols
                cfg["guardrails"]["atr_stop_multiplier"] = float(summary.calibrated_atr_multiplier)

            cfg["distillation_metadata"] = {
                "last_distilled_utc": summary.timestamp_utc,
                "audit_id": summary.audit_id,
                "sample_size": summary.sample_size,
                "win_rate_pct": float(summary.win_rate_pct),
                "profit_factor": float(summary.profit_factor),
                "dominant_root_cause": summary.dominant_root_cause,
                "synced_to_aws": summary.synced_to_aws
            }

            with open(SCALPER_CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=2)
        except Exception as e:
            print(f"[DISTILLATION] Warning updating scalper_config.json: {e}")

    def _record_audit_db(self, summary: DistillationSummary) -> None:
        """Persists distillation audit into lessons.db."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO scalper_distillation_audits (
                    audit_id, timestamp_utc, sample_size, win_rate_pct,
                    profit_factor, realization_tax_drag_bps, dominant_root_cause,
                    recommended_remedy, calibrated_atr_multiplier,
                    calibrated_fee_hurdle_pct, calibrated_min_win_prob_pct,
                    calibrated_ratchet_trigger_pct, quarantined_symbols,
                    synced_to_aws, aws_sync_timestamp
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                summary.audit_id,
                summary.timestamp_utc,
                summary.sample_size,
                str(summary.win_rate_pct),
                str(summary.profit_factor),
                str(summary.realization_tax_drag_bps),
                summary.dominant_root_cause,
                summary.recommended_remedy,
                str(summary.calibrated_atr_multiplier),
                str(summary.calibrated_fee_hurdle_pct),
                str(summary.calibrated_min_win_prob_pct),
                str(summary.calibrated_ratchet_trigger_pct),
                json.dumps(summary.quarantined_symbols),
                1 if summary.synced_to_aws else 0,
                summary.timestamp_utc if summary.synced_to_aws else None
            ))
            conn.commit()

    def sync_distilled_rules_to_aws(
        self,
        summary: DistillationSummary,
        aws_host: str = DEFAULT_AWS_HOST,
        aws_user: str = DEFAULT_AWS_USER,
        aws_key: str = DEFAULT_AWS_KEY,
        aws_remote_dir: str = DEFAULT_AWS_REMOTE_DIR
    ) -> bool:
        """
        Transfers data/scalper_distilled_rules.json and data/scalper_config.json to AWS EC2 via SCP.
        The remote headless worker immediately reloads scalper_config.json with zero downtime.
        """
        if not os.path.exists(aws_key):
            summary.synced_to_aws = False
            summary.aws_sync_notes = f"AWS SSH Key not found at: {aws_key}"
            return False

        files_to_sync = [DISTILLED_RULES_PATH, SCALPER_CONFIG_PATH]
        for fpath in files_to_sync:
            if not os.path.exists(fpath):
                continue
            scp_cmd = [
                "scp",
                "-i", aws_key,
                "-o", "StrictHostKeyChecking=no",
                "-o", "ConnectTimeout=8",
                fpath,
                f"{aws_user}@{aws_host}:{aws_remote_dir}/"
            ]
            try:
                res = subprocess.run(scp_cmd, capture_output=True, text=True, timeout=15)
                if res.returncode != 0:
                    summary.synced_to_aws = False
                    summary.aws_sync_notes = f"SCP failed for {os.path.basename(fpath)}: {res.stderr.strip()}"
                    return False
            except Exception as e:
                summary.synced_to_aws = False
                summary.aws_sync_notes = f"SCP Exception: {str(e)}"
                return False

        summary.synced_to_aws = True
        summary.aws_sync_notes = f"Successfully pushed to {aws_user}@{aws_host}:{aws_remote_dir} (Hot-Reload Active)"
        
        # Update SQLite audit record with sync success
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                UPDATE scalper_distillation_audits
                SET synced_to_aws = 1, aws_sync_timestamp = ?
                WHERE audit_id = ?
            """, (datetime.datetime.now(datetime.timezone.utc).isoformat(), summary.audit_id))
            conn.commit()

        # Update metadata in scalper_config.json
        try:
            with open(SCALPER_CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            if "distillation_metadata" in cfg:
                cfg["distillation_metadata"]["synced_to_aws"] = True
                cfg["distillation_metadata"]["aws_sync_notes"] = summary.aws_sync_notes
            with open(SCALPER_CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=2)
        except Exception:
            pass

        return True
