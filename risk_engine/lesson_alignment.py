"""
risk_engine/lesson_alignment.py — Two-Tier Lesson-to-Risk Alignment & Conflict Auditor.

Audits `data/lessons.db` against `RiskConfig` using a strict two-tier taxonomy so
timeless mathematical invariants are hard-enforced while small-sample empirical
heuristics are tracked with explicit `supersedes` chains (preventing heuristic
fossilization and false boot conflicts).

Zero dependency on alpha generation modules.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
import os
import sqlite3
from typing import Callable, Dict, List, Optional, Tuple

from risk_engine.config import RiskConfig


class LessonTier(str, Enum):
    STRUCTURAL_INVARIANT = "STRUCTURAL_INVARIANT"  # Timeless math / execution survival rule (hard check)
    REGIME_HEURISTIC = "REGIME_HEURISTIC"          # Empirical strategy rule (drift-monitored, superseding chain)
    NON_RISK_SYSTEM = "NON_RISK_SYSTEM"            # UI / tooling / ML pipeline / coding hygiene


@dataclass(frozen=True)
class LessonBinding:
    lesson_id: int
    tier: LessonTier
    owner: str
    summary: str
    supersedes: Tuple[int, ...] = ()
    invariant_check: Optional[Callable[[RiskConfig], Tuple[bool, str]]] = None


@dataclass(frozen=True)
class AlignmentIssue:
    severity: str       # "ERROR" | "WARNING"
    code: str           # "UNMAPPED_TRADING_LESSON" | "STRUCTURAL_INVARIANT_CONFLICT" | "DEADLOCK_RISK"
    lesson_id: Optional[int]
    message: str


@dataclass(frozen=True)
class LessonAlignmentReport:
    total_lessons_in_db: int
    mapped_count: int
    structural_invariants_passed: int
    structural_invariants_failed: int
    issues: List[AlignmentIssue] = field(default_factory=list)

    @property
    def is_aligned(self) -> bool:
        return not any(i.severity == "ERROR" for i in self.issues)


def _check_zero_float(cfg: RiskConfig) -> Tuple[bool, str]:
    ok = isinstance(cfg.kelly_fraction, Decimal) and isinstance(cfg.max_portfolio_open_stop_risk_pct, Decimal)
    return ok, "Config financial bounds use decimal.Decimal"


def _check_fee_hurdle(cfg: RiskConfig) -> Tuple[bool, str]:
    ok = cfg.min_cost_multiple >= Decimal("1.50") and cfg.min_rr_ratio >= Decimal("1.20")
    return ok, f"min_cost_multiple={cfg.min_cost_multiple} (>=1.50), min_rr_ratio={cfg.min_rr_ratio} (>=1.20)"


def _check_same_symbol_lock(cfg: RiskConfig) -> Tuple[bool, str]:
    ok = cfg.max_positions_per_symbol <= 1
    return ok, f"max_positions_per_symbol={cfg.max_positions_per_symbol} (<=1)"


def _check_stop_noise_floor(cfg: RiskConfig) -> Tuple[bool, str]:
    ok = cfg.require_stop_loss_on_entries and cfg.min_stop_distance_pct >= Decimal("0.0066")
    return ok, f"require_stop_loss={cfg.require_stop_loss_on_entries}, min_stop_distance_pct={cfg.min_stop_distance_pct} (>=0.0066)"


def _check_sl_roi_clamp(cfg: RiskConfig) -> Tuple[bool, str]:
    ok = cfg.max_sl_roi_pct <= Decimal("0.06")
    return ok, f"max_sl_roi_pct={cfg.max_sl_roi_pct} (<=0.06)"


def _check_rate_limiter(cfg: RiskConfig) -> Tuple[bool, str]:
    ok = cfg.max_api_messages_per_second <= 20 and cfg.max_api_messages_per_minute <= 600
    return ok, f"rate_limit={cfg.max_api_messages_per_second}/s, {cfg.max_api_messages_per_minute}/m"


def _check_halt_exit_liberation(cfg: RiskConfig) -> Tuple[bool, str]:
    ok = cfg.allow_reduce_only_in_non_desync_halt is True
    return ok, f"allow_reduce_only_in_non_desync_halt={cfg.allow_reduce_only_in_non_desync_halt}"


def _check_concurrency_not_starved(cfg: RiskConfig) -> Tuple[bool, str]:
    ok = cfg.max_concurrent_positions >= 2 and cfg.tier1_max_concurrent_positions >= 1
    return ok, f"max_concurrent_positions={cfg.max_concurrent_positions} (>=2), tier1={cfg.tier1_max_concurrent_positions}"


def _check_small_account_btc_and_risk_integrity(cfg: RiskConfig) -> Tuple[bool, str]:
    # $200 account must allow 0.001 BTC (~$75) fat-finger floor >= $100 AND cap net leverage <= 1.0x
    ff_200 = cfg.effective_fat_finger_notional_usd(Decimal("200"))
    net_200 = cfg.effective_max_net_leverage(Decimal("200"))
    ok = ff_200 >= Decimal("100") and ff_200 <= Decimal("500") and net_200 <= Decimal("1.00")
    return ok, f"small_account_ff($200)={ff_200}, small_account_net_lev={net_200}"


def _check_kelly_no_double_penalty(cfg: RiskConfig) -> Tuple[bool, str]:
    ok = cfg.kelly_apply_decay_only_to_gross and cfg.win_rate_decay_buffer <= Decimal("0.01")
    return ok, f"kelly_apply_decay_only_to_gross={cfg.kelly_apply_decay_only_to_gross}, win_rate_decay_buffer={cfg.win_rate_decay_buffer}"


LESSON_REGISTRY: Dict[int, LessonBinding] = {
    # --- Timeless Structural Invariants (Hard-Enforced Against RiskConfig) ---
    2: LessonBinding(2, LessonTier.STRUCTURAL_INVARIANT, "risk_engine.models", "Zero-float Decimal financial math", invariant_check=_check_zero_float),
    4: LessonBinding(4, LessonTier.STRUCTURAL_INVARIANT, "risk_engine.sizing", "Net EV over raw win rate; no double-penalized Kelly starvation", invariant_check=_check_kelly_no_double_penalty),
    10: LessonBinding(10, LessonTier.STRUCTURAL_INVARIANT, "risk_engine.oms", "Positive net-of-fee hurdle & R:R floor", invariant_check=_check_fee_hurdle),
    15: LessonBinding(15, LessonTier.STRUCTURAL_INVARIANT, "risk_engine.oms", "Alpha-agnostic same-symbol position lock (<=1)", invariant_check=_check_same_symbol_lock),
    16: LessonBinding(16, LessonTier.STRUCTURAL_INVARIANT, "risk_engine.oms", "Vanishing-stop leverage guard & mandatory SL", invariant_check=_check_stop_noise_floor),
    17: LessonBinding(17, LessonTier.STRUCTURAL_INVARIANT, "risk_engine.gateway+capital_recycler", "Stale trade exit liberation even during non-desync HALT", invariant_check=_check_halt_exit_liberation),
    25: LessonBinding(25, LessonTier.STRUCTURAL_INVARIANT, "risk_engine.oms", "Hard leveraged SL ROI clamp (<=6.0%)", invariant_check=_check_sl_roi_clamp),
    27: LessonBinding(27, LessonTier.STRUCTURAL_INVARIANT, "risk_engine.gateway", "Exchange API message rate-limit enforcement", invariant_check=_check_rate_limiter),
    29: LessonBinding(29, LessonTier.STRUCTURAL_INVARIANT, "risk_engine.sizing", "Small-account risk-at-stop parity & correlated net-beta cap", invariant_check=_check_small_account_btc_and_risk_integrity),
    37: LessonBinding(37, LessonTier.STRUCTURAL_INVARIANT, "risk_engine.oms", "Anti-fee-cannibalization net friction multiple", supersedes=(10,), invariant_check=_check_fee_hurdle),
    39: LessonBinding(39, LessonTier.STRUCTURAL_INVARIANT, "risk_engine.oms", "Minimum stop-loss noise floor (>=0.66%)", invariant_check=_check_stop_noise_floor),
    40: LessonBinding(40, LessonTier.STRUCTURAL_INVARIANT, "risk_engine.oms", "Avoid over-conservative concurrency starvation", invariant_check=_check_concurrency_not_starved),
    41: LessonBinding(41, LessonTier.STRUCTURAL_INVARIANT, "risk_engine.gateway+capital_recycler", "Capital recycler exits permitted during non-desync HALT", invariant_check=_check_halt_exit_liberation),
    45: LessonBinding(45, LessonTier.STRUCTURAL_INVARIANT, "execution_realism+risk_engine.reconciler", "Truth-grade execution realism & exchange reconciliation"),

    # --- Regime-Fitted Empirical Heuristics (Strategy Layer with Supersedes Chain) ---
    11: LessonBinding(11, LessonTier.REGIME_HEURISTIC, "quant_flaw_auditor", "Backtest lookahead & hyper-compounding guard"),
    12: LessonBinding(12, LessonTier.REGIME_HEURISTIC, "trade_forensics", "Separate signal edge from fee friction in post-trade audit"),
    13: LessonBinding(13, LessonTier.REGIME_HEURISTIC, "apex_scalper", "Single-slot (N=1) scalper clutter prevention"),
    14: LessonBinding(14, LessonTier.REGIME_HEURISTIC, "apex_scalper", "Avoid chasing lagging 5m green candles"),
    18: LessonBinding(18, LessonTier.REGIME_HEURISTIC, "apex_scalper", "Volatility-buffered ratchet & universe hygiene"),
    19: LessonBinding(19, LessonTier.REGIME_HEURISTIC, "apex_scalper", "Stoikov micro-price & dynamic temporal expiry"),
    20: LessonBinding(20, LessonTier.REGIME_HEURISTIC, "apex_scalper", "Scalper breakeven choke & fee bleed prevention"),
    21: LessonBinding(21, LessonTier.REGIME_HEURISTIC, "apex_scalper", "Adaptive harvest clamp at +1.0% to +1.5%"),
    22: LessonBinding(22, LessonTier.REGIME_HEURISTIC, "orchestrator", "15-minute post-exit symbol cooldown"),
    24: LessonBinding(24, LessonTier.REGIME_HEURISTIC, "storm_protocol", "Tsunami 3-phase shock pause & 60m auto-recovery"),
    26: LessonBinding(26, LessonTier.REGIME_HEURISTIC, "tiger_scalper+config", "Dual-regime volatility brackets", supersedes=(21,)),
    28: LessonBinding(28, LessonTier.REGIME_HEURISTIC, "tiger_orderflow", "Tiger macro shield & Wyckoff confirmation"),
    32: LessonBinding(32, LessonTier.REGIME_HEURISTIC, "tiger_orderflow", "Trapped-trader delta OI climax filter"),
    33: LessonBinding(33, LessonTier.REGIME_HEURISTIC, "tiger_scalper", "Anti-burst slot locking & 60s fleet cooldown"),
    34: LessonBinding(34, LessonTier.REGIME_HEURISTIC, "learning_governor", "Dual-track Bayesian learning & autopsy"),
    35: LessonBinding(35, LessonTier.REGIME_HEURISTIC, "tiger_orderflow", "Strict OI affirmation & 5m plateau ratchet"),
    36: LessonBinding(36, LessonTier.REGIME_HEURISTIC, "tiger_scanner", "Exclude active/quarantined symbols from scanner sieve"),
    38: LessonBinding(38, LessonTier.REGIME_HEURISTIC, "macro_specialists", "Macro session liquidity windows (14:00-15:00 & 22:00-03:00 UTC)"),
    42: LessonBinding(42, LessonTier.REGIME_HEURISTIC, "orchestrator", "US Open extension (14:00-15:30 UTC), neural gate & 30m directional flip hysteresis", supersedes=(38,)),
    43: LessonBinding(43, LessonTier.REGIME_HEURISTIC, "tiger_orderflow", "Tiger falling-knife guard & buy asymmetry"),
    44: LessonBinding(44, LessonTier.REGIME_HEURISTIC, "tiger_scalper", "Do NOT apply Macro 22:00-02:59 UTC session block to Tiger; tighten Tiger buy wick", supersedes=(38, 43)),

    # --- Non-Risk System / Coding / App Lessons ---
    1: LessonBinding(1, LessonTier.NON_RISK_SYSTEM, "kronos_onnx_engine", "512-candle tail slicing contract"),
    3: LessonBinding(3, LessonTier.NON_RISK_SYSTEM, "tooling", "Graphify code-only hygiene"),
    5: LessonBinding(5, LessonTier.NON_RISK_SYSTEM, "infra", "Windows SSL cert handling"),
    6: LessonBinding(6, LessonTier.NON_RISK_SYSTEM, "webui", "WebUI chart return fix"),
    7: LessonBinding(7, LessonTier.NON_RISK_SYSTEM, "webui", "Plotly JSON bdata serialization"),
    8: LessonBinding(8, LessonTier.NON_RISK_SYSTEM, "webui", "TradingView lightweight charts"),
    9: LessonBinding(9, LessonTier.NON_RISK_SYSTEM, "webui", "Headless /api/predict empty comparison guard"),
    23: LessonBinding(23, LessonTier.NON_RISK_SYSTEM, "infra", "Asymmetric PC learning / AWS distillation"),
    30: LessonBinding(30, LessonTier.NON_RISK_SYSTEM, "scripts.tiger_worker", "Tiger worker loop indentation heartbeat"),
    31: LessonBinding(31, LessonTier.NON_RISK_SYSTEM, "scripts.system_hygiene", "Cross-platform storage hygiene"),
}


def audit_lesson_alignment(
    config: RiskConfig,
    lessons_db_path: str = "data/lessons.db",
) -> LessonAlignmentReport:
    """
    Audit all rows in `data/lessons.db` against `RiskConfig`:
    1. Flags any unmapped `category='trading'` lesson as an ERROR.
    2. Executes every `STRUCTURAL_INVARIANT` check against `config` and flags conflicts as ERROR.
    3. Flags cross-check deadlock hazards (e.g. rolling drawdown tighter than intraday drawdown).
    """
    issues: List[AlignmentIssue] = []
    db_rows: List[Tuple[int, str, str]] = []

    if os.path.exists(lessons_db_path):
        conn = sqlite3.connect(lessons_db_path)
        try:
            db_rows = conn.execute(
                "SELECT id, category, trigger_keyword FROM lessons ORDER BY id;"
            ).fetchall()
        finally:
            conn.close()

    mapped_count = 0
    passed_invariants = 0
    failed_invariants = 0

    for lid, category, kw in db_rows:
        binding = LESSON_REGISTRY.get(lid)
        if binding is None:
            sev = "ERROR" if str(category).lower() == "trading" else "WARNING"
            issues.append(
                AlignmentIssue(
                    severity=sev,
                    code="UNMAPPED_TRADING_LESSON" if sev == "ERROR" else "UNMAPPED_SYSTEM_LESSON",
                    lesson_id=lid,
                    message=f"Lesson #{lid} ({category}: {kw}) is not registered in LESSON_REGISTRY.",
                )
            )
            continue

        mapped_count += 1
        if binding.tier == LessonTier.STRUCTURAL_INVARIANT and binding.invariant_check is not None:
            ok, detail = binding.invariant_check(config)
            if ok:
                passed_invariants += 1
            else:
                failed_invariants += 1
                issues.append(
                    AlignmentIssue(
                        severity="ERROR",
                        code="STRUCTURAL_INVARIANT_CONFLICT",
                        lesson_id=lid,
                        message=f"Lesson #{lid} ({binding.summary}) violated by RiskConfig: {detail}",
                    )
                )

    # Cross-rule structural sanity checks (Deadlock / Contradiction detection)
    if config.tier2_rolling_drawdown_pct < config.tier2_drawdown_pct:
        issues.append(
            AlignmentIssue(
                severity="ERROR",
                code="DEADLOCK_RISK",
                lesson_id=None,
                message="tier2_rolling_drawdown_pct should be >= tier2_drawdown_pct (intraday) to avoid false variance halts.",
            )
        )
    if config.max_portfolio_open_stop_risk_pct < config.max_single_trade_stop_risk_pct:
        issues.append(
            AlignmentIssue(
                severity="ERROR",
                code="DEADLOCK_RISK",
                lesson_id=None,
                message="max_portfolio_open_stop_risk_pct cannot be smaller than max_single_trade_stop_risk_pct.",
            )
        )

    return LessonAlignmentReport(
        total_lessons_in_db=len(db_rows),
        mapped_count=mapped_count,
        structural_invariants_passed=passed_invariants,
        structural_invariants_failed=failed_invariants,
        issues=issues,
    )
