"""
src/quant/execution_realism.py — Truth-Grade Execution Simulation Engine
========================================================================
Shared institutional execution realism layer used by BOTH:
  1. Forward Paper Trading (scripts/tiger_worker.py --paper)
  2. Historical Backtesting & Counterfactual Replay

Enforces the Kronos Institutional Accuracy & Verification Standard:
  - Strictly Decimal financial math (AGENTS.md Invariant 1)
  - Zero same-candle retroactive entry fills (causality gate)
  - Dynamic slippage (live half-spread + Almgren-Chriss impact + floor)
  - Order-type faithful maker/taker VIP0 fees (0.02% maker / 0.05% taker)
  - Hard Take-Profit limit cap (zero phantom positive overshoot)
  - Sub-second WS tick & intra-candle High/Low stop-loss evaluation
  - Pessimistic tie-breaker: STOP_LOSS always wins if both TP and SL touch in same bar
"""

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
import math
from typing import Iterable, List, Optional, Sequence, Tuple


MAJOR_SYMBOLS = frozenset({"BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"})


@dataclass(frozen=True)
class ExecutionFrictionConfig:
    """Binance USD(S)-M Futures VIP0 realistic execution friction parameters."""
    maker_fee_pct: Decimal = Decimal("0.0002")              # 2 bps limit maker fee
    taker_fee_pct: Decimal = Decimal("0.0005")              # 5 bps market/stop taker fee
    major_slippage_floor_bps: Decimal = Decimal("2.0")      # 2 bps floor for top-liquidity majors
    alt_entry_slippage_floor_bps: Decimal = Decimal("5.0")  # 5 bps floor for mid-cap breakout entries
    alt_stop_slippage_floor_bps: Decimal = Decimal("8.0")   # 8 bps floor for stop-market flushes
    almgren_chriss_eta: Decimal = Decimal("0.5")            # Square-root market impact coefficient
    default_daily_volatility: Decimal = Decimal("0.06")     # 6% baseline daily vol for volatile alts
    stress_multiplier: Decimal = Decimal("1.0")             # 1.0x reality, 1.5x stressed, 2.0x hostile


DEFAULT_FRICTION_CONFIG = ExecutionFrictionConfig()


@dataclass(frozen=True)
class TickQuote:
    """Minimal causal trade tick for exact intrabar fill/exit ordering."""
    price: Decimal
    timestamp_ms: int


@dataclass(frozen=True)
class EntryFillResult:
    """Outcome of causal entry fill evaluation."""
    filled: bool
    fill_price: Decimal = Decimal("0")
    slippage_pct: Decimal = Decimal("0")
    entry_fee_pct: Decimal = Decimal("0")
    fill_source: str = "NONE"   # "WS_TICK" | "NEXT_BAR_KLINE" | "NONE"
    reason: str = ""


@dataclass(frozen=True)
class ExitFillResult:
    """Outcome of pessimistic bracket/market exit evaluation."""
    triggered: bool
    action: str = "HOLD"        # "TAKE_PROFIT" | "STOP_LOSS" | "MARKET_FLATTEN" | "HOLD"
    exit_price: Decimal = Decimal("0")
    slippage_pct: Decimal = Decimal("0")
    exit_fee_pct: Decimal = Decimal("0")
    trigger_source: str = "NONE"  # "WS_TICK" | "INTERVAL_EXTREME" | "MARKET_CLOSE" | "NONE"
    reason: str = ""


@dataclass(frozen=True)
class TradePnLBreakdown:
    """Exact Decimal accounting breakdown separating gross edge from friction drag."""
    gross_return_pct: Decimal
    total_fee_pct: Decimal
    funding_pct: Decimal
    net_return_pct: Decimal
    gross_pnl_usd: Decimal
    friction_usd: Decimal
    net_pnl_usd: Decimal
    is_net_win: bool


