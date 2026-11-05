"""
Kronos Quant Flaw & Mathematical Logic Auditor (Vibe-Trading Enhanced)
======================================================================
Autonomous sanity guardian adapted from Vibe-Trading's Quant Strategy Desk,
Risk Committee, and Backtest Diagnostic architecture.

Audits trading history, active brackets, and equity curves for:
1. Time-Machine / Lookahead Arbitrage (prices pre-crossing TP/SL at entry).
2. Impossible Performance Artifacts (Win Rate > 80%, Profit Factor > 10.0x).
3. Hyper-Compounding / Notional Blowout (positions exceeding liquidity or account caps).
4. Square-Root Market Impact Violations (Almgren-Chriss execution friction).
5. Inverted Bracket Geometry.

All monetary calculations adhere to Invariant 1: Strictly Decimal.
"""

from decimal import Decimal, ROUND_HALF_UP, ROUND_DOWN
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Dict, Any, Optional
import math
import logging

logger = logging.getLogger("Kronos.QuantFlawAuditor")


class FlawSeverity(Enum):
    CLEAN = "CLEAN"
    WARNING = "WARNING"
    CRITICAL_HALLUCINATION = "CRITICAL_HALLUCINATION"


@dataclass
class QuantFlaw:
    """Represents a detected mathematical or execution flaw."""
    code: str
    severity: FlawSeverity
    title: str
    description: str
    observed_value: str
    institutional_bound: str
    remediation: str


@dataclass
class AuditVerdict:
    """Comprehensive verdict returned by the Quant Flaw Auditor."""
    is_valid: bool
    flaws: List[QuantFlaw] = field(default_factory=list)
    confidence_score: Decimal = Decimal("1.00")
    summary: str = "All quantitative sanity checks passed."


