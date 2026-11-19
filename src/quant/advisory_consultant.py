"""
src/quant/advisory_consultant.py — Specialized Advisory Consultant & Mathematical Audit Engine.

Inspired by TradingAgents (TauricResearch), upgraded to Kronos Institutional Invariants:
1. Zero Float Financial Math: All prices, fees, alpha, and conviction metrics use decimal.Decimal.
2. Tri-Perspective Adversarial Conviction Ratio (ACR):
       ACR = (C_bull * (1 - P_bear)) / (1 + R_drag)
   - C_bull in [0, 1]: Bull momentum & orderbook demand conviction.
   - P_bear in [0, 1]: Liquidation trap & mean-reversion shock risk.
   - R_drag in [0, 1]: Fee friction & slippage drag ratio.
3. Autonomous Trade Settlement & Reflection:
   - Computes realized alpha vs. benchmark (BTC): alpha = R_trade - R_BTC.
   - Deconstructs TCA realization tax drag and duration sweetspots.
   - Generates concise 2-sentence institutional lessons for data/lessons.db.
4. Asynchronous & Safe: Completely decoupled from real-time execution engines.
"""

import os
import json
import logging
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional, Dict, Any, List, Tuple
from dataclasses import dataclass, asdict
from datetime import datetime, timezone

from src.quant.config import ALL_SUPPORTED_SYMBOLS, FuturesSymbolConfig, DEFAULT_RISK_CONFIG
from src.quant.gemini_strategy_arbiter import GeminiStrategyArbiter