def compute_dynamic_slippage_pct(
    symbol: str,
    notional_usd: Decimal,
    adv_24h_usd: Decimal = Decimal("50000000"),
    live_spread_pct: Optional[Decimal] = None,
    is_stop_exit: bool = False,
    daily_volatility: Optional[Decimal] = None,
    cfg: ExecutionFrictionConfig = DEFAULT_FRICTION_CONFIG,
) -> Decimal:
    """
    Computes adverse market/stop slippage as a fractional rate (e.g. Decimal("0.0005") = 5 bps):
        slippage = (half_spread + max(floor, almgren_chriss_impact)) * stress_multiplier
    """
    sym = symbol.upper()
    if sym in MAJOR_SYMBOLS:
        floor_bps = cfg.major_slippage_floor_bps
    else:
        floor_bps = cfg.alt_stop_slippage_floor_bps if is_stop_exit else cfg.alt_entry_slippage_floor_bps
    floor_pct = floor_bps / Decimal("10000")

    # Square-root market impact (Almgren-Chriss)
    vol = daily_volatility if (daily_volatility is not None and daily_volatility > Decimal("0")) else cfg.default_daily_volatility
    if adv_24h_usd > Decimal("0") and notional_usd > Decimal("0"):
        part_ratio = float(notional_usd / adv_24h_usd)
        sqrt_part = Decimal(str(math.sqrt(max(0.0, part_ratio))))
        impact_pct = cfg.almgren_chriss_eta * vol * sqrt_part
    else:
        impact_pct = floor_pct

    half_spread = Decimal("0")
    if live_spread_pct is not None and live_spread_pct > Decimal("0"):
        half_spread = live_spread_pct / Decimal("2")

    base_slip = half_spread + max(floor_pct, impact_pct)
    stressed = base_slip * cfg.stress_multiplier
    return stressed.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)


def evaluate_causal_breakout_entry(
    side: str,
    trigger_price: Decimal,
    signal_created_ts_ms: int,
    symbol: str,
    ticks_after_signal: Sequence[TickQuote] = (),
    fallback_bar_open_ts_ms: Optional[int] = None,
    fallback_bar_high: Optional[Decimal] = None,
    fallback_bar_low: Optional[Decimal] = None,
    best_bid: Optional[Decimal] = None,
    best_ask: Optional[Decimal] = None,
    live_spread_pct: Optional[Decimal] = None,
    notional_usd: Decimal = Decimal("100.00"),
    adv_24h_usd: Decimal = Decimal("50000000"),
    cfg: ExecutionFrictionConfig = DEFAULT_FRICTION_CONFIG,
) -> EntryFillResult:
    """
    Evaluates whether a Stop-Market breakout entry fills CAUSALLY (strictly after signal creation).

    Anti-Fantasy Guarantees:
      1. Zero same-candle retroactive fills: fallback kline is IGNORED unless its open timestamp
         is strictly >= signal_created_ts_ms (a fresh candle opened after the signal).
      2. When live WS ticks exist after signal creation, walks them chronologically to find
         the exact first crossing tick.
      3. Applies realistic taker fee (0.05%) and adverse breakout slippage + spread crossing.
    """
    side_u = side.upper()
    if trigger_price <= Decimal("0") or side_u not in ("BUY", "SELL"):
        return EntryFillResult(filled=False, reason="Invalid trigger or side")

    slip_pct = compute_dynamic_slippage_pct(
        symbol=symbol,
        notional_usd=notional_usd,
        adv_24h_usd=adv_24h_usd,
        live_spread_pct=live_spread_pct,
        is_stop_exit=False,
        cfg=cfg,
    )

    # Path A: Live causal WS tick stream (highest fidelity)
    causal_ticks = sorted(
        (t for t in ticks_after_signal if t.timestamp_ms > signal_created_ts_ms and t.price > Decimal("0")),
        key=lambda t: t.timestamp_ms,
    )
    if causal_ticks:
        for tick in causal_ticks:
            if side_u == "BUY" and tick.price >= trigger_price:
                base_px = max(trigger_price, tick.price)
                if best_ask is not None and best_ask > base_px:
                    base_px = best_ask
                fill_px = base_px * (Decimal("1") + slip_pct)
                return EntryFillResult(
                    filled=True,
                    fill_price=fill_px,
                    slippage_pct=slip_pct,
                    entry_fee_pct=cfg.taker_fee_pct,
                    fill_source="WS_TICK",
                    reason=f"Causal WS tick {tick.price} crossed BUY trigger {trigger_price} (+{slip_pct*10000:.1f}bps slip)",
                )
            if side_u == "SELL" and tick.price <= trigger_price:
                base_px = min(trigger_price, tick.price)
                if best_bid is not None and Decimal("0") < best_bid < base_px:
                    base_px = best_bid
                fill_px = base_px * (Decimal("1") - slip_pct)
                return EntryFillResult(
                    filled=True,
                    fill_price=fill_px,
                    slippage_pct=slip_pct,
                    entry_fee_pct=cfg.taker_fee_pct,
                    fill_source="WS_TICK",
                    reason=f"Causal WS tick {tick.price} crossed SELL trigger {trigger_price} (-{slip_pct*10000:.1f}bps slip)",
                )
        return EntryFillResult(filled=False, reason="Post-signal WS ticks did not cross entry trigger")

    # Path B: Candle fallback — ONLY allowed on a strictly NEW candle opened AFTER signal creation!
    if (
        fallback_bar_open_ts_ms is not None
        and fallback_bar_open_ts_ms >= signal_created_ts_ms
        and fallback_bar_high is not None
        and fallback_bar_low is not None
    ):
        if side_u == "BUY" and fallback_bar_high >= trigger_price:
            base_px = max(trigger_price, best_ask) if (best_ask is not None and best_ask > trigger_price) else trigger_price
            fill_px = base_px * (Decimal("1") + slip_pct)
            return EntryFillResult(
                filled=True,
                fill_price=fill_px,
                slippage_pct=slip_pct,
                entry_fee_pct=cfg.taker_fee_pct,
                fill_source="NEXT_BAR_KLINE",
                reason=f"Next-bar high {fallback_bar_high} crossed BUY trigger {trigger_price} (+{slip_pct*10000:.1f}bps slip)",
            )
        if side_u == "SELL" and fallback_bar_low <= trigger_price:
            base_px = min(trigger_price, best_bid) if (best_bid is not None and Decimal("0") < best_bid < trigger_price) else trigger_price
            fill_px = base_px * (Decimal("1") - slip_pct)
            return EntryFillResult(
                filled=True,
                fill_price=fill_px,
                slippage_pct=slip_pct,
                entry_fee_pct=cfg.taker_fee_pct,
                fill_source="NEXT_BAR_KLINE",
                reason=f"Next-bar low {fallback_bar_low} crossed SELL trigger {trigger_price} (-{slip_pct*10000:.1f}bps slip)",
            )

    return EntryFillResult(
        filled=False,
        reason="No causal post-signal crossing (same-candle retroactive fill blocked)",
    )


