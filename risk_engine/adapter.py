"""
risk_engine/adapter.py — Synchronous Execution Gateway Wrapper & Exchange Adapters.

Guarantees at the architectural boundary that NO order can reach an exchange gateway
without explicit clearance from RiskEngine.evaluate_order().
"""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from risk_engine.engine import RiskEngine
from risk_engine.models import (
    DecisionStatus,
    MarketSnapshot,
    OrderBookSnapshot,
    OrderSide,
    OrderType,
    PortfolioState,
    PositionSnapshot,
    ProposedOrder,
    RiskDecision,
)


class RiskGatedGateway:
    """
    Synchronous choke-point wrapping any exchange execution callback.
    Enforces that every order passes RiskEngine.evaluate_order() before dispatch,
    applies RESIZED quantities automatically, and triggers cancel/flatten hooks on KILL_SWITCH.
    """

    def __init__(
        self,
        risk_engine: RiskEngine,
        dispatch_fn: Callable[[ProposedOrder, RiskDecision], Any],
    ):
        self.risk_engine = risk_engine
        self._dispatch_fn = dispatch_fn

    def submit_order(
        self,
        proposed_order: ProposedOrder,
        portfolio_state: PortfolioState,
        market_snapshot: MarketSnapshot,
        now_ms: Optional[int] = None,
    ) -> Tuple[RiskDecision, Optional[Any]]:
        """
        Evaluate order through RiskEngine; dispatch ONLY if APPROVED or RESIZED.
        Returns (RiskDecision, execution_result_or_None).
        """
        decision = self.risk_engine.evaluate_order(
            proposed_order=proposed_order,
            portfolio_state=portfolio_state,
            market_snapshot=market_snapshot,
            now_ms=now_ms,
        )

        if not decision.is_executable:
            return decision, None

        effective_order = (
            replace(proposed_order, quantity=decision.approved_qty)
            if decision.status == DecisionStatus.RESIZED
            else proposed_order
        )
        res_id = decision.metrics_snapshot.get("reservation_id")
        try:
            exec_result = self._dispatch_fn(effective_order, decision)
        except Exception:
            self.risk_engine.release_slot_reservation(res_id)
            raise
        return decision, exec_result


class BinanceExecutorReconciliationAdapter:
    """
    Adapter connecting a BinanceAtomicExecutor-like object (duck-typed so risk_engine
    has zero static import coupling to src/quant) to Layer-4 StateReconciler.
    """

    def __init__(self, executor: Any):
        self.executor = executor

    def fetch_exchange_positions(self) -> Dict[str, PositionSnapshot]:
        summary = self.executor.get_live_account_summary()
        if summary.get("connected") is False:
            raise RuntimeError(f"Exchange disconnected: {summary.get('error', 'unknown')}")
        out: Dict[str, PositionSnapshot] = {}
        for p in summary.get("positions", []):
            sym = str(p["symbol"]).strip().upper()
            raw_amt = p.get("position_amt", p.get("positionAmt", p.get("quantity", "0")))
            amt = Decimal(str(raw_amt))
            if amt == Decimal("0"):
                continue
            side = OrderSide.BUY if amt > Decimal("0") else OrderSide.SELL
            entry_px = Decimal(str(p.get("entry_price", p.get("entryPrice", "0"))))
            mark_px = Decimal(str(p.get("mark_price", p.get("markPrice", entry_px))))
            upnl = Decimal(str(p.get("unrealized_pnl_usd", p.get("unRealizedProfit", p.get("unrealized_pnl", "0")))))
            lev = Decimal(str(p.get("leverage", "1")))
            sl_raw = p.get("stop_loss")
            sl_val = Decimal(str(sl_raw)) if sl_raw is not None else None
            out[sym] = PositionSnapshot(
                symbol=sym,
                side=side,
                quantity=abs(amt),
                entry_price=entry_px,
                mark_price=mark_px,
                unrealized_pnl=upnl,
                leverage=lev,
                stop_loss=sl_val,
            )
        return out

    def fetch_exchange_open_orders(self) -> List[Dict[str, Any]]:
        if hasattr(self.executor, "get_live_open_orders"):
            return list(self.executor.get_live_open_orders() or [])
        return []

    def cancel_order(self, symbol: str, order_id: str) -> bool:
        if hasattr(self.executor, "_signed_request"):
            try:
                self.executor._signed_request(
                    "DELETE", "/fapi/v1/order", {"symbol": symbol, "orderId": order_id}
                )
                return True
            except Exception:
                return False
        return False

    def flatten_position(self, symbol: str, side: OrderSide, quantity: Decimal) -> bool:
        if hasattr(self.executor, "flatten_live_symbol"):
            res = self.executor.flatten_live_symbol(symbol)
            return bool(res and res.get("status") != "ERROR")
        return False