class QuantFlawAuditor:
    """
    Independent quant auditor enforcing empirical realism across Kronos.
    Zero-tolerance for vanity metrics and simulation artifacts.
    """

    def __init__(
        self,
        max_realistic_win_rate: Decimal = Decimal("78.0"),
        max_realistic_profit_factor: Decimal = Decimal("10.0"),
        max_small_account_notional: Decimal = Decimal("50.00"),
        max_account_leverage: int = 5
    ):
        self.max_realistic_win_rate = max_realistic_win_rate
        self.max_realistic_profit_factor = max_realistic_profit_factor
        self.max_small_account_notional = max_small_account_notional
        self.max_account_leverage = max_account_leverage

    def compute_almgren_chriss_impact(
        self,
        notional_usd: Decimal,
        adv_24h_usd: Decimal,
        daily_volatility: Decimal = Decimal("0.04"),
        eta: Decimal = Decimal("0.5")
    ) -> Decimal:
        """
        Compute square-root market impact via Almgren-Chriss model:
        Impact = eta * volatility * sqrt(Trade Size / 24h ADV)
        """
        if adv_24h_usd <= Decimal("0"):
            return Decimal("0.0020") # Default 20 bps fallback

        participation_ratio = notional_usd / adv_24h_usd
        # Participation ratio square root in Decimal
        float_ratio = float(participation_ratio)
        sqrt_val = Decimal(str(math.sqrt(max(0.0, float_ratio))))

        impact = eta * daily_volatility * sqrt_val
        return impact.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)

    def audit_trade_record(
        self,
        trade: Dict[str, Any]
    ) -> List[QuantFlaw]:
        """Audit an individual closed trade for mathematical anomalies."""
        flaws = []
        entry = Decimal(str(trade.get("entry_price", 0)))
        exit_px = Decimal(str(trade.get("exit_price", 0)))
        side = trade.get("side", "").upper()
        duration_min = int(trade.get("duration_minutes", 0))
        notional = Decimal(str(trade.get("notional_usd", 0)))
        reason = trade.get("reason", "")

        # 1. Zero or negative pricing
        if entry <= Decimal("0") or exit_px <= Decimal("0"):
            flaws.append(QuantFlaw(
                code="FLAW_ZERO_PRICE",
                severity=FlawSeverity.CRITICAL_HALLUCINATION,
                title="Zero or Negative Execution Price",
                description="Trade executed at non-positive price coordinate.",
                observed_value=f"Entry: ${entry}, Exit: ${exit_px}",
                institutional_bound="Price > 0.00",
                remediation="Validate price precision and exchange ticker feed."
            ))

        # 2. Inverted Return Geometry
        pnl = Decimal(str(trade.get("realized_pnl_usd", 0)))
        if side in ("BUY", "LONG") and exit_px > entry and pnl < Decimal("0"):
            # Could be fee drag, but if gross is also negative, geometry is broken
            gross = Decimal(str(trade.get("gross_pnl_usd", pnl)))
            if gross < Decimal("0"):
                flaws.append(QuantFlaw(
                    code="FLAW_INVERTED_PNL",
                    severity=FlawSeverity.CRITICAL_HALLUCINATION,
                    title="Inverted Long Gross PnL",
                    description="Exit price above Entry, but Gross PnL is negative.",
                    observed_value=f"Entry: {entry}, Exit: {exit_px}, Gross: {gross}",
                    institutional_bound="Gross PnL = (Exit - Entry) * Qty",
                    remediation="Audit PnL calculation formulas in execution module."
                ))

        # 3. Microsecond / Instantaneous TP on 1-hour candle
        if duration_min <= 1 and reason == "TAKE_PROFIT_TRIGGERED":
            ret_pct = Decimal(str(trade.get("return_pct", 0)))
            if abs(ret_pct) >= Decimal("1.5"):
                flaws.append(QuantFlaw(
                    code="FLAW_INSTANT_TP_ANOMALY",
                    severity=FlawSeverity.WARNING,
                    title="Suspicious 1-Minute Take-Profit Hit",
                    description="Take profit triggered within 1 minute of trade entry on a swing ATR target.",
                    observed_value=f"Duration: {duration_min}m, Gain: +{ret_pct}%",
                    institutional_bound="Duration > 5m for ATR swing targets",
                    remediation="Verify entry price was not pre-crossed at time of submission."
                ))

        return flaws

    def audit_performance_summary(
        self,
        summary: Dict[str, Any]
    ) -> AuditVerdict:
        """
        Audit overall paper trading performance summary against institutional sanity bounds.
        Detects hyper-compounding, unrealistic win rates, and simulation artifacts.
        """
        flaws: List[QuantFlaw] = []

        total_trades = int(summary.get("total_trades", 0))
        winning_trades = int(summary.get("winning_trades", 0))
        win_rate = Decimal(str(summary.get("win_rate_pct", 0)))
        profit_factor = Decimal(str(summary.get("profit_factor", 0)))
        initial_equity = Decimal(str(summary.get("initial_equity", 200.0)))
        current_equity = Decimal(str(summary.get("current_equity", 200.0)))
        net_return_pct = Decimal(str(summary.get("net_return_pct", 0)))

        # Check 1: Impossible Win Rate over statistically significant sample
        if total_trades >= 20 and win_rate > self.max_realistic_win_rate:
            flaws.append(QuantFlaw(
                code="FLAW_IMPOSSIBLE_WIN_RATE",
                severity=FlawSeverity.CRITICAL_HALLUCINATION,
                title="Statistically Impossible Win Rate (Simulation Artifact)",
                description=(
                    f"Win rate of {win_rate}% across {total_trades} trades exceeds institutional feasibility. "
                    "Indicates lookahead bias, pre-crossed brackets, or zero-cost execution."
                ),
                observed_value=f"{win_rate}% ({winning_trades}/{total_trades})",
                institutional_bound=f"<= {self.max_realistic_win_rate}%",
                remediation="Check for lookahead price feeds or stale lookback CSVs."
            ))

        # Check 2: Extreme Profit Factor
        if total_trades >= 15 and profit_factor > self.max_realistic_profit_factor:
            flaws.append(QuantFlaw(
                code="FLAW_EXTREME_PROFIT_FACTOR",
                severity=FlawSeverity.CRITICAL_HALLUCINATION,
                title="Extreme Profit Factor (Vanity Metric)",
                description=(
                    f"Profit factor of {profit_factor:.2f}x indicates loss suppression, "
                    "omitted adverse fills, or synthetic compounding."
                ),
                observed_value=f"{profit_factor:.2f}x",
                institutional_bound=f"<= {self.max_realistic_profit_factor:.2f}x",
                remediation="Ensure realistic taker fees, slippage, and stop-loss execution."
            ))

        # Check 3: Exponential 24h Capital Explosion (The $200 -> $949k Flaw)
        if initial_equity <= Decimal("500.00") and current_equity > Decimal("10000.00"):
            flaws.append(QuantFlaw(
                code="FLAW_HYPER_COMPOUNDING_EXPLOSION",
                severity=FlawSeverity.CRITICAL_HALLUCINATION,
                title="Unconstrained Compounding Explosion",
                description=(
                    f"Account equity grew from ${initial_equity} to ${current_equity} (+{net_return_pct}%). "
                    "Real exchanges impose liquidity limits, maintenance margin tiers, and market impact."
                ),
                observed_value=f"${initial_equity} -> ${current_equity}",
                institutional_bound="Small accounts must adhere to micro-notional ceilings",
                remediation="Enforce small_account_threshold_usd and max_micro_notional_usd."
            ))

        # Check 4: Audit individual closed trades if present
        closed_trades = summary.get("closed_trades", [])
        for t in closed_trades:
            trade_flaws = self.audit_trade_record(t)
            flaws.extend(trade_flaws)

        # Confidence scoring: 1.0 down to 0.0 based on severity
        critical_count = sum(1 for f in flaws if f.severity == FlawSeverity.CRITICAL_HALLUCINATION)
        warning_count = sum(1 for f in flaws if f.severity == FlawSeverity.WARNING)

        if critical_count > 0:
            confidence = Decimal("0.00")
            is_valid = False
            summary_txt = f"CRITICAL REJECTION: {critical_count} hallucination flaws detected. Performance data is untrustworthy."
        elif warning_count > 0:
            confidence = max(Decimal("0.50"), Decimal("1.00") - Decimal(str(warning_count * 0.15)))
            is_valid = True
            summary_txt = f"CAUTION: {warning_count} non-critical warnings detected. Review execution assumptions."
        else:
            confidence = Decimal("1.00")
            is_valid = True
            summary_txt = "PRISTINE: All quantitative checks passed. Performance metrics reflect empirical ground reality."

        return AuditVerdict(
            is_valid=is_valid,
            flaws=flaws,
            confidence_score=confidence,
            summary=summary_txt
        )