def evaluate_pessimistic_bracket_exit(
    side: str,
    take_profit: Decimal,
    stop_loss: Decimal,
    symbol: str,
    ordered_ticks: Sequence[TickQuote] = (),
    interval_high: Optional[Decimal] = None,
    interval_low: Optional[Decimal] = None,
    current_price: Optional[Decimal] = None,
    live_spread_pct: Optional[Decimal] = None,
    notional_usd: Decimal = Decimal("100.00"),
    adv_24h_usd: Decimal = Decimal("50000000"),
    require_tp_penetration: bool = True,
    cfg: ExecutionFrictionConfig = DEFAULT_FRICTION_CONFIG,
) -> ExitFillResult:
    """
    Evaluates Take-Profit (Limit) and Stop-Loss (Stop-Market) exits with institutional realism:

    Anti-Fantasy Guarantees:
      1. Take-Profit fill is STRICTLY CAPPED at `take_profit` (never `current_price` overshoot).
      2. Queue penetration: when `require_tp_penetration=True`, price must trade strictly
         beyond `take_profit` (`>` for BUY, `<` for SELL) to guarantee passive limit fill.
      3. Stop-Loss inspects sub-second WS ticks AND full interval High/Low (catches fast wicks).
      4. Stop-Loss fills with adverse stop slippage + taker fee (0.05%).
      5. Pessimistic Tie-Breaker: without tick-level ordering, if BOTH SL and TP touch in the
         same interval, STOP_LOSS ALWAYS WINS.
    """
    side_u = side.upper()
    if side_u not in ("BUY", "SELL"):
        return ExitFillResult(triggered=False, action="HOLD", reason="Invalid side")

    stop_slip = compute_dynamic_slippage_pct(
        symbol=symbol,
        notional_usd=notional_usd,
        adv_24h_usd=adv_24h_usd,
        live_spread_pct=live_spread_pct,
        is_stop_exit=True,
        cfg=cfg,
    )

    # Path A: Exact chronological tick ordering (live WS @aggTrade stream)
    valid_ticks = sorted(
        (t for t in ordered_ticks if t.price > Decimal("0")),
        key=lambda t: t.timestamp_ms,
    )
    if valid_ticks:
        for tick in valid_ticks:
            px = tick.price
            if side_u == "BUY":
                if px <= stop_loss:
                    worst_px = min(stop_loss, px)
                    fill_px = worst_px * (Decimal("1") - stop_slip)
                    return ExitFillResult(
                        triggered=True,
                        action="STOP_LOSS",
                        exit_price=fill_px,
                        slippage_pct=stop_slip,
                        exit_fee_pct=cfg.taker_fee_pct,
                        trigger_source="WS_TICK",
                        reason=f"WS tick {px} breached BUY SL {stop_loss} (-{stop_slip*10000:.1f}bps slip)",
                    )
                tp_hit = (px > take_profit) if require_tp_penetration else (px >= take_profit)
                if tp_hit:
                    return ExitFillResult(
                        triggered=True,
                        action="TAKE_PROFIT",
                        exit_price=take_profit,  # Strictly capped at resting limit TP
                        slippage_pct=Decimal("0"),
                        exit_fee_pct=cfg.maker_fee_pct,
                        trigger_source="WS_TICK",
                        reason=f"WS tick {px} penetrated BUY Limit TP {take_profit} (capped at TP)",
                    )
            else:  # SELL
                if px >= stop_loss:
                    worst_px = max(stop_loss, px)
                    fill_px = worst_px * (Decimal("1") + stop_slip)
                    return ExitFillResult(
                        triggered=True,
                        action="STOP_LOSS",
                        exit_price=fill_px,
                        slippage_pct=stop_slip,
                        exit_fee_pct=cfg.taker_fee_pct,
                        trigger_source="WS_TICK",
                        reason=f"WS tick {px} breached SELL SL {stop_loss} (+{stop_slip*10000:.1f}bps slip)",
                    )
                tp_hit = (px < take_profit) if require_tp_penetration else (px <= take_profit)
                if tp_hit:
                    return ExitFillResult(
                        triggered=True,
                        action="TAKE_PROFIT",
                        exit_price=take_profit,  # Strictly capped at resting limit TP
                        slippage_pct=Decimal("0"),
                        exit_fee_pct=cfg.maker_fee_pct,
                        trigger_source="WS_TICK",
                        reason=f"WS tick {px} penetrated SELL Limit TP {take_profit} (capped at TP)",
                    )

    # Path B: Interval High/Low check (catches wicks even if WS dropped or in bar backtests)
    # PESSIMISTIC TIE-BREAKER: Always evaluate STOP_LOSS before TAKE_PROFIT!
    eff_high = interval_high if interval_high is not None else current_price
    eff_low = interval_low if interval_low is not None else current_price
    if current_price is not None and eff_high is not None and eff_low is not None:
        eff_high = max(eff_high, current_price)
        eff_low = min(eff_low, current_price)

    if eff_high is not None and eff_low is not None:
        if side_u == "BUY":
            # 1. Check SL FIRST (pessimistic tie-breaker)
            if eff_low <= stop_loss:
                fill_px = stop_loss * (Decimal("1") - stop_slip)
                return ExitFillResult(
                    triggered=True,
                    action="STOP_LOSS",
                    exit_price=fill_px,
                    slippage_pct=stop_slip,
                    exit_fee_pct=cfg.taker_fee_pct,
                    trigger_source="INTERVAL_EXTREME",
                    reason=f"Interval low {eff_low} breached BUY SL {stop_loss} (pessimistic stop, -{stop_slip*10000:.1f}bps slip)",
                )
            # 2. Check TP second — strictly capped at take_profit
            tp_hit = (eff_high > take_profit) if require_tp_penetration else (eff_high >= take_profit)
            if tp_hit:
                return ExitFillResult(
                    triggered=True,
                    action="TAKE_PROFIT",
                    exit_price=take_profit,
                    slippage_pct=Decimal("0"),
                    exit_fee_pct=cfg.maker_fee_pct,
                    trigger_source="INTERVAL_EXTREME",
                    reason=f"Interval high {eff_high} penetrated BUY Limit TP {take_profit} (capped at TP)",
                )
        else:  # SELL
            # 1. Check SL FIRST (pessimistic tie-breaker)
            if eff_high >= stop_loss:
                fill_px = stop_loss * (Decimal("1") + stop_slip)
                return ExitFillResult(
                    triggered=True,
                    action="STOP_LOSS",
                    exit_price=fill_px,
                    slippage_pct=stop_slip,
                    exit_fee_pct=cfg.taker_fee_pct,
                    trigger_source="INTERVAL_EXTREME",
                    reason=f"Interval high {eff_high} breached SELL SL {stop_loss} (pessimistic stop, +{stop_slip*10000:.1f}bps slip)",
                )
            # 2. Check TP second — strictly capped at take_profit
            tp_hit = (eff_low < take_profit) if require_tp_penetration else (eff_low <= take_profit)
            if tp_hit:
                return ExitFillResult(
                    triggered=True,
                    action="TAKE_PROFIT",
                    exit_price=take_profit,
                    slippage_pct=Decimal("0"),
                    exit_fee_pct=cfg.maker_fee_pct,
                    trigger_source="INTERVAL_EXTREME",
                    reason=f"Interval low {eff_low} penetrated SELL Limit TP {take_profit} (capped at TP)",
                )

    return ExitFillResult(triggered=False, action="HOLD", reason="Bracket intact")