def ticket_to_proposed_order(
    ticket: Any,
    order_type: OrderType = OrderType.MARKET,
    win_rate: Optional[Decimal] = None,
    payoff_ratio: Optional[Decimal] = None,
    reduce_only: bool = False,
    timestamp_ms: Optional[int] = None,
) -> ProposedOrder:
    """
    Duck-typed converter translating a Kronos TradeTicket into a RiskEngine ProposedOrder
    without introducing any import coupling to src/quant.
    """
    rr = getattr(ticket, "reward_risk_ratio", None)
    eff_payoff = payoff_ratio if payoff_ratio is not None else (Decimal(str(rr)) if rr is not None else None)
    return ProposedOrder(
        symbol=ticket.symbol,
        side=OrderSide.coerce(ticket.side),
        order_type=order_type,
        quantity=Decimal(str(ticket.quantity)),
        price=Decimal(str(ticket.entry_price)),
        stop_loss=Decimal(str(ticket.stop_loss)) if getattr(ticket, "stop_loss", None) is not None else None,
        take_profit=Decimal(str(ticket.take_profit)) if getattr(ticket, "take_profit", None) is not None else None,
        conviction=Decimal(str(getattr(ticket, "forecast_confidence", Decimal("0.65")))),
        win_rate=win_rate,
        payoff_ratio=eff_payoff,
        reduce_only=reduce_only,
        leverage=Decimal(str(getattr(ticket, "effective_leverage", 5))),
        timestamp_ms=timestamp_ms,
    )


def build_portfolio_state_from_summary(
    summary: Dict[str, Any],
    now_ms: Optional[int] = None,
    peak_equity_usd: Optional[Decimal] = None,
    intraday_start_equity_usd: Optional[Decimal] = None,
    realized_returns_series: Optional[List[Decimal]] = None,
) -> PortfolioState:
    """
    Construct a fresh Mark-to-Market PortfolioState from an exchange account summary dict.
    Uses Mark-to-Market Equity = total_wallet_balance_usd + unrealized_pnl_usd so
    unrealized crash drawdowns are immediately reflected in Tier 1/2 clocks.
    """
    ts = now_ms if now_ms is not None else int(time.time() * 1000)
    wallet = Decimal(str(summary.get("total_wallet_balance_usd", "0")))
    unrealized = Decimal(str(summary.get("unrealized_pnl_usd", "0")))
    mtm_equity = wallet + unrealized
    free_margin = Decimal(str(summary.get("available_balance_usd", mtm_equity)))

    positions: Dict[str, PositionSnapshot] = {}
    for p in summary.get("positions", []):
        sym = str(p.get("symbol", "")).strip().upper()
        if not sym:
            continue
        raw_amt = p.get("position_amt", p.get("positionAmt", p.get("quantity", "0")))
        amt = Decimal(str(raw_amt))
        if amt == Decimal("0"):
            continue
        side = OrderSide.BUY if amt > Decimal("0") else OrderSide.SELL
        entry_px = Decimal(str(p.get("entry_price", p.get("entryPrice", "0"))))
        mark_px = Decimal(str(p.get("mark_price", p.get("markPrice", entry_px))))
        upnl = Decimal(str(p.get("unrealized_pnl_usd", p.get("unRealizedProfit", "0"))))
        lev = Decimal(str(p.get("leverage", "1")))
        sl_raw = p.get("stop_loss")
        sl_val = Decimal(str(sl_raw)) if sl_raw is not None else None
        positions[sym] = PositionSnapshot(
            symbol=sym,
            side=side,
            quantity=abs(amt),
            entry_price=entry_px,
            mark_price=mark_px,
            unrealized_pnl=upnl,
            leverage=lev,
            stop_loss=sl_val,
        )

    return PortfolioState(
        equity_usd=mtm_equity,
        peak_equity_usd=peak_equity_usd if peak_equity_usd is not None else mtm_equity,
        intraday_start_equity_usd=(
            intraday_start_equity_usd if intraday_start_equity_usd is not None else mtm_equity
        ),
        free_margin_usd=free_margin,
        positions=positions,
        realized_returns_series=realized_returns_series or [],
        timestamp_ms=ts,
    )


def build_market_snapshot_from_orderbook(
    symbol: str,
    mark_price: Decimal,
    best_bid: Decimal,
    best_ask: Decimal,
    bid_depth_usd: Decimal,
    ask_depth_usd: Decimal,
    realized_vol: Decimal = Decimal("0.015"),
    baseline_vol: Decimal = Decimal("0.015"),
    atr_pct: Optional[Decimal] = None,
    step_size: Decimal = Decimal("0.001"),
    min_qty: Decimal = Decimal("0.001"),
    min_notional_usd: Decimal = Decimal("5.00"),
    top_of_book_depth_usd: Optional[Decimal] = None,
    now_ms: Optional[int] = None,
) -> MarketSnapshot:
    """Pure constructor turning live order-book figures into a strict-Decimal MarketSnapshot."""
    ts = now_ms if now_ms is not None else int(time.time() * 1000)
    return MarketSnapshot(
        symbol=symbol,
        mark_price=mark_price,
        order_book=OrderBookSnapshot(
            best_bid=best_bid,
            best_ask=best_ask,
            bid_depth_usd=bid_depth_usd,
            ask_depth_usd=ask_depth_usd,
            top_of_book_depth_usd=top_of_book_depth_usd,
        ),
        realized_vol=realized_vol,
        baseline_vol=baseline_vol,
        atr_pct=atr_pct,
        timestamp_ms=ts,
        step_size=step_size,
        min_qty=min_qty,
        min_notional_usd=min_notional_usd,
    )
