"""
src/quant/kev_risk_arbiter.py — KEV.ai Supreme Risk Arbiter & Adversarial Gate.

Holds 100% Supreme Veto Power. No trade enters the exchange without satisfying:
1. News Blackout Gate: No imminent macroeconomic or exchange shocks.
2. Macro Confluence Gate: Direction aligns with Top-10 composite breadth (>60% for Longs).
3. Net Fee Hurdle Gate: Expected drift after friction >= 0.50% (Lesson #10).
4. Crypto Carry Gate: 8h perpetual funding rate is not prohibitive.
5. Correlation Shield: Pairwise correlation with existing active positions rho < 0.85.
6. Risk-to-Reward Gate: Reward / Risk ratio >= 1.50:1.

Also embeds the Adversarial Bull vs. Bear Devil's Advocate Stress-Test,
and sizes positions via strict Decimal Fractional Kelly / Risk Budgeting.
Strictly adheres to AGENTS.md Invariant 1 (Zero Float Financial Math).
"""

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP, ROUND_DOWN
from typing import Dict, List, Optional, Set

from src.quant.config import (
    DEFAULT_RISK_CONFIG,
    ALL_SUPPORTED_SYMBOLS,
    FuturesSymbolConfig,
    GlobalRiskConfig,
)
from src.quant.macro_specialists import NewsBlackoutVerdict, CarryVerdict
from src.quant.crypto_index_engine import MacroIndexVerdict
from src.quant.kronos_onnx_engine import TrajectoryVerdict


@dataclass(frozen=True)
class TradeTicket:
    """Pre-cleared, execution-ready trade bracket specification in Decimal."""
    symbol: str
    side: str                     # "BUY" (for Long) or "SELL" (for Short)
    entry_price: Decimal
    stop_loss: Decimal
    take_profit: Decimal
    quantity: Decimal
    notional_usd: Decimal
    effective_leverage: int
    risk_budget_usd: Decimal
    reward_risk_ratio: Decimal
    net_expected_gain_pct: Decimal


@dataclass(frozen=True)
class KEVDecision:
    """Supreme risk evaluation verdict."""
    approved: bool
    symbol: str
    side: str
    veto_gate_failed: Optional[str]
    veto_reason: str
    ticket: Optional[TradeTicket]
    adversarial_notes: str