def evaluate_market_flatten_exit(
    side: str,
    current_price: Decimal,
    symbol: str,
    best_bid: Optional[Decimal] = None,
    best_ask: Optional[Decimal] = None,
    live_spread_pct: Optional[Decimal] = None,
    notional_usd: Decimal = Decimal("100.00"),
    adv_24h_usd: Decimal = Decimal("50000000"),
    action_label: str = "MARKET_FLATTEN",
    reason_prefix: str = "Market flatten",
    cfg: ExecutionFrictionConfig = DEFAULT_FRICTION_CONFIG,
) -> ExitFillResult:
    """
    Models an active market close (Capital Recycler, Stall Scratch, Hard 15m Kill)
    with realistic spread crossing + taker slippage + taker fee (0.05%).
    """
    side_u = side.upper()
    slip = compute_dynamic_slippage_pct(
        symbol=symbol,
        notional_usd=notional_usd,
        adv_24h_usd=adv_24h_usd,
        live_spread_pct=live_spread_pct,
        is_stop_exit=False,
        cfg=cfg,
    )
    if side_u == "BUY":
        # Closing a LONG sells into the bid
        base_px = min(current_price, best_bid) if (best_bid is not None and Decimal("0") < best_bid < current_price) else current_price
        fill_px = base_px * (Decimal("1") - slip)
    else:
        # Closing a SHORT buys into the ask
        base_px = max(current_price, best_ask) if (best_ask is not None and best_ask > current_price) else current_price
        fill_px = base_px * (Decimal("1") + slip)

    return ExitFillResult(
        triggered=True,
        action=action_label,
        exit_price=fill_px,
        slippage_pct=slip,
        exit_fee_pct=cfg.taker_fee_pct,
        trigger_source="MARKET_CLOSE",
        reason=f"{reason_prefix} (adverse slip {slip*10000:.1f}bps + taker fee)",
    )


