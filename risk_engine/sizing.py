"""
risk_engine/sizing.py — Quantitative Position Sizing & Tail-Risk Governance (v3).

Implements:
1. Single-Pass Net-of-Fee Fractional Kelly (0.25 * f*) without double-counting friction.
2. Inverse Realized Volatility Targeting (max of rolling vol & ATR%).
3. Non-Gaussian Empirical Expected Shortfall (CVaR).
4. Aggregate Portfolio Open Stop-Risk Cap (2.5% normal / 1.25% Tier-1) & Single-Trade Stop-Risk Cap.
5. Correlated Net Directional Leverage Cap (1.0x on small accounts) & Gross Leverage Cap.
6. Honest Discrete Min-Lot Preservation (allows 0.001 BTC on small accounts ONLY if dollar
   stop-risk, CVaR, leverage, and book depth invariants all pass; never hides risk).

Strictly adheres to Zero Float Financial Math (decimal.Decimal throughout).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_CEILING, ROUND_DOWN, ROUND_HALF_UP
from typing import List, Optional, Tuple

from risk_engine.config import RiskConfig
from risk_engine.models import (
    MarketSnapshot,
    OrderSide,
    PortfolioState,
    ProposedOrder,
    RiskMode,
)


@dataclass(frozen=True)
class SizingResult:
    """Detailed output of quantitative sizing and cap governance."""
    approved_qty: Decimal
    was_resized: bool
    vetoed: bool
    reason_codes: List[str]
    raw_kelly: Decimal
    fractional_kelly: Decimal
    vol_scalar: Decimal
    empirical_cvar_pct: Decimal
    portfolio_cvar_pct: Decimal
    max_notional_usd: Decimal
    book_impact_pct: Decimal
    trade_stop_risk_usd: Decimal
    portfolio_open_stop_risk_usd: Decimal


def compute_fractional_kelly(
    win_rate: Decimal,
    payoff_ratio: Decimal,
    config: RiskConfig,
    is_gross_estimate: bool = True,
) -> Tuple[Decimal, Decimal]:
    """
    Calculate raw Kelly f* and bounded Fractional Kelly.
    Applies decay buffers strictly once (only on gross estimates when
    `kelly_apply_decay_only_to_gross` is True) to avoid double-penalizing realized net edge.
    """
    apply_decay = is_gross_estimate or (not config.kelly_apply_decay_only_to_gross)
    if apply_decay:
        p_eff = max(Decimal("0"), min(Decimal("1"), win_rate - config.win_rate_decay_buffer))
        b_eff = max(Decimal("0.01"), payoff_ratio * (Decimal("1") - config.payoff_decay_buffer))
    else:
        p_eff = max(Decimal("0"), min(Decimal("1"), win_rate))
        b_eff = max(Decimal("0.01"), payoff_ratio)

    raw_kelly = p_eff - ((Decimal("1") - p_eff) / b_eff)

    if raw_kelly <= Decimal("0"):
        return raw_kelly, Decimal("0")

    frac = raw_kelly * config.kelly_fraction
    capped = min(config.max_kelly_allocation_pct, frac)
    return raw_kelly, capped


def compute_volatility_scalar(
    realized_vol: Decimal,
    atr_pct: Optional[Decimal],
    config: RiskConfig,
) -> Decimal:
    """Inverse realized-volatility sizing scalar bounded by [min_vol_scalar, max_vol_scalar]."""
    eff_vol = realized_vol
    if atr_pct is not None and atr_pct > eff_vol:
        eff_vol = atr_pct
    eff_vol = max(eff_vol, config.volatility_floor)
    raw_scalar = config.target_volatility / eff_vol
    return max(config.min_vol_scalar, min(config.max_vol_scalar, raw_scalar))


def compute_empirical_cvar(
    returns_series: List[Decimal],
    confidence_level: Decimal,
    fallback_vol: Decimal,
    fat_tail_multiplier: Decimal,
    min_samples: int,
) -> Decimal:
    """Non-Gaussian Empirical Expected Shortfall (CVaR) expressed as positive loss fraction."""
    empirical = Decimal("0")
    if returns_series:
        sorted_rets = sorted(returns_series)
        tail_prob = Decimal("1") - confidence_level
        n = Decimal(len(sorted_rets))
        k_dec = (tail_prob * n).to_integral_value(rounding=ROUND_CEILING)
        k = max(1, min(len(sorted_rets), int(k_dec)))
        tail_slice = sorted_rets[:k]
        tail_mean = sum(tail_slice, Decimal("0")) / Decimal(k)
        empirical = max(Decimal("0"), -tail_mean)

    if len(returns_series) >= min_samples and empirical > Decimal("0"):
        return empirical

    conservative_fallback = max(Decimal("0.005"), fallback_vol * Decimal("2.326") * fat_tail_multiplier)
    return max(empirical, conservative_fallback)


def compute_target_quantity(
    proposed_order: ProposedOrder,
    portfolio_state: PortfolioState,
    market_snapshot: MarketSnapshot,
    config: RiskConfig,
    risk_mode: RiskMode,
) -> SizingResult:
    """
    Compute the maximum risk-cleared quantity <= proposed_order.quantity across
    all quantitative sizing, stop-risk, CVaR, leverage, and liquidity caps.
    """
    reason_codes: List[str] = []
    equity = portfolio_state.equity_usd
    ref_price = proposed_order.price if proposed_order.price > Decimal("0") else market_snapshot.mark_price
    proposed_qty = proposed_order.quantity
    proposed_notional = proposed_qty * ref_price
    existing_open_stop_risk = portfolio_state.total_open_stop_risk_usd()

    # 1. Single-Pass Net-of-Fee Fractional Kelly
    win_rate = proposed_order.win_rate if proposed_order.win_rate is not None else config.default_win_rate
    payoff_ratio = (
        proposed_order.payoff_ratio
        if proposed_order.payoff_ratio is not None
        else config.default_payoff_ratio
    )
    # If caller omitted empirical stats, defaults are gross priors; otherwise honor order flag
    is_gross = True if (proposed_order.win_rate is None or proposed_order.payoff_ratio is None) else proposed_order.is_gross_edge_estimate
    raw_kelly, frac_kelly = compute_fractional_kelly(win_rate, payoff_ratio, config, is_gross_estimate=is_gross)

    # 2. Inverse Realized Volatility Scalar
    vol_scalar = compute_volatility_scalar(
        market_snapshot.realized_vol, market_snapshot.atr_pct, config
    )

    # 3. Empirical Tail-Risk (CVaR) — Asset & Portfolio
    asset_cvar_pct = compute_empirical_cvar(
        returns_series=market_snapshot.asset_returns_series,
        confidence_level=config.cvar_confidence_level,
        fallback_vol=max(market_snapshot.realized_vol, market_snapshot.atr_pct or Decimal("0")),
        fat_tail_multiplier=config.cvar_fat_tail_multiplier,
        min_samples=config.cvar_min_samples,
    )
    portfolio_cvar_pct = (
        compute_empirical_cvar(
            returns_series=portfolio_state.realized_returns_series,
            confidence_level=config.cvar_confidence_level,
            fallback_vol=market_snapshot.realized_vol,
            fat_tail_multiplier=config.cvar_fat_tail_multiplier,
            min_samples=config.cvar_min_samples,
        )
        if portfolio_state.realized_returns_series
        else Decimal("0")
    )

    side_depth = market_snapshot.order_book.execution_side_depth_usd(proposed_order.side)
    book_impact_pct = (proposed_notional / side_depth) if side_depth > Decimal("0") else Decimal("999")

    def _veto(codes: List[str]) -> SizingResult:
        return SizingResult(
            approved_qty=Decimal("0"),
            was_resized=False,
            vetoed=True,
            reason_codes=codes,
            raw_kelly=raw_kelly,
            fractional_kelly=frac_kelly,
            vol_scalar=vol_scalar,
            empirical_cvar_pct=asset_cvar_pct,
            portfolio_cvar_pct=portfolio_cvar_pct,
            max_notional_usd=Decimal("0"),
            book_impact_pct=book_impact_pct,
            trade_stop_risk_usd=Decimal("0"),
            portfolio_open_stop_risk_usd=existing_open_stop_risk,
        )

    # Handle reduce-only orders: shrink risk, capped strictly at opposing position quantity
    if proposed_order.reduce_only:
        existing = portfolio_state.positions.get(proposed_order.symbol)
        if existing is None or existing.quantity <= Decimal("0") or existing.side == proposed_order.side:
            return _veto(["REDUCE_ONLY_NO_OPPOSING_POSITION"])
        capped_qty = min(proposed_qty, existing.quantity)
        if capped_qty < proposed_qty:
            reason_codes.append("RESIZED_REDUCE_ONLY_TO_POSITION_QTY")
        quantized = market_snapshot.quantize_qty_down(capped_qty)
        if quantized <= Decimal("0"):
            return _veto(reason_codes + ["BELOW_MIN_STEP_SIZE"])
        return SizingResult(
            approved_qty=quantized,
            was_resized=(quantized < proposed_qty),
            vetoed=False,
            reason_codes=reason_codes,
            raw_kelly=raw_kelly,
            fractional_kelly=frac_kelly,
            vol_scalar=vol_scalar,
            empirical_cvar_pct=asset_cvar_pct,
            portfolio_cvar_pct=portfolio_cvar_pct,
            max_notional_usd=quantized * ref_price,
            book_impact_pct=book_impact_pct,
            trade_stop_risk_usd=Decimal("0"),
            portfolio_open_stop_risk_usd=existing_open_stop_risk,
        )

    if frac_kelly <= Decimal("0"):
        return _veto(["KELLY_NEGATIVE_EXPECTANCY_AFTER_DECAY"])

    cap_notional = proposed_notional
    stop_dist_pct = proposed_order.stop_distance_pct
    is_small_account = equity <= config.small_account_threshold_usd

    # Cap A: Fractional Kelly + Volatility Target Cap
    kelly_capital_budget = equity * frac_kelly * vol_scalar
    if stop_dist_pct is not None and stop_dist_pct > Decimal("0"):
        kelly_notional_cap = kelly_capital_budget / stop_dist_pct
    else:
        kelly_notional_cap = kelly_capital_budget

    if risk_mode == RiskMode.THROTTLED_TIER1:
        tier1_notional_cap = min(proposed_notional, kelly_notional_cap) * config.tier1_size_multiplier
        if tier1_notional_cap < cap_notional:
            cap_notional = tier1_notional_cap
            reason_codes.append("TIER1_DRAWDOWN_SIZE_CUT_50PCT")
    elif kelly_notional_cap < cap_notional:
        cap_notional = kelly_notional_cap
        reason_codes.append("RESIZED_FRACTIONAL_KELLY_VOL_TARGET")

    # Cap B: Aggregate Portfolio Open Stop-Risk & Single-Trade Stop-Risk Caps (v3)
    max_port_stop_risk_pct = (
        config.tier1_max_portfolio_open_stop_risk_pct
        if risk_mode == RiskMode.THROTTLED_TIER1
        else config.max_portfolio_open_stop_risk_pct
    )
    max_port_stop_risk_usd = equity * max_port_stop_risk_pct
    remaining_port_stop_risk_usd = max(Decimal("0"), max_port_stop_risk_usd - existing_open_stop_risk)

    max_single_stop_risk_usd = equity * config.max_single_trade_stop_risk_pct
    if risk_mode == RiskMode.THROTTLED_TIER1:
        max_single_stop_risk_usd *= config.tier1_size_multiplier

    allowed_trade_stop_risk_usd = min(remaining_port_stop_risk_usd, max_single_stop_risk_usd)
    if stop_dist_pct is not None and stop_dist_pct > Decimal("0"):
        if allowed_trade_stop_risk_usd <= Decimal("0"):
            return _veto(["PORTFOLIO_OPEN_STOP_RISK_EXCEEDED"])
        stop_risk_notional_cap = allowed_trade_stop_risk_usd / stop_dist_pct
        if stop_risk_notional_cap < cap_notional:
            cap_notional = stop_risk_notional_cap
            reason_codes.append("RESIZED_PORTFOLIO_STOP_RISK_CAP")

    # Cap C: Empirical CVaR Tail-Risk Budget Cap
    if portfolio_cvar_pct >= config.max_portfolio_cvar_pct:
        return _veto(["PORTFOLIO_CVAR_LIMIT_BREACHED"])

    remaining_cvar_budget_usd = equity * (config.max_portfolio_cvar_pct - portfolio_cvar_pct)
    cvar_notional_cap = (
        (remaining_cvar_budget_usd / asset_cvar_pct) if asset_cvar_pct > Decimal("0") else cap_notional
    )
    if risk_mode == RiskMode.THROTTLED_TIER1:
        cvar_notional_cap *= config.tier1_size_multiplier
    if cvar_notional_cap < cap_notional:
        cap_notional = cvar_notional_cap
        reason_codes.append("RESIZED_CVAR_TAIL_RISK_CAP")

    # Cap D: Single-Asset Exposure Cap (for small accounts, governed primarily by stop-risk + fat-finger + net cap)
    max_asset_usd = equity * config.max_single_asset_exposure_pct
    if risk_mode == RiskMode.THROTTLED_TIER1:
        max_asset_usd *= config.tier1_size_multiplier
    current_sym_exp = portfolio_state.symbol_exposure_usd(proposed_order.symbol)
    remaining_asset_usd = max(Decimal("0"), max_asset_usd - current_sym_exp)

    if not (is_small_account and config.preserve_indivisible_min_lot):
        if remaining_asset_usd <= Decimal("0"):
            return _veto(["MAX_SINGLE_ASSET_EXPOSURE_EXCEEDED"])
        if remaining_asset_usd < cap_notional:
            cap_notional = remaining_asset_usd
            reason_codes.append("RESIZED_SINGLE_ASSET_EXPOSURE_CAP")
    elif current_sym_exp <= Decimal("0") and remaining_asset_usd < cap_notional:
        # On small accounts, only enforce 25% notional cap if it still clears min_qty * ref_price
        min_lot_notional = market_snapshot.min_qty * ref_price
        if remaining_asset_usd >= max(min_lot_notional, market_snapshot.min_notional_usd):
            cap_notional = remaining_asset_usd
            reason_codes.append("RESIZED_SINGLE_ASSET_EXPOSURE_CAP")

    # Cap E: Gross Portfolio Leverage Cap
    max_gross_usd = equity * config.max_gross_leverage
    remaining_gross_usd = max(Decimal("0"), max_gross_usd - portfolio_state.gross_exposure_usd())
    if remaining_gross_usd <= Decimal("0"):
        return _veto(["MAX_GROSS_LEVERAGE_EXCEEDED"])
    if remaining_gross_usd < cap_notional:
        cap_notional = remaining_gross_usd
        reason_codes.append("RESIZED_GROSS_LEVERAGE_CAP")

    # Cap F: Correlated Net Portfolio Directional Leverage Cap (1.0x on small accounts!)
    eff_max_net_lev = config.effective_max_net_leverage(equity)
    max_net_usd = equity * eff_max_net_lev
    current_net = portfolio_state.net_exposure_usd()
    order_sign = Decimal("1") if proposed_order.side == OrderSide.BUY else Decimal("-1")
    projected_net = abs(current_net + order_sign * cap_notional)
    remaining_net_usd = (
        max(Decimal("0"), max_net_usd - current_net)
        if order_sign > Decimal("0")
        else max(Decimal("0"), max_net_usd + current_net)
    )
    if projected_net > max_net_usd:
        if remaining_net_usd <= Decimal("0"):
            return _veto(["MAX_NET_LEVERAGE_EXCEEDED"])
        if remaining_net_usd < cap_notional:
            cap_notional = remaining_net_usd
            reason_codes.append("RESIZED_NET_LEVERAGE_CAP")

    # Cap G: Visible Order-Book Depth Impact Cap
    if side_depth <= Decimal("0"):
        return _veto(["ORDER_BOOK_DEPTH_ZERO"])
    max_depth_notional = side_depth * config.max_order_book_depth_pct
    if max_depth_notional < cap_notional:
        cap_notional = max_depth_notional
        reason_codes.append("RESIZED_ORDER_BOOK_DEPTH_CAP")

    # Cap H: Available Free Margin Guard
    max_margin_notional = (
        max(Decimal("0"), portfolio_state.free_margin_usd) * config.max_gross_leverage
        if portfolio_state.free_margin_usd is not None
        else cap_notional
    )
    if max_margin_notional < cap_notional:
        cap_notional = max_margin_notional
        reason_codes.append("RESIZED_FREE_MARGIN_CAP")

    # Convert capped notional back to strictly downward-quantized contract quantity
    raw_qty = cap_notional / ref_price if ref_price > Decimal("0") else Decimal("0")
    approved_qty = market_snapshot.quantize_qty_down(min(proposed_qty, raw_qty))
    final_notional = (approved_qty * ref_price).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    # Honest Discrete Min-Lot Preservation (e.g. 0.001 BTC on $200 account):
    # Permitted ONLY if proposed_qty >= min_qty AND every hard survival invariant
    # (stop-risk, CVaR, gross/net leverage, book depth, free margin) holds at min_qty!
    if (
        (approved_qty < market_snapshot.min_qty or final_notional < market_snapshot.min_notional_usd)
        and is_small_account
        and config.preserve_indivisible_min_lot
        and proposed_qty >= market_snapshot.min_qty
    ):
        min_lot_qty = market_snapshot.min_qty
        min_lot_notional = (min_lot_qty * ref_price).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        min_lot_stop_risk = (
            min_lot_notional * stop_dist_pct if (stop_dist_pct is not None and stop_dist_pct > Decimal("0")) else Decimal("0")
        )
        min_lot_projected_net = abs(current_net + order_sign * min_lot_notional)
        hard_safe = (
            min_lot_notional >= market_snapshot.min_notional_usd
            and min_lot_notional <= remaining_gross_usd
            and min_lot_projected_net <= max_net_usd
            and min_lot_notional <= max_depth_notional
            and min_lot_notional <= max_margin_notional
            and min_lot_notional <= cvar_notional_cap
            and (stop_dist_pct is None or min_lot_stop_risk <= allowed_trade_stop_risk_usd)
        )
        if hard_safe:
            approved_qty = min_lot_qty
            final_notional = min_lot_notional
            reason_codes.append("PRESERVED_INDIVISIBLE_MIN_LOT_STOP_RISK_SAFE")

    if approved_qty < market_snapshot.min_qty or final_notional < market_snapshot.min_notional_usd:
        return _veto(reason_codes + ["RESIZED_BELOW_EXCHANGE_MINIMUM"])

    trade_stop_risk_usd = (
        (final_notional * stop_dist_pct).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
        if stop_dist_pct is not None
        else Decimal("0")
    )
    was_resized = approved_qty < proposed_qty
    return SizingResult(
        approved_qty=approved_qty,
        was_resized=was_resized,
        vetoed=False,
        reason_codes=reason_codes,
        raw_kelly=raw_kelly,
        fractional_kelly=frac_kelly,
        vol_scalar=vol_scalar,
        empirical_cvar_pct=asset_cvar_pct,
        portfolio_cvar_pct=portfolio_cvar_pct,
        max_notional_usd=final_notional,
        book_impact_pct=(final_notional / side_depth) if side_depth > Decimal("0") else Decimal("999"),
        trade_stop_risk_usd=trade_stop_risk_usd,
        portfolio_open_stop_risk_usd=existing_open_stop_risk + trade_stop_risk_usd,
    )
