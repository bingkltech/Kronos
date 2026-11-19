"""
risk_engine/models.py — Strict Decimal Domain Models for the Institutional Risk Engine.

Zero dependency on alpha generation or exchange-specific modules.
All financial quantities, prices, balances, exposures, spreads, and risk ratios
are strictly represented as decimal.Decimal (Zero Float Financial Math).
"""

from __future__ import annotations

from dataclasses import dataclass, field
import datetime
from decimal import Decimal, InvalidOperation, ROUND_DOWN, ROUND_HALF_UP
from enum import Enum
from typing import Any, Dict, List, Optional, Union


NumericInput = Union[Decimal, int, str, float]


def to_decimal(value: NumericInput, field_name: str = "value") -> Decimal:
    """
    Safely convert numeric input to finite decimal.Decimal via string representation.
    Rejects booleans, None, NaN, and Infinity (fail-closed financial hygiene).
    """
    if isinstance(value, bool) or value is None:
        raise ValueError(f"Invalid numeric value for {field_name}: {value!r}")
    try:
        dec = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError(f"Cannot convert {field_name}={value!r} to Decimal") from exc
    if not dec.is_finite():
        raise ValueError(f"Non-finite Decimal value for {field_name}: {value!r}")
    return dec


def to_optional_decimal(
    value: Optional[NumericInput], field_name: str = "value"
) -> Optional[Decimal]:
    if value is None:
        return None
    return to_decimal(value, field_name)


class DecisionStatus(str, Enum):
    APPROVED = "APPROVED"
    RESIZED = "RESIZED"
    VETOED = "VETOED"
    KILL_SWITCH = "KILL_SWITCH"


class RiskMode(str, Enum):
    NORMAL = "NORMAL"
    THROTTLED_TIER1 = "THROTTLED_TIER1"
    REDUCE_ONLY = "REDUCE_ONLY"
    HALTED = "HALTED"


class OrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"

    @classmethod
    def coerce(cls, value: Union["OrderSide", str]) -> "OrderSide":
        if isinstance(value, cls):
            return value
        norm = str(value).strip().upper()
        if norm in ("BUY", "LONG"):
            return cls.BUY
        if norm in ("SELL", "SHORT"):
            return cls.SELL
        raise ValueError(f"Unsupported OrderSide: {value!r}")


class OrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP_MARKET = "STOP_MARKET"
    TAKE_PROFIT_MARKET = "TAKE_PROFIT_MARKET"

    @classmethod
    def coerce(cls, value: Union["OrderType", str]) -> "OrderType":
        if isinstance(value, cls):
            return value
        norm = str(value).strip().upper()
        return cls(norm)


class DiscrepancySeverity(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


@dataclass(frozen=True)
class ProposedOrder:
    """Alpha-agnostic order proposal submitted to the Risk Engine gatekeeper."""
    symbol: str
    side: OrderSide
    order_type: OrderType
    quantity: Decimal
    price: Decimal                           # Limit price (LIMIT) or reference entry price (MARKET)
    stop_loss: Optional[Decimal] = None
    take_profit: Optional[Decimal] = None
    conviction: Decimal = Decimal("0.65")    # Normalized [0, 1] signal conviction
    win_rate: Optional[Decimal] = None       # Empirical win probability [0, 1]
    payoff_ratio: Optional[Decimal] = None   # Empirical avg_win / avg_loss (> 0)
    reduce_only: bool = False
    exchange_enforces_reduce_only: bool = False  # True when wire payload carries native reduceOnly="true"
    is_gross_edge_estimate: bool = False     # True if win_rate/payoff are pre-fee gross estimates
    sample_size: int = 0                     # Empirical trade sample size backing win_rate/payoff
    round_trip_fee_bps: Decimal = Decimal("10.0")  # Round-trip fee assumption in bps (e.g. 10 bps = 0.10%)
    leverage: Decimal = Decimal("5")         # Intended isolated contract leverage for SL ROI check
    client_order_id: Optional[str] = None
    timestamp_ms: Optional[int] = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "symbol", str(self.symbol).strip().upper())
        object.__setattr__(self, "side", OrderSide.coerce(self.side))
        object.__setattr__(self, "order_type", OrderType.coerce(self.order_type))
        object.__setattr__(self, "quantity", to_decimal(self.quantity, "quantity"))
        object.__setattr__(self, "price", to_decimal(self.price, "price"))
        object.__setattr__(self, "stop_loss", to_optional_decimal(self.stop_loss, "stop_loss"))
        object.__setattr__(self, "take_profit", to_optional_decimal(self.take_profit, "take_profit"))
        object.__setattr__(self, "conviction", to_decimal(self.conviction, "conviction"))
        object.__setattr__(self, "win_rate", to_optional_decimal(self.win_rate, "win_rate"))
        object.__setattr__(self, "payoff_ratio", to_optional_decimal(self.payoff_ratio, "payoff_ratio"))
        object.__setattr__(self, "round_trip_fee_bps", to_decimal(self.round_trip_fee_bps, "round_trip_fee_bps"))
        object.__setattr__(self, "leverage", to_decimal(self.leverage, "leverage"))

    @property
    def notional_usd(self) -> Decimal:
        return (self.quantity * self.price).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)

    @property
    def stop_distance_pct(self) -> Optional[Decimal]:
        if self.stop_loss is None or self.price <= Decimal("0"):
            return None
        return abs(self.price - self.stop_loss) / self.price

    @property
    def stop_risk_usd(self) -> Decimal:
        if self.stop_loss is None:
            return Decimal("0")
        return abs(self.price - self.stop_loss) * abs(self.quantity)