def calculate_exact_trade_pnl(
    side: str,
    entry_price: Decimal,
    exit_price: Decimal,
    notional_usd: Decimal,
    entry_fee_pct: Decimal = Decimal("0.0005"),
    exit_fee_pct: Decimal = Decimal("0.0005"),
    funding_pct: Decimal = Decimal("0"),
) -> TradePnLBreakdown:
    """Pure-Decimal PnL breakdown separating gross return from fee/funding friction."""
    if entry_price <= Decimal("0") or notional_usd <= Decimal("0"):
        return TradePnLBreakdown(
            gross_return_pct=Decimal("0"),
            total_fee_pct=Decimal("0"),
            funding_pct=Decimal("0"),
            net_return_pct=Decimal("0"),
            gross_pnl_usd=Decimal("0"),
            friction_usd=Decimal("0"),
            net_pnl_usd=Decimal("0"),
            is_net_win=False,
        )

    side_u = side.upper()
    if side_u in ("BUY", "LONG"):
        gross_ret = (exit_price - entry_price) / entry_price
    else:
        gross_ret = (entry_price - exit_price) / entry_price

    total_fee_pct = entry_fee_pct + exit_fee_pct
    net_ret = gross_ret - total_fee_pct - funding_pct

    gross_usd = (notional_usd * gross_ret).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    friction_usd = (notional_usd * (total_fee_pct + funding_pct)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    net_usd = (notional_usd * net_ret).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)

    return TradePnLBreakdown(
        gross_return_pct=gross_ret,
        total_fee_pct=total_fee_pct,
        funding_pct=funding_pct,
        net_return_pct=net_ret,
        gross_pnl_usd=gross_usd,
        friction_usd=friction_usd,
        net_pnl_usd=net_usd,
        is_net_win=net_usd > Decimal("0"),
    )