logger = logging.getLogger("Kronos.AdvisoryConsultant")
if not logger.handlers:
    h = logging.StreamHandler()
    h.setFormatter(logging.Formatter("[%(asctime)s UTC] [%(levelname)s] [AdvisoryConsultant] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
    logger.addHandler(h)
    logger.setLevel(logging.INFO)


@dataclass
class TriPerspectiveAudit:
    """Mathematical deconstruction of Bull, Bear, and Risk Council stances."""
    bull_conviction: Decimal      # C_bull in [0.00, 1.00]
    bear_trap_risk: Decimal       # P_bear in [0.00, 1.00]
    friction_drag_ratio: Decimal  # R_drag in [0.00, 1.00]
    acr_score: Decimal            # ACR in [0.00, 1.00]
    bull_thesis: str
    bear_antithesis: str
    risk_verdict: str             # "STRONG_CONVICTION", "BALANCED_MODERATE", "ADVERSARIAL_VETO"


@dataclass
class AdvisoryAssessment:
    """Full institutional multi-perspective assessment for an instrument."""
    symbol: str
    timestamp_utc: str
    current_price: Decimal
    direction_bias: str           # "LONG", "SHORT", "NEUTRAL"
    rating: str                   # "STRONG_BUY", "OVERWEIGHT", "HOLD", "UNDERWEIGHT", "AVOID"
    audit: TriPerspectiveAudit
    technical_indicators: Dict[str, Any]
    volume_profile_poc_aligned: bool
    recommended_action: str
    synthesized_memorandum: str

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        # Convert Decimals to float/string for JSON serialization
        d["current_price"] = float(self.current_price)
        d["audit"]["bull_conviction"] = float(self.audit.bull_conviction)
        d["audit"]["bear_trap_risk"] = float(self.audit.bear_trap_risk)
        d["audit"]["friction_drag_ratio"] = float(self.audit.friction_drag_ratio)
        d["audit"]["acr_score"] = float(self.audit.acr_score)
        return d


@dataclass
class SettlementReflection:
    """Post-trade audit and empirical lesson attribution."""
    position_id: str
    symbol: str
    side: str
    entry_price: Decimal
    exit_price: Decimal
    holding_seconds: int
    gross_return_pct: Decimal
    benchmark_btc_return_pct: Decimal
    alpha_return_pct: Decimal
    fee_drag_pct: Decimal
    net_return_pct: Decimal
    sweetspot_compliance: bool
    dominant_root_cause: str
    empirical_lesson: str


class AdvisoryConsultantEngine:
    """
    Sovereign Advisory Consultant & Mathematical Audit Engine.
    Operates as an asynchronous intelligence wing for Kronos.
    """

    def __init__(
        self,
        gemini_arbiter: Optional[GeminiStrategyArbiter] = None,
        min_acr_entry_threshold: Decimal = Decimal("0.65")
    ):
        self.gemini_arbiter = gemini_arbiter or GeminiStrategyArbiter()
        self.min_acr_threshold = min_acr_entry_threshold

    def compute_acr(
        self,
        bull_conviction: Decimal,
        bear_trap_risk: Decimal,
        friction_drag: Decimal
    ) -> Decimal:
        """
        Formulation 1: Tri-Perspective Adversarial Conviction Ratio (ACR).
        Formula: ACR = (C_bull * (1 - P_bear)) / (1 + R_drag)
        """
        # Clamp inputs
        c_bull = max(Decimal("0.00"), min(Decimal("1.00"), bull_conviction))
        p_bear = max(Decimal("0.00"), min(Decimal("1.00"), bear_trap_risk))
        r_drag = max(Decimal("0.00"), friction_drag)

        numerator = c_bull * (Decimal("1.00") - p_bear)
        denominator = Decimal("1.00") + r_drag
        acr = numerator / denominator
        return acr.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)

    def assess_instrument(
        self,
        symbol: str,
        current_price: Decimal,
        order_book_imbalance: Decimal,
        micro_skew_bps: Decimal,
        recent_klines: List[Dict[str, Decimal]],
        volume_profile_poc: Optional[Decimal] = None,
        funding_rate_bps: Optional[Decimal] = None
    ) -> AdvisoryAssessment:
        """
        Runs an end-to-end multi-perspective specialized consultation audit on a symbol.
        """
        now_str = datetime.now(timezone.utc).isoformat()
        cfg = ALL_SUPPORTED_SYMBOLS.get(symbol)
        taker_friction = cfg.round_trip_taker_friction() if cfg else Decimal("0.0010")

        # 1. Technical & Momentum Feature Extraction
        closes = [k["close"] for k in recent_klines] if recent_klines else [current_price]
        highs = [k.get("high", k["close"]) for k in recent_klines] if recent_klines else [current_price]
        lows = [k.get("low", k["close"]) for k in recent_klines] if recent_klines else [current_price]

        # Calculate short-term 5-period and 20-period price momentum
        p_current = closes[-1]
        p_5 = closes[-5] if len(closes) >= 5 else closes[0]
        p_20 = closes[-20] if len(closes) >= 20 else closes[0]

        mom_5_pct = ((p_current - p_5) / p_5) * Decimal("100") if p_5 > Decimal("0") else Decimal("0")
        mom_20_pct = ((p_current - p_20) / p_20) * Decimal("20") if p_20 > Decimal("0") else Decimal("0")

        # 2. Bull Thesis Formulation
        bullish_score = Decimal("0.50")
        bull_factors = []

        # Order Book Imbalance demand test
        if order_book_imbalance > Decimal("0.20"):
            bullish_score += Decimal("0.15")
            bull_factors.append(f"Strong bid-side book pressure (+{float(order_book_imbalance)*100:.1f}% OBI)")
        elif order_book_imbalance < Decimal("-0.20"):
            bullish_score -= Decimal("0.15")

        # Stoikov micro-skew confirmation
        if micro_skew_bps > Decimal("1.5"):
            bullish_score += Decimal("0.15")
            bull_factors.append(f"Positive micro-price skew (+{float(micro_skew_bps):.1f} bps)")
        elif micro_skew_bps < Decimal("-1.5"):
            bullish_score -= Decimal("0.15")

        # Momentum alignment
        if mom_5_pct > Decimal("0.20"):
            bullish_score += Decimal("0.10")
            bull_factors.append(f"Short-term expansion (+{float(mom_5_pct):.2f}%)")

        c_bull = max(Decimal("0.05"), min(Decimal("0.95"), bullish_score))

        # 3. Bear Skeptic & Liquidation Trap Formulation
        bear_score = Decimal("0.20")
        bear_factors = []

        # Crowded funding rate trap check
        fr = funding_rate_bps or Decimal("0.5")  # default neutral 0.5 bps
        if fr > Decimal("2.0"):  # Overheated long crowding
            bear_score += Decimal("0.25")
            bear_factors.append(f"Overcrowded long positioning (Funding: +{float(fr):.1f} bps)")
        elif fr < Decimal("-2.0"):  # Overcrowded short squeeze risk
            bear_score += Decimal("0.25")
            bear_factors.append(f"Severe negative funding rate ({float(fr):.1f} bps)")

        # Volume Profile POC Resistance Traps
        poc_aligned = True
        if volume_profile_poc is not None and volume_profile_poc > Decimal("0"):
            dist_to_poc_pct = ((current_price - volume_profile_poc) / volume_profile_poc) * Decimal("100")
            if Decimal("-0.40") <= dist_to_poc_pct <= Decimal("0.00"):
                # Firing right into POC resistance ceiling
                bear_score += Decimal("0.30")
                bear_factors.append(f"Firing directly into Volume Profile Point of Control resistance ceiling (${float(volume_profile_poc):.4f})")
                poc_aligned = False
            elif Decimal("0.00") < dist_to_poc_pct <= Decimal("0.40"):
                # Sitting on POC support floor
                bear_factors.append(f"Supported by Volume Profile POC floor (${float(volume_profile_poc):.4f})")

        p_bear = max(Decimal("0.05"), min(Decimal("0.95"), bear_score))

        # 4. Friction & Tax Drag Ratio
        # Taker fees relative to average expected return (0.80% standard target)
        expected_target_pct = Decimal("0.0080")
        drag_ratio = taker_friction / expected_target_pct

        # 5. Tri-Perspective ACR Computation
        acr = self.compute_acr(c_bull, p_bear, drag_ratio)

        # 6. Categorical Rating Synthesis
        if acr >= Decimal("0.70"):
            rating = "STRONG_BUY"
            direction = "LONG"
            verdict = "STRONG_CONVICTION"
            action = "Approved for standard primary slot allocation."
        elif acr >= Decimal("0.58"):
            rating = "OVERWEIGHT"
            direction = "LONG"
            verdict = "BALANCED_MODERATE"
            action = "Permitted for conservative half-sized canary execution."
        elif acr >= Decimal("0.42"):
            rating = "HOLD"
            direction = "NEUTRAL"
            verdict = "ADVERSARIAL_VETO"
            action = "Hold/Standby: Bull and Bear forces balanced; risk-reward sub-optimal."
        elif acr >= Decimal("0.28"):
            rating = "UNDERWEIGHT"
            direction = "SHORT"
            verdict = "ADVERSARIAL_VETO"
            action = "Caution: Bear pressure dominant; avoid long exposure."
        else:
            rating = "AVOID"
            direction = "SHORT"
            verdict = "ADVERSARIAL_VETO"
            action = "Strict Veto: Severe trap risk or heavy friction drag."

        bull_thesis_text = "; ".join(bull_factors) if bull_factors else "Modest baseline directional drift."
        bear_antithesis_text = "; ".join(bear_factors) if bear_factors else "Minimal structural liquidation trap detected."

        memo = (
            f"Tri-Perspective Audit for {symbol}: ACR Score = {acr} (Rating: {rating}). "
            f"Bull Conviction: {c_bull:.2f} ({bull_thesis_text}). "
            f"Bear Trap Probability: {p_bear:.2f} ({bear_antithesis_text}). "
            f"Friction Drag: {drag_ratio:.2f}. Recommended Action: {action}"
        )

        audit = TriPerspectiveAudit(
            bull_conviction=c_bull,
            bear_trap_risk=p_bear,
            friction_drag_ratio=drag_ratio,
            acr_score=acr,
            bull_thesis=bull_thesis_text,
            bear_antithesis=bear_antithesis_text,
            risk_verdict=verdict
        )

        return AdvisoryAssessment(
            symbol=symbol,
            timestamp_utc=now_str,
            current_price=current_price,
            direction_bias=direction,
            rating=rating,
            audit=audit,
            technical_indicators={
                "momentum_5m_pct": float(mom_5_pct),
                "momentum_20m_pct": float(mom_20_pct),
                "order_book_imbalance": float(order_book_imbalance),
                "micro_skew_bps": float(micro_skew_bps),
                "friction_bps": float(taker_friction * Decimal("10000"))
            },
            volume_profile_poc_aligned=poc_aligned,
            recommended_action=action,
            synthesized_memorandum=memo
        )

    def settle_and_reflect(
        self,
        position_id: str,
        symbol: str,
        side: str,
        entry_price: Decimal,
        exit_price: Decimal,
        holding_seconds: int,
        btc_entry_price: Decimal,
        btc_exit_price: Decimal,
        is_scalp: bool = True
    ) -> SettlementReflection:
        """
        Formulation 2: Post-Trade Forensic Settlement & Alpha Attribution.
        Computes realized alpha vs. BTC, sweetspot compliance, and institutional lesson.
        """
        cfg = ALL_SUPPORTED_SYMBOLS.get(symbol)
        fee_pct = (cfg.round_trip_taker_friction() * Decimal("100")) if cfg else Decimal("0.10")

        # 1. Realized Gross Return
        if side.upper() in ("BUY", "LONG"):
            gross_ret = ((exit_price - entry_price) / entry_price) * Decimal("100")
        else:
            gross_ret = ((entry_price - exit_price) / entry_price) * Decimal("100")

        # 2. Benchmark BTC Return over the identical holding window
        btc_ret = Decimal("0.00")
        if btc_entry_price > Decimal("0"):
            btc_ret = ((btc_exit_price - btc_entry_price) / btc_entry_price) * Decimal("100")

        # 3. Alpha vs. Benchmark
        alpha = gross_ret - btc_ret

        # 4. Net Return
        net_ret = gross_ret - fee_pct

        # 5. Sweetspot Duration Compliance Check
        # Scalps: 600s - 900s (10-15m) sweetspot, max 8m if stagnant
        # Macro: 90m - 240m (1.5h - 4h) sweetspot
        if is_scalp:
            sweetspot_ok = 30 <= holding_seconds <= 900
            max_sweetspot_str = "15m"
        else:
            sweetspot_ok = 1800 <= holding_seconds <= 14400
            max_sweetspot_str = "4h"

        # 6. Diagnosis and Concrete 2-Sentence Lesson Formulation
        if net_ret > Decimal("0"):
            root_cause = "THESIS_CONFIRMED_PROFIT"
            lesson = (
                f"{symbol} achieved net +{net_ret:.2f}% (Alpha: {alpha:+.2f}% vs BTC) within {holding_seconds}s sweetspot. "
                f"Directional thesis held cleanly; maintain current momentum and OBI entry thresholds."
            )
        elif gross_ret > Decimal("0") and net_ret <= Decimal("0"):
            root_cause = "FRICTION_TAX_BLEED"
            lesson = (
                f"{symbol} printed gross +{gross_ret:.2f}% but was inverted to net {net_ret:.2f}% by {fee_pct:.2f}% taker friction. "
                f"Increase minimum net fee hurdle from {fee_pct:.2f}% to prevent trading into tight dead bands."
            )
        elif not sweetspot_ok and holding_seconds > 900:
            root_cause = "STAGNATION_TIMEOUT_OVERSTAY"
            lesson = (
                f"{symbol} remained in trade for {holding_seconds // 60}m, exceeding the {max_sweetspot_str} sweetspot ceiling. "
                f"Enforce strict 8-minute stagnation ejection when MFE fails to expand past +0.25%."
            )
        else:
            root_cause = "ADVERSE_STOP_OUT"
            lesson = (
                f"{symbol} stopped out at {net_ret:.2f}% (Alpha: {alpha:+.2f}% vs BTC) after {holding_seconds}s. "
                f"Respect the 15-minute post-exit quarantine window to avoid immediate whipsaw re-entry."
            )

        return SettlementReflection(
            position_id=position_id,
            symbol=symbol,
            side=side,
            entry_price=entry_price,
            exit_price=exit_price,
            holding_seconds=holding_seconds,
            gross_return_pct=gross_ret.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
            benchmark_btc_return_pct=btc_ret.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
            alpha_return_pct=alpha.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
            fee_drag_pct=fee_pct.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
            net_return_pct=net_ret.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
            sweetspot_compliance=sweetspot_ok,
            dominant_root_cause=root_cause,
            empirical_lesson=lesson
        )