@dataclass(frozen=True)
class PositionSnapshot:
    """Point-in-time snapshot of an open position."""
    symbol: str
    side: OrderSide
    quantity: Decimal
    entry_price: Decimal
    mark_price: Decimal
    unrealized_pnl: Decimal = Decimal("0")
    leverage: Decimal = Decimal("1")
    stop_loss: Optional[Decimal] = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "symbol", str(self.symbol).strip().upper())
        object.__setattr__(self, "side", OrderSide.coerce(self.side))
        object.__setattr__(self, "quantity", to_decimal(self.quantity, "quantity"))
        object.__setattr__(self, "entry_price", to_decimal(self.entry_price, "entry_price"))
        object.__setattr__(self, "mark_price", to_decimal(self.mark_price, "mark_price"))
        object.__setattr__(self, "unrealized_pnl", to_decimal(self.unrealized_pnl, "unrealized_pnl"))
        object.__setattr__(self, "leverage", to_decimal(self.leverage, "leverage"))
        object.__setattr__(self, "stop_loss", to_optional_decimal(self.stop_loss, "stop_loss"))

    @property
    def notional_usd(self) -> Decimal:
        return abs(self.quantity) * self.mark_price

    @property
    def signed_notional_usd(self) -> Decimal:
        sign = Decimal("1") if self.side == OrderSide.BUY else Decimal("-1")
        return sign * self.notional_usd

    def stop_risk_usd(self, fallback_stop_pct: Decimal = Decimal("0.02")) -> Decimal:
        """
        Worst-case dollar loss from current mark/entry to stop_loss.
        If an exchange position has no known stop_loss, uses conservative fallback_stop_pct.
        """
        if self.stop_loss is not None:
            if self.side == OrderSide.BUY:
                dist = max(Decimal("0"), self.mark_price - self.stop_loss)
            else:
                dist = max(Decimal("0"), self.stop_loss - self.mark_price)
            return dist * abs(self.quantity)
        return self.notional_usd * fallback_stop_pct