class KEVSupremeArbiter:
    """
    Supreme Risk Officer & Chief Risk Arbiter.
    Implements the 6-Point Veto Gate and adversarial devil's advocate stress-testing.
    """

    def __init__(
        self,
        risk_config: Optional[GlobalRiskConfig] = None,
        symbols_config: Optional[Dict[str, FuturesSymbolConfig]] = None
    ):
        self.risk_config = risk_config or DEFAULT_RISK_CONFIG
        self.symbols_config = symbols_config or ALL_SUPPORTED_SYMBOLS

    def evaluate_candidate(
        self,
        trajectory: TrajectoryVerdict,
        news_verdict: NewsBlackoutVerdict,
        macro_index: MacroIndexVerdict,
        carry_verdict: CarryVerdict,
        account_equity: Decimal,
        active_positions: Optional[List[str]] = None,
        correlation_matrix: Optional[Dict[str, Dict[str, Decimal]]] = None,
        confidence_multiplier: Decimal = Decimal("1.0"),
        is_maker_sniper: bool = False
    ) -> KEVDecision:
        """
        Evaluate candidate trade against all 6 Supreme Veto Gates.
        All pricing, friction, and sizing operations are strictly Decimal.
        """
        symbol = trajectory.symbol
        side = trajectory.proposed_side
        cfg = self.symbols_config.get(symbol)
        if not cfg:
            return KEVDecision(
                approved=False,
                symbol=symbol,
                side=side,
                veto_gate_failed="GATE_CONFIG",
                veto_reason=f"Unregistered symbol configuration: {symbol}",
                ticket=None,
                adversarial_notes="Configuration failure."
            )

        if side not in ["LONG", "SHORT"]:
            return KEVDecision(
                approved=False,
                symbol=symbol,
                side=side,
                veto_gate_failed="GATE_DIRECTION",
                veto_reason="Neutral or undefined directional trajectory.",
                ticket=None,
                adversarial_notes="Model forecast is neutral."
            )

        # ----------------------------------------------------------------------
        # Gate 1: News & Macro Blackout Shield
        # ----------------------------------------------------------------------
        if news_verdict.is_blackout:
            return KEVDecision(
                approved=False,
                symbol=symbol,
                side=side,
                veto_gate_failed="GATE_1_NEWS_BLACKOUT",
                veto_reason=f"VETO: Macro blackout active: {news_verdict.reason}",
                ticket=None,
                adversarial_notes="Macro event release risk too high."
            )

        # ----------------------------------------------------------------------
        # Gate 2: Macro Confluence Gate (Top-10 Composite Breadth)
        # ----------------------------------------------------------------------
        if side == "LONG" and macro_index.macro_regime == "BEAR_DISTRIBUTION":
            return KEVDecision(
                approved=False,
                symbol=symbol,
                side=side,
                veto_gate_failed="GATE_2_MACRO_CONFLUENCE",
                veto_reason=f"VETO: Cannot Long during systemic Bear Distribution ({macro_index.breadth_ratio*Decimal('100'):.1f}% breadth).",
                ticket=None,
                adversarial_notes="Attempting counter-trend long against systemic market dump."
            )
        elif side == "SHORT" and macro_index.macro_regime == "BULL_EXPANSION":
            return KEVDecision(
                approved=False,
                symbol=symbol,
                side=side,
                veto_gate_failed="GATE_2_MACRO_CONFLUENCE",
                veto_reason=f"VETO: Cannot Short during systemic Bull Expansion ({macro_index.breadth_ratio*Decimal('100'):.1f}% breadth).",
                ticket=None,
                adversarial_notes="Attempting counter-trend short against systemic market pump."
            )

        # ----------------------------------------------------------------------
        # Gate 3: Net Fee Hurdle Gate (Lesson #10)
        # ----------------------------------------------------------------------
        friction = cfg.round_trip_maker_friction() if is_maker_sniper else cfg.round_trip_taker_friction()
        net_drift = abs(trajectory.raw_drift) - friction
        min_hurdle = self.risk_config.min_net_fee_hurdle

        if net_drift < min_hurdle:
            return KEVDecision(
                approved=False,
                symbol=symbol,
                side=side,
                veto_gate_failed="GATE_3_FEE_HURDLE",
                veto_reason=(
                    f"VETO: Net expected drift {net_drift*Decimal('100'):.2f}% below hurdle {min_hurdle*Decimal('100'):.2f}% "
                    f"(Raw: {trajectory.raw_drift*Decimal('100'):.2f}%, Friction: {friction*Decimal('100'):.2f}%)."
                ),
                ticket=None,
                adversarial_notes="Alpha swallowed by exchange taker friction and slippage."
            )

        # ----------------------------------------------------------------------
        # Gate 4: Crypto Carry & Funding Rate Guard
        # ----------------------------------------------------------------------
        if carry_verdict.verdict == "PROHIBITIVE":
            return KEVDecision(
                approved=False,
                symbol=symbol,
                side=side,
                veto_gate_failed="GATE_4_CARRY_GUARD",
                veto_reason=f"VETO: Prohibitive 8h funding rate carry drag: {carry_verdict.reason}",
                ticket=None,
                adversarial_notes="Perpetual funding will bleed trade profitability over 12 hours."
            )

        # ----------------------------------------------------------------------
        # Gate 5: Correlation Shield (Portfolio Diversification)
        # ----------------------------------------------------------------------
        active_positions = active_positions or []
        if len(active_positions) >= self.risk_config.max_concurrent_positions:
            return KEVDecision(
                approved=False,
                symbol=symbol,
                side=side,
                veto_gate_failed="GATE_5_PORTFOLIO_CAPACITY",
                veto_reason=f"VETO: Max concurrent positions ({self.risk_config.max_concurrent_positions}) reached.",
                ticket=None,
                adversarial_notes="Portfolio risk capacity full."
            )

        if correlation_matrix and active_positions:
            sym_corrs = correlation_matrix.get(symbol, {})
            for active_sym in active_positions:
                rho = sym_corrs.get(active_sym, Decimal("0.0"))
                if rho >= self.risk_config.max_pair_correlation:
                    return KEVDecision(
                        approved=False,
                        symbol=symbol,
                        side=side,
                        veto_gate_failed="GATE_5_CORRELATION_SHIELD",
                        veto_reason=f"VETO: Pairwise correlation rho={rho:.2f} with active position {active_sym} >= {self.risk_config.max_pair_correlation}.",
                        ticket=None,
                        adversarial_notes=f"Over-concentrating beta in correlated asset {active_sym}."
                    )

        # ----------------------------------------------------------------------
        # Gate 6: Risk-to-Reward Ratio Gate
        # ----------------------------------------------------------------------
        entry = trajectory.current_price
        tp = trajectory.dynamic_take_profit
        sl = trajectory.dynamic_stop_loss

        risk_distance = abs(entry - sl)
        reward_distance = abs(tp - entry)

        if risk_distance <= Decimal("0"):
            return KEVDecision(
                approved=False,
                symbol=symbol,
                side=side,
                veto_gate_failed="GATE_6_INVALID_STOPS",
                veto_reason="VETO: Stop distance is zero.",
                ticket=None,
                adversarial_notes="Stop-loss must not equal entry."
            )

        rr_ratio = reward_distance / risk_distance
        if rr_ratio < self.risk_config.min_rr_ratio:
            return KEVDecision(
                approved=False,
                symbol=symbol,
                side=side,
                veto_gate_failed="GATE_6_RISK_REWARD",
                veto_reason=f"VETO: Risk/Reward ratio {rr_ratio:.2f}:1 is below institutional minimum {self.risk_config.min_rr_ratio:.2f}:1.",
                ticket=None,
                adversarial_notes="Negative expectancy: potential reward does not compensate downside stop risk."
            )

        # ----------------------------------------------------------------------
        # Adversarial Bull vs. Bear Devil's Advocate Stress-Test
        # ----------------------------------------------------------------------
        adversarial_notes = []
        if side == "LONG":
            if carry_verdict.funding_rate > Decimal("0.00015"):
                adversarial_notes.append("Adversarial Warning: Mild positive funding rate. Must exit promptly if trajectory stalls.")
        elif side == "SHORT":
            if carry_verdict.funding_rate < Decimal("-0.00015"):
                adversarial_notes.append("Adversarial Warning: Mild negative funding rate. Shorts will pay fee at next 8h mark.")

        # ----------------------------------------------------------------------
        # Position Sizing via Fractional Kelly / Risk Budgeting in Decimal
        # ----------------------------------------------------------------------
        base_budget_ratio = self.risk_config.base_risk_budget_ratio
        effective_budget_ratio = base_budget_ratio * confidence_multiplier
        risk_budget_usd = (account_equity * effective_budget_ratio).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        raw_qty = risk_budget_usd / risk_distance
        quantized_qty = cfg.quantize_quantity(raw_qty)

        if quantized_qty < cfg.min_quantity:
            return KEVDecision(
                approved=False,
                symbol=symbol,
                side=side,
                veto_gate_failed="GATE_SIZING_MIN_QTY",
                veto_reason=f"VETO: Sized quantity {quantized_qty} below contract minimum {cfg.min_quantity}.",
                ticket=None,
                adversarial_notes="Account equity or risk budget too small for contract minimum step size."
            )

        notional_usd = (quantized_qty * entry).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if notional_usd < cfg.min_notional:
            return KEVDecision(
                approved=False,
                symbol=symbol,
                side=side,
                veto_gate_failed="GATE_SIZING_MIN_NOTIONAL",
                veto_reason=f"VETO: Notional value ${notional_usd} below Binance minimum ${cfg.min_notional}.",
                ticket=None,
                adversarial_notes="Trade value does not meet exchange notional threshold."
            )

        raw_leverage = int((notional_usd / account_equity).quantize(Decimal("1"), rounding=ROUND_DOWN)) + 1
        effective_leverage = min(self.risk_config.max_account_leverage, max(1, raw_leverage))

        ticket = TradeTicket(
            symbol=symbol,
            side="BUY" if side == "LONG" else "SELL",
            entry_price=entry,
            stop_loss=sl,
            take_profit=tp,
            quantity=quantized_qty,
            notional_usd=notional_usd,
            effective_leverage=effective_leverage,
            risk_budget_usd=risk_budget_usd,
            reward_risk_ratio=rr_ratio.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
            net_expected_gain_pct=(net_drift * Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
        )

        return KEVDecision(
            approved=True,
            symbol=symbol,
            side=side,
            veto_gate_failed=None,
            veto_reason="ALL 6 SUPREME VETO GATES PASSED. Trade approved.",
            ticket=ticket,
            adversarial_notes="; ".join(adversarial_notes) if adversarial_notes else "Adversarial stress-test clear."
        )