@dataclass(frozen=True)
class PortfolioState:
    """Point-in-time account equity, drawdown watermarks, and open exposures."""
    equity_usd: Decimal
    peak_equity_usd: Decimal
    intraday_start_equity_usd: Decimal
    free_margin_usd: Optional[Decimal] = None
    positions: Dict[str, PositionSnapshot] = field(default_factory=dict)
    realized_returns_series: List[Decimal] = field(default_factory=list)
    open_order_ids: List[str] = field(default_factory=list)
    timestamp_ms: Optional[int] = None

    def __post_init__(self) -> None:
        eq = to_decimal(self.equity_usd, "equity_usd")
        pk = to_decimal(self.peak_equity_usd, "peak_equity_usd")
        intra = to_decimal(self.intraday_start_equity_usd, "intraday_start_equity_usd")
        fm = to_optional_decimal(self.free_margin_usd, "free_margin_usd")
        object.__setattr__(self, "equity_usd", eq)
        object.__setattr__(self, "peak_equity_usd", pk)
        object.__setattr__(self, "intraday_start_equity_usd", intra)
        object.__setattr__(self, "free_margin_usd", eq if fm is None else fm)
        norm_returns = [to_decimal(r, "realized_return") for r in self.realized_returns_series]
        object.__setattr__(self, "realized_returns_series", norm_returns)
        norm_positions = {str(k).strip().upper(): v for k, v in self.positions.items()}
        object.__setattr__(self, "positions", norm_positions)

    def rolling_drawdown_pct(self) -> Decimal:
        """Non-negative drawdown ratio from rolling equity high-water mark (e.g. 0.03 = -3%)."""
        if self.peak_equity_usd <= Decimal("0"):
            return Decimal("1")
        dd = (self.peak_equity_usd - self.equity_usd) / self.peak_equity_usd
        return max(Decimal("0"), dd)

    def intraday_drawdown_pct(self) -> Decimal:
        """Non-negative drawdown ratio from intraday starting equity."""
        if self.intraday_start_equity_usd <= Decimal("0"):
            return Decimal("1")
        dd = (self.intraday_start_equity_usd - self.equity_usd) / self.intraday_start_equity_usd
        return max(Decimal("0"), dd)

    def effective_drawdown_pct(self) -> Decimal:
        """Worst of rolling and intraday drawdown."""
        return max(self.rolling_drawdown_pct(), self.intraday_drawdown_pct())

    def gross_exposure_usd(self) -> Decimal:
        return sum((p.notional_usd for p in self.positions.values()), Decimal("0"))

    def net_exposure_usd(self) -> Decimal:
        return sum((p.signed_notional_usd for p in self.positions.values()), Decimal("0"))

    def gross_leverage(self) -> Decimal:
        if self.equity_usd <= Decimal("0"):
            return Decimal("999")
        return self.gross_exposure_usd() / self.equity_usd

    def net_leverage(self) -> Decimal:
        if self.equity_usd <= Decimal("0"):
            return Decimal("999")
        return abs(self.net_exposure_usd()) / self.equity_usd

    def symbol_exposure_usd(self, symbol: str) -> Decimal:
        pos = self.positions.get(symbol.strip().upper())
        return pos.notional_usd if pos else Decimal("0")

    def total_open_stop_risk_usd(self, fallback_stop_pct: Decimal = Decimal("0.02")) -> Decimal:
        """Aggregate dollar risk-at-stop across all currently open positions."""
        return sum(
            (p.stop_risk_usd(fallback_stop_pct=fallback_stop_pct) for p in self.positions.values()),
            Decimal("0"),
        )


@dataclass(frozen=True)
class OrderBookSnapshot:
    """Top-of-book quote and visible liquidity depth snapshot."""
    best_bid: Decimal
    best_ask: Decimal
    bid_depth_usd: Decimal
    ask_depth_usd: Decimal
    top_of_book_depth_usd: Optional[Decimal] = None

    def __post_init__(self) -> None:
        bid = to_decimal(self.best_bid, "best_bid")
        ask = to_decimal(self.best_ask, "best_ask")
        b_depth = to_decimal(self.bid_depth_usd, "bid_depth_usd")
        a_depth = to_decimal(self.ask_depth_usd, "ask_depth_usd")
        tob = to_optional_decimal(self.top_of_book_depth_usd, "top_of_book_depth_usd")
        object.__setattr__(self, "best_bid", bid)
        object.__setattr__(self, "best_ask", ask)
        object.__setattr__(self, "bid_depth_usd", b_depth)
        object.__setattr__(self, "ask_depth_usd", a_depth)
        object.__setattr__(
            self, "top_of_book_depth_usd", (b_depth + a_depth) if tob is None else tob
        )

    def mid_price(self) -> Decimal:
        return (self.best_bid + self.best_ask) / Decimal("2")

    def spread_bps(self) -> Decimal:
        mid = self.mid_price()
        if mid <= Decimal("0") or self.best_ask < self.best_bid:
            return Decimal("99999")
        return ((self.best_ask - self.best_bid) / mid) * Decimal("10000")

    def execution_side_depth_usd(self, side: OrderSide) -> Decimal:
        return self.ask_depth_usd if side == OrderSide.BUY else self.bid_depth_usd


@dataclass(frozen=True)
class MarketSnapshot:
    """Live market microstructure, volatility, and correlation snapshot."""
    symbol: str
    mark_price: Decimal
    order_book: OrderBookSnapshot
    realized_vol: Decimal                                 # Rolling volatility (e.g. 0.02 = 2%)
    baseline_vol: Decimal = Decimal("0.015")              # Baseline regime volatility
    atr_pct: Optional[Decimal] = None                     # ATR / mark_price
    asset_returns_series: List[Decimal] = field(default_factory=list)
    pairwise_correlations: Dict[str, Decimal] = field(default_factory=dict)
    portfolio_avg_correlation: Optional[Decimal] = None
    timestamp_ms: Optional[int] = None
    step_size: Decimal = Decimal("0.0001")                # Lot quantization step
    min_qty: Decimal = Decimal("0.0001")
    min_notional_usd: Decimal = Decimal("5.00")

    def __post_init__(self) -> None:
        object.__setattr__(self, "symbol", str(self.symbol).strip().upper())
        object.__setattr__(self, "mark_price", to_decimal(self.mark_price, "mark_price"))
        object.__setattr__(self, "realized_vol", to_decimal(self.realized_vol, "realized_vol"))
        object.__setattr__(self, "baseline_vol", to_decimal(self.baseline_vol, "baseline_vol"))
        object.__setattr__(self, "atr_pct", to_optional_decimal(self.atr_pct, "atr_pct"))
        object.__setattr__(
            self,
            "asset_returns_series",
            [to_decimal(r, "asset_return") for r in self.asset_returns_series],
        )
        object.__setattr__(
            self,
            "pairwise_correlations",
            {str(k).strip().upper(): to_decimal(v, "corr") for k, v in self.pairwise_correlations.items()},
        )
        object.__setattr__(
            self,
            "portfolio_avg_correlation",
            to_optional_decimal(self.portfolio_avg_correlation, "portfolio_avg_correlation"),
        )
        object.__setattr__(self, "step_size", to_decimal(self.step_size, "step_size"))
        object.__setattr__(self, "min_qty", to_decimal(self.min_qty, "min_qty"))
        object.__setattr__(self, "min_notional_usd", to_decimal(self.min_notional_usd, "min_notional_usd"))

    def quantize_qty_down(self, qty: Decimal) -> Decimal:
        """Quantize quantity strictly downward to step_size so risk caps are never exceeded."""
        if qty <= Decimal("0"):
            return Decimal("0")
        if self.step_size <= Decimal("0"):
            return qty
        units = (qty / self.step_size).to_integral_value(rounding=ROUND_DOWN)
        return units * self.step_size


@dataclass(frozen=True)
class RiskDecision:
    """
    Structured, immutable clearance verdict emitted by RiskEngine.evaluate_order().
    All financial values are strictly Decimal.
    """
    status: DecisionStatus
    approved_qty: Decimal
    reason_codes: List[str]
    metrics_snapshot: Dict[str, Any]
    risk_mode: RiskMode = RiskMode.NORMAL
    actions_required: List[str] = field(default_factory=list)
    timestamp_utc: str = field(
        default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat()
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "approved_qty", to_decimal(self.approved_qty, "approved_qty"))

    @property
    def is_executable(self) -> bool:
        return self.status in (DecisionStatus.APPROVED, DecisionStatus.RESIZED) and self.approved_qty > Decimal("0")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp_utc": self.timestamp_utc,
            "status": self.status.value,
            "risk_mode": self.risk_mode.value,
            "approved_qty": str(self.approved_qty),
            "reason_codes": list(self.reason_codes),
            "actions_required": list(self.actions_required),
            "metrics_snapshot": {
                k: str(v) if isinstance(v, Decimal) else v
                for k, v in self.metrics_snapshot.items()
            },
        }


@dataclass(frozen=True)
class ReconciliationDiscrepancy:
    """Single mismatch discovered between internal OMS state and exchange state."""
    discrepancy_type: str      # PHANTOM_EXCHANGE_POSITION | GHOST_INTERNAL_POSITION | QTY_MISMATCH | SIDE_MISMATCH | ORPHAN_OPEN_ORDER
    symbol: str
    severity: DiscrepancySeverity
    internal_value: str
    exchange_value: str
    action_taken: str


@dataclass(frozen=True)
class ReconciliationReport:
    """Summary emitted by a single Layer-4 post-trade reconciliation pass."""
    timestamp_utc: str
    is_synchronized: bool
    discrepancies: List[ReconciliationDiscrepancy]
    kill_switch_triggered: bool = False
    actions_taken: List[str] = field(default_factory=list)
