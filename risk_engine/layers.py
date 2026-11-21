"""
risk_engine/layers.py — Four-Layer Electronic Defense-in-Depth Controls (v3 Real-Money Integrity).

Layer 1: Signal & Regime Layer
    - Abnormal volatility spikes
    - Scale-invariant liquidity evaporation (bid-ask spread disaster ceiling + 10x order-notional depth floor)
    - Stage-2 72h shadow warnings (spread > 5 bps, cost multiple < 4x)
    - Cross-asset correlation convergence

Layer 2: Pre-Trade OMS Layer
    - Scale-aware fat-finger notional cap (max($100, 0.50*equity) on small accounts; $25k hard cap)
    - Mandatory Stop-Loss, Noise-Floor SL (>=0.66% L#16/L#39), Max SL ROI (<=6.0% L#25), Net R:R & Cost Multiple (L#10/L#37)
    - Unified Portfolio Concurrency (3 normal / 1 Tier-1) & Same-Symbol Lock (1, L#15)
    - Price collars on limit orders (vs mid & mark price), quote & equity freshness
    - Duplicate-order millisecond loop detection & burst limiter

Layer 3: Gateway & Kill-Switch Layer
    - Sliding-window API message-rate throttler (per-second & per-minute)
    - Exchange cancel-on-disconnect (COD) heartbeat watchdog
    - External control-file (`risk_state.txt`) listener & persistent HALT latch sync
    - Split Pod-Shop Drawdown Clocks: Intraday (-3%/-6%) & Rolling (-6%/-12%)
    - Non-desync vs desync HALT tracking for safe native `reduceOnly` exits

Layer 4: Post-Trade Reconciliation Layer
    - Synchronous & asynchronous state-reconciliation loop detecting & resolving phantom
      exchange positions, ghost internal positions, partial-fill qty desyncs, side mismatches,
      and orphan open orders.
"""

from __future__ import annotations

import asyncio
from collections import deque
import datetime
from decimal import Decimal
import logging
import os
import threading
import time
from typing import Any, Callable, Deque, Dict, List, Optional, Protocol, Tuple

from risk_engine.config import RiskConfig
from risk_engine.ledger import RiskLedger
from risk_engine.models import (
    DiscrepancySeverity,
    MarketSnapshot,
    OrderSide,
    OrderType,
    PortfolioState,
    PositionSnapshot,
    ProposedOrder,
    ReconciliationDiscrepancy,
    ReconciliationReport,
    RiskMode,
)

logger = logging.getLogger("risk_engine.layers")


# ==============================================================================
# Layer 1: Signal & Regime Layer
# ==============================================================================

class RegimeLayer:
    """Evaluates volatility regimes, scale-invariant order-book liquidity, conviction, and correlation stress."""

    def __init__(self, config: RiskConfig):
        self.config = config

    def evaluate(
        self,
        order: ProposedOrder,
        portfolio: PortfolioState,
        market: MarketSnapshot,
        risk_mode: RiskMode,
    ) -> Tuple[bool, List[str], Dict[str, Any]]:
        reasons: List[str] = []
        shadow_warnings: List[str] = []
        spread_bps = market.order_book.spread_bps()
        vol_ratio = (
            (market.realized_vol / market.baseline_vol)
            if market.baseline_vol > Decimal("0")
            else Decimal("999")
        )

        active_syms = set(portfolio.positions.keys()) - {order.symbol}
        active_corrs = [
            abs(market.pairwise_correlations[s])
            for s in active_syms
            if s in market.pairwise_correlations
        ]
        max_pair_corr = max(active_corrs) if active_corrs else Decimal("0")
        if market.portfolio_avg_correlation is not None:
            avg_corr = abs(market.portfolio_avg_correlation)
        elif market.pairwise_correlations:
            vals = [abs(v) for v in market.pairwise_correlations.values()]
            avg_corr = sum(vals, Decimal("0")) / Decimal(len(vals))
        else:
            avg_corr = Decimal("0")

        tob_depth = market.order_book.top_of_book_depth_usd or Decimal("0")
        req_depth = max(
            self.config.min_top_of_book_depth_usd,
            order.notional_usd * self.config.min_book_depth_multiple,
        )

        # Stage-2 72h shadow calibration warnings (logged, not hard-blocking until calibrated)
        if spread_bps > self.config.shadow_warn_spread_bps:
            shadow_warnings.append("SHADOW_WARN_SPREAD_ABOVE_CALIBRATION_TARGET")
        if order.take_profit is not None and order.price > Decimal("0"):
            tp_bps = (abs(order.take_profit - order.price) / order.price) * Decimal("10000")
            total_friction_bps = order.round_trip_fee_bps + spread_bps
            if total_friction_bps > Decimal("0") and (tp_bps / total_friction_bps) < self.config.shadow_warn_cost_multiple:
                shadow_warnings.append("SHADOW_WARN_COST_MULTIPLE_BELOW_4X")

        metrics: Dict[str, Any] = {
            "spread_bps": spread_bps,
            "vol_spike_ratio": vol_ratio,
            "correlation_max": max_pair_corr,
            "correlation_avg": avg_corr,
            "top_of_book_depth_usd": tob_depth,
            "required_depth_usd": req_depth,
            "shadow_warnings": shadow_warnings,
        }

        if order.reduce_only:
            return True, reasons, metrics

        # 1a. Conviction Hurdle (tightened under Tier-1 Soft Breach)
        min_conv = (
            self.config.tier1_min_conviction
            if risk_mode == RiskMode.THROTTLED_TIER1
            else self.config.base_min_conviction
        )
        if order.conviction < min_conv:
            code = (
                "TIER1_LOW_CONVICTION_BLOCKED"
                if risk_mode == RiskMode.THROTTLED_TIER1
                else "BELOW_MIN_CONVICTION"
            )
            reasons.append(code)

        # 1b. Volatility Spike Veto
        if market.realized_vol > self.config.max_absolute_vol:
            reasons.append("REGIME_ABSOLUTE_VOLATILITY_SPIKE")
        elif vol_ratio > self.config.max_vol_spike_ratio:
            reasons.append("REGIME_VOLATILITY_SPIKE_RATIO")

        # 1c. Liquidity Evaporation: Bid-Ask Spread & Scale-Invariant Top-of-Book Depth
        max_spread = self.config.max_spread_bps
        if risk_mode == RiskMode.THROTTLED_TIER1:
            max_spread = max_spread * self.config.tier1_spread_tightening_factor
        if spread_bps > max_spread:
            code = (
                "TIER1_SPREAD_TOLERANCE_BREACHED"
                if risk_mode == RiskMode.THROTTLED_TIER1
                else "LIQUIDITY_SPREAD_WIDENING"
            )
            reasons.append(code)

        if tob_depth < req_depth:
            reasons.append("LIQUIDITY_DEPTH_EVAPORATION")

        # 1d. Cross-Asset Correlation Convergence & Pairwise Concentration Shield
        if max_pair_corr >= self.config.max_pairwise_correlation:
            reasons.append("CORRELATION_PAIRWISE_SHIELD")
        if avg_corr >= self.config.max_portfolio_avg_correlation:
            reasons.append("CORRELATION_SYSTEMIC_CONVERGENCE")

        return (len(reasons) == 0), reasons, metrics


# ==============================================================================
# Layer 2: Pre-Trade OMS Layer
# ==============================================================================

class PreTradeOMSLayer:
    """
    Hard electronic pre-trade safety checks:
    - Order, market quote, and portfolio equity freshness & sanity
    - Scale-aware fat-finger single-order notional limit
    - Price collars against mid and mark price
    - Mandatory stop-loss, noise-floor SL (L#16/L#39), max SL ROI (L#25), net friction hurdle (L#10/L#37)
    - Unified portfolio concurrency (3 normal / 1 Tier-1) & same-symbol lock (1, L#15)
    - Duplicate-order millisecond loop detection & burst limiter
    """

    def __init__(self, config: RiskConfig):
        self.config = config
        self._lock = threading.Lock()
        self._recent_fingerprints: Dict[str, int] = {}
        self._order_timestamps_ms: Deque[int] = deque()

    def _now_ms(self, order_ts_ms: Optional[int]) -> int:
        return order_ts_ms if order_ts_ms is not None else int(time.time() * 1000)

    def _fingerprint(self, order: ProposedOrder) -> str:
        return f"{order.symbol}|{order.side.value}|{order.order_type.value}|{order.quantity}|{order.price}|{order.reduce_only}"

    def evaluate(
        self,
        order: ProposedOrder,
        portfolio: PortfolioState,
        market: MarketSnapshot,
        risk_mode: RiskMode = RiskMode.NORMAL,
        now_ms: Optional[int] = None,
    ) -> Tuple[bool, List[str]]:
        reasons: List[str] = []
        eval_ms = now_ms if now_ms is not None else self._now_ms(order.timestamp_ms)

        # 2a. Symbol alignment & positive financial values
        if order.symbol != market.symbol:
            reasons.append("OMS_SYMBOL_MISMATCH")
        if order.quantity <= Decimal("0"):
            reasons.append("OMS_NON_POSITIVE_QUANTITY")
        if order.price <= Decimal("0") or market.mark_price <= Decimal("0"):
            reasons.append("OMS_NON_POSITIVE_PRICE")
        if market.order_book.best_bid <= Decimal("0") or market.order_book.best_ask <= Decimal("0"):
            reasons.append("OMS_INVALID_ORDER_BOOK_QUOTES")
        elif market.order_book.best_ask < market.order_book.best_bid:
            reasons.append("OMS_CROSSED_ORDER_BOOK")

        # 2b. Quote & Mark-to-Market portfolio staleness checks
        if market.timestamp_ms is not None and (eval_ms - market.timestamp_ms) > self.config.max_market_snapshot_age_ms:
            reasons.append("OMS_STALE_MARKET_SNAPSHOT")
        if portfolio.timestamp_ms is not None and (eval_ms - portfolio.timestamp_ms) > self.config.max_portfolio_state_age_ms:
            reasons.append("OMS_STALE_PORTFOLIO_STATE")

        # 2c. Scale-aware fat-finger single-order notional limit
        if order.quantity > Decimal("0") and order.price > Decimal("0") and not order.reduce_only:
            notional = order.quantity * order.price
            fat_finger_cap = self.config.effective_fat_finger_notional_usd(portfolio.equity_usd)
            if notional > fat_finger_cap and self.config.fat_finger_hard_veto:
                reasons.append("OMS_FAT_FINGER_NOTIONAL_VETO")

        # 2d. Price Collar Check (LIMIT orders against both mid price and mark price)
        if order.order_type == OrderType.LIMIT and order.price > Decimal("0"):
            mid = market.order_book.mid_price()
            for label, ref in (("MID", mid), ("MARK", market.mark_price)):
                if ref > Decimal("0"):
                    dev = abs(order.price - ref) / ref
                    if dev > self.config.max_price_collar_pct:
                        reasons.append(f"OMS_PRICE_COLLAR_BREACH_{label}")
                        break

        # 2e. Mandatory Stop-Loss, Bracket Geometry, Noise Floor (L#16/L#39), SL ROI Clamp (L#25), Net Cost Multiple (L#10/L#37)
        if not order.reduce_only:
            if self.config.require_stop_loss_on_entries and order.stop_loss is None:
                reasons.append("OMS_MISSING_STOP_LOSS")

            if order.stop_loss is not None and order.price > Decimal("0"):
                valid_sl_dir = (
                    (order.side == OrderSide.BUY and order.stop_loss < order.price)
                    or (order.side == OrderSide.SELL and order.stop_loss > order.price)
                )
                if not valid_sl_dir:
                    reasons.append("OMS_INVALID_BRACKET_STOP_LOSS")
                else:
                    sl_dist_pct = abs(order.price - order.stop_loss) / order.price
                    # Adaptive Noise Floor: Scalps use dynamic spread-aware floor; macro swings use standard floor
                    if getattr(order, "is_scalp", False):
                        spread_pct = market.order_book.spread_bps() / Decimal("10000")
                        min_sl_floor = max(spread_pct * Decimal("3.0"), getattr(self.config, "scalp_min_stop_distance_pct", Decimal("0.0040")))
                    else:
                        min_sl_floor = self.config.min_stop_distance_pct

                    if sl_dist_pct < min_sl_floor:
                        reasons.append("OMS_STOP_BELOW_NOISE_FLOOR_L16_L39")
                    eff_lev = max(Decimal("1"), order.leverage)
                    if (sl_dist_pct * eff_lev) > self.config.max_sl_roi_pct:
                        reasons.append("OMS_SL_ROI_EXCEEDS_CLAMP_L25")

            if order.take_profit is not None and order.price > Decimal("0"):
                valid_tp_dir = (
                    (order.side == OrderSide.BUY and order.take_profit > order.price)
                    or (order.side == OrderSide.SELL and order.take_profit < order.price)
                )
                if not valid_tp_dir:
                    reasons.append("OMS_INVALID_BRACKET_TAKE_PROFIT")
                else:
                    tp_dist_pct = abs(order.take_profit - order.price) / order.price
                    friction_pct = (order.round_trip_fee_bps + market.order_book.spread_bps()) / Decimal("10000")
                    if friction_pct > Decimal("0") and (tp_dist_pct / friction_pct) < self.config.min_cost_multiple:
                        reasons.append("OMS_NET_COST_MULTIPLE_BELOW_MIN_L10_L37")
                    if order.stop_loss is not None and "OMS_INVALID_BRACKET_STOP_LOSS" not in reasons:
                        sl_dist_pct = abs(order.price - order.stop_loss) / order.price
                        net_reward = tp_dist_pct - friction_pct
                        net_risk = sl_dist_pct + friction_pct
                        required_rr = (
                            getattr(self.config, "scalp_min_rr_ratio", self.config.min_rr_ratio)
                            if getattr(order, "is_scalp", False)
                            else self.config.min_rr_ratio
                        )
                        if net_risk > Decimal("0") and (net_reward / net_risk) < required_rr:
                            reasons.append("OMS_NET_RR_BELOW_MIN_L10")

            # 2f. Unified Portfolio Concurrency & Same-Symbol Lock (L#15 Alpha-Agnostic)
            active_positions = {k: v for k, v in portfolio.positions.items() if v.quantity > Decimal("0")}
            if order.symbol in active_positions and self.config.max_positions_per_symbol <= 1:
                reasons.append("OMS_SAME_SYMBOL_LOCK_L15")

            max_conc = (
                self.config.tier1_max_concurrent_positions
                if risk_mode == RiskMode.THROTTLED_TIER1
                else self.config.max_concurrent_positions
            )
            if len(active_positions) >= max_conc:
                code = (
                    "TIER1_CONCURRENCY_CAP_REACHED"
                    if risk_mode == RiskMode.THROTTLED_TIER1
                    else "OMS_MAX_CONCURRENT_POSITIONS_REACHED"
                )
                reasons.append(code)

        # 2g. Duplicate-Order Loop & Burst Protection (atomic)
        fp = self._fingerprint(order)
        with self._lock:
            burst_cutoff = eval_ms - self.config.burst_window_ms
            while self._order_timestamps_ms and self._order_timestamps_ms[0] <= burst_cutoff:
                self._order_timestamps_ms.popleft()

            last_seen = self._recent_fingerprints.get(fp)
            if last_seen is not None and (eval_ms - last_seen) < self.config.duplicate_order_window_ms:
                reasons.append("OMS_DUPLICATE_ORDER_LOOP_BLOCKED")

            if len(self._order_timestamps_ms) >= self.config.max_orders_per_burst_window:
                reasons.append("OMS_ORDER_BURST_LIMIT_EXCEEDED")

            self._recent_fingerprints[fp] = eval_ms
            self._order_timestamps_ms.append(eval_ms)

            if len(self._recent_fingerprints) > 2048:
                dup_cutoff = eval_ms - (self.config.duplicate_order_window_ms * 4)
                self._recent_fingerprints = {
                    k: ts for k, ts in self._recent_fingerprints.items() if ts >= dup_cutoff
                }

        return (len(reasons) == 0), reasons

    def reset_history(self) -> None:
        with self._lock:
            self._recent_fingerprints.clear()
            self._order_timestamps_ms.clear()


# ==============================================================================
# Layer 3: Gateway & Kill-Switch Layer
# ==============================================================================

class GatewayKillSwitchLayer:
    """
    Gateway-level hard protections:
    - Token-bucket / sliding-window API message-rate throttle
    - Exchange cancel-on-disconnect (COD) heartbeat monitor
    - External control-file (`risk_state.txt`) listener & atomic SQLite HALT persistence
    - Split Pod-Shop Drawdown Clocks: Intraday (-3%/-6%) & Rolling (-6%/-12%)
    """

    VALID_CONTROL_STATES = {
        "ACTIVE",
        "NORMAL",
        "RUN",
        "RUNNING",
        "REDUCE_ONLY",
        "HALT",
        "HALTED",
        "FLATTEN",
        "KILL",
    }

    def __init__(self, config: RiskConfig, ledger: Optional[RiskLedger] = None):
        self.config = config
        self.ledger = ledger
        self._lock = threading.Lock()
        self._msg_ts_1s: Deque[int] = deque()
        self._msg_ts_60s: Deque[int] = deque()
        self._halted_latched: bool = False
        self._halt_reason: Optional[str] = None
        self._is_desync_halt: bool = False
        self._last_heartbeat_ms: Optional[int] = None
        self._cod_armed: bool = False

        # Restore persistent halt latch from cross-process ledger on startup
        if self.ledger is not None:
            h, reason, desync = self.ledger.get_halt_state()
            if h:
                self._halted_latched = True
                self._halt_reason = reason
                self._is_desync_halt = desync

    @property
    def is_halted(self) -> bool:
        if self.ledger is not None:
            h, reason, desync = self.ledger.get_halt_state()
            if h:
                with self._lock:
                    self._halted_latched = True
                    self._halt_reason = reason
                    self._is_desync_halt = desync
                return True
        with self._lock:
            return self._halted_latched

    @property
    def halt_reason(self) -> Optional[str]:
        with self._lock:
            return self._halt_reason

    @property
    def is_desync_halt(self) -> bool:
        if self.ledger is not None:
            _, _, desync = self.ledger.get_halt_state()
            if desync:
                return True
        with self._lock:
            return self._is_desync_halt

    def _persist_control_file_halt(self, token: str) -> None:
        path = self.config.control_file_path
        if not path:
            return
        try:
            parent = os.path.dirname(os.path.abspath(path))
            if parent:
                os.makedirs(parent, exist_ok=True)
            tmp = f"{path}.tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                fh.write(f"{token}\n")
            os.replace(tmp, path)
        except Exception as exc:
            logger.error("Failed persisting halt state to control file %s: %s", path, exc)

    def latch_halt(
        self,
        reason: str,
        is_desync_halt: bool = False,
        persist_control_token: Optional[str] = None,
    ) -> None:
        with self._lock:
            self._halted_latched = True
            self._halt_reason = reason
            self._is_desync_halt = self._is_desync_halt or is_desync_halt
        if self.ledger is not None:
            self.ledger.set_halt_state(True, reason, is_desync_halt=self._is_desync_halt)
        if persist_control_token:
            self._persist_control_file_halt(persist_control_token)

    def manual_reset(self, operator_id: str, reason: str) -> Tuple[bool, str]:
        if not operator_id or not str(operator_id).strip():
            return False, "RESET_REJECTED_MISSING_OPERATOR_ID"
        ext_state, _ = self.read_control_file()
        if ext_state in ("HALT", "HALTED", "FLATTEN", "KILL"):
            return False, f"RESET_BLOCKED_BY_CONTROL_FILE_{ext_state}"
        with self._lock:
            self._halted_latched = False
            self._halt_reason = None
            self._is_desync_halt = False
        if self.ledger is not None:
            self.ledger.set_halt_state(False, None, is_desync_halt=False)
        logger.warning("RiskEngine HALT latch cleared manually by operator=%s reason=%s", operator_id, reason)
        return True, "MANUAL_RESET_COMPLETED"

    def record_heartbeat(self, now_ms: Optional[int] = None) -> None:
        ts = now_ms if now_ms is not None else int(time.time() * 1000)
        with self._lock:
            self._last_heartbeat_ms = ts
            self._cod_armed = True

    def is_connection_healthy(self, now_ms: Optional[int] = None) -> bool:
        with self._lock:
            if not self._cod_armed or self._last_heartbeat_ms is None:
                return True
            ts = now_ms if now_ms is not None else int(time.time() * 1000)
            return (ts - self._last_heartbeat_ms) <= self.config.cancel_on_disconnect_timeout_ms

    def build_cancel_on_disconnect_payload(self, symbol: Optional[str] = None) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "countdownTime": self.config.cancel_on_disconnect_timeout_ms,
        }
        if symbol:
            payload["symbol"] = symbol.strip().upper()
        return payload

    def check_and_consume_rate_limit(self, now_ms: Optional[int] = None) -> Tuple[bool, Optional[str]]:
        ts = now_ms if now_ms is not None else int(time.time() * 1000)
        with self._lock:
            while self._msg_ts_1s and (ts - self._msg_ts_1s[0]) >= 1000:
                self._msg_ts_1s.popleft()
            while self._msg_ts_60s and (ts - self._msg_ts_60s[0]) >= 60000:
                self._msg_ts_60s.popleft()

            if len(self._msg_ts_1s) >= self.config.max_api_messages_per_second:
                return False, "GATEWAY_RATE_LIMIT_PER_SECOND"
            if len(self._msg_ts_60s) >= self.config.max_api_messages_per_minute:
                return False, "GATEWAY_RATE_LIMIT_PER_MINUTE"

            self._msg_ts_1s.append(ts)
            self._msg_ts_60s.append(ts)
            return True, None

    def read_control_file(self) -> Tuple[str, Optional[str]]:
        path = self.config.control_file_path
        if not path or not os.path.exists(path):
            return "ACTIVE", None
        try:
            with open(path, "r", encoding="utf-8") as fh:
                raw = fh.read().strip().upper()
            if not raw:
                return "ACTIVE", None
            token = raw.splitlines()[0].strip().split()[0]
            if token not in self.VALID_CONTROL_STATES:
                return "HALT", f"CORRUPTED_CONTROL_FILE_TOKEN:{token}"
            return token, None
        except Exception as exc:
            return "HALT", f"CONTROL_FILE_READ_ERROR:{exc}"

    def evaluate_risk_mode(
        self,
        portfolio: PortfolioState,
        now_ms: Optional[int] = None,
    ) -> Tuple[RiskMode, List[str], List[str]]:
        reasons: List[str] = []
        actions: List[str] = []

        # 3a. Already latched in HALTED state?
        if self.is_halted:
            reasons.append("KILL_SWITCH_LATCHED_HALTED")
            return RiskMode.HALTED, reasons, ["REQUIRE_MANUAL_RESET"]

        # 3b. External control file check (immediate override)
        ctrl_state, ctrl_err = self.read_control_file()
        if ctrl_err:
            self.latch_halt(ctrl_err, is_desync_halt=True)
            reasons.append("EXTERNAL_CONTROL_FILE_CORRUPTED")
            return RiskMode.HALTED, reasons, ["CANCEL_ALL_ORDERS", "LOCK_HALTED"]

        if ctrl_state in ("FLATTEN", "KILL"):
            self.latch_halt(f"EXTERNAL_CONTROL_FILE_{ctrl_state}", is_desync_halt=False)
            reasons.append(f"EXTERNAL_CONTROL_FILE_{ctrl_state}")
            return (
                RiskMode.HALTED,
                reasons,
                ["CANCEL_ALL_ORDERS", "FLATTEN_ALL_POSITIONS", "LOCK_HALTED"],
            )
        if ctrl_state in ("HALT", "HALTED"):
            self.latch_halt("EXTERNAL_CONTROL_FILE_HALT", is_desync_halt=False)
            reasons.append("EXTERNAL_CONTROL_FILE_HALT")
            return RiskMode.HALTED, reasons, ["CANCEL_ALL_ORDERS", "LOCK_HALTED"]

        # 3c. Cancel-on-disconnect heartbeat watchdog
        if not self.is_connection_healthy(now_ms):
            self.latch_halt("CANCEL_ON_DISCONNECT_HEARTBEAT_TIMEOUT", is_desync_halt=True, persist_control_token="HALT")
            reasons.append("GATEWAY_CANCEL_ON_DISCONNECT_TIMEOUT")
            return RiskMode.HALTED, reasons, ["CANCEL_ALL_ORDERS", "LOCK_HALTED"]

        # 3d. Split Pod-Shop Drawdown Clocks (Intraday -3%/-6% vs Rolling -6%/-12%)
        intra_dd = portfolio.intraday_drawdown_pct()
        roll_dd = portfolio.rolling_drawdown_pct()

        if intra_dd >= self.config.tier2_drawdown_pct:
            self.latch_halt(
                f"TIER2_INTRADAY_DRAWDOWN_BREACH:{intra_dd:.4f}",
                is_desync_halt=False,
                persist_control_token="FLATTEN",
            )
            reasons.append("TIER2_INTRADAY_DRAWDOWN_HARD_BREACH")
            return (
                RiskMode.HALTED,
                reasons,
                ["CANCEL_ALL_ORDERS", "FLATTEN_ALL_POSITIONS", "LOCK_HALTED"],
            )

        if roll_dd >= self.config.tier2_rolling_drawdown_pct:
            self.latch_halt(
                f"TIER2_ROLLING_DRAWDOWN_BREACH:{roll_dd:.4f}",
                is_desync_halt=False,
                persist_control_token="FLATTEN",
            )
            reasons.append("TIER2_ROLLING_DRAWDOWN_HARD_BREACH")
            return (
                RiskMode.HALTED,
                reasons,
                ["CANCEL_ALL_ORDERS", "FLATTEN_ALL_POSITIONS", "LOCK_HALTED"],
            )

        if ctrl_state == "REDUCE_ONLY":
            reasons.append("EXTERNAL_CONTROL_FILE_REDUCE_ONLY")
            return RiskMode.REDUCE_ONLY, reasons, actions

        if intra_dd >= self.config.tier1_drawdown_pct:
            reasons.append("TIER1_INTRADAY_DRAWDOWN_SOFT_BREACH")
            return RiskMode.THROTTLED_TIER1, reasons, actions

        if roll_dd >= self.config.tier1_rolling_drawdown_pct:
            reasons.append("TIER1_ROLLING_DRAWDOWN_SOFT_BREACH")
            return RiskMode.THROTTLED_TIER1, reasons, actions

        return RiskMode.NORMAL, reasons, actions


# ==============================================================================
# Layer 4: Post-Trade Reconciliation Layer
# ==============================================================================

class ExchangeReconciliationAdapter(Protocol):
    def fetch_exchange_positions(self) -> Dict[str, PositionSnapshot]:
        ...

    def fetch_exchange_open_orders(self) -> List[Dict[str, Any]]:
        ...

    def cancel_order(self, symbol: str, order_id: str) -> bool:
        ...

    def flatten_position(self, symbol: str, side: OrderSide, quantity: Decimal) -> bool:
        ...


class StateReconciler:
    """
    Asynchronous & deterministic post-trade state reconciliation engine.
    """

    def __init__(
        self,
        adapter: ExchangeReconciliationAdapter,
        config: RiskConfig,
        on_kill_switch: Optional[Callable[[str], None]] = None,
        on_sync_internal_position: Optional[Callable[[str, Optional[PositionSnapshot]], None]] = None,
    ):
        self.adapter = adapter
        self.config = config
        self.on_kill_switch = on_kill_switch
        self.on_sync_internal_position = on_sync_internal_position
        self._running = False
        self._task: Optional[asyncio.Task[Any]] = None
        self.last_report: Optional[ReconciliationReport] = None

    def reconcile_once(
        self,
        internal_positions: Dict[str, PositionSnapshot],
        internal_open_order_ids: Optional[List[str]] = None,
    ) -> ReconciliationReport:
        now_utc = datetime.datetime.now(datetime.timezone.utc).isoformat()
        discrepancies: List[ReconciliationDiscrepancy] = []
        actions_taken: List[str] = []
        kill_triggered = False

        internal_map = {k.strip().upper(): v for k, v in internal_positions.items() if v.quantity > Decimal("0")}
        known_order_ids = set(str(oid) for oid in (internal_open_order_ids or []))

        try:
            exchange_raw = self.adapter.fetch_exchange_positions()
            exchange_map = {k.strip().upper(): v for k, v in exchange_raw.items() if v.quantity > Decimal("0")}
            exchange_orders = self.adapter.fetch_exchange_open_orders()
        except Exception as exc:
            disc = ReconciliationDiscrepancy(
                discrepancy_type="EXCHANGE_RECONCILE_FETCH_ERROR",
                symbol="ALL",
                severity=DiscrepancySeverity.CRITICAL,
                internal_value=str(list(internal_map.keys())),
                exchange_value=f"ERROR:{exc}",
                action_taken="TRIGGER_KILL_SWITCH",
            )
            discrepancies.append(disc)
            actions_taken.append("TRIGGER_KILL_SWITCH_FETCH_FAILURE")
            if self.on_kill_switch:
                self.on_kill_switch(f"RECONCILE_FETCH_ERROR:{exc}")
            report = ReconciliationReport(
                timestamp_utc=now_utc,
                is_synchronized=False,
                discrepancies=discrepancies,
                kill_switch_triggered=True,
                actions_taken=actions_taken,
            )
            self.last_report = report
            return report

        all_symbols = sorted(set(internal_map.keys()) | set(exchange_map.keys()))

        for sym in all_symbols:
            int_pos = internal_map.get(sym)
            exch_pos = exchange_map.get(sym)

            if exch_pos is not None and int_pos is None:
                action = "ALERT_PHANTOM_POSITION"
                if self.config.auto_flatten_phantom_positions:
                    flattened = False
                    try:
                        flattened = bool(self.adapter.flatten_position(sym, exch_pos.side, exch_pos.quantity))
                    except Exception:
                        flattened = False
                    if flattened:
                        action = "AUTO_FLATTENED_PHANTOM_POSITION"
                        actions_taken.append(f"FLATTEN_PHANTOM:{sym}:{exch_pos.quantity}")
                    else:
                        action = "PHANTOM_FLATTEN_FAILED_KILL_SWITCH"
                        actions_taken.append(f"KILL_SWITCH_PHANTOM_FLATTEN_FAILED:{sym}")
                        kill_triggered = True
                        if self.on_kill_switch:
                            self.on_kill_switch(f"PHANTOM_POSITION_FLATTEN_FAILED:{sym}")
                else:
                    if self.on_sync_internal_position:
                        self.on_sync_internal_position(sym, exch_pos)
                        action = "ADOPTED_EXCHANGE_POSITION"
                        actions_taken.append(f"ADOPT_POSITION:{sym}")

                discrepancies.append(
                    ReconciliationDiscrepancy(
                        discrepancy_type="PHANTOM_EXCHANGE_POSITION",
                        symbol=sym,
                        severity=DiscrepancySeverity.CRITICAL,
                        internal_value="NONE",
                        exchange_value=f"{exch_pos.side.value}:{exch_pos.quantity}",
                        action_taken=action,
                    )
                )
                continue

            if int_pos is not None and exch_pos is None:
                if self.on_sync_internal_position:
                    self.on_sync_internal_position(sym, None)
                actions_taken.append(f"PURGE_GHOST_INTERNAL:{sym}")
                discrepancies.append(
                    ReconciliationDiscrepancy(
                        discrepancy_type="GHOST_INTERNAL_POSITION",
                        symbol=sym,
                        severity=DiscrepancySeverity.WARNING,
                        internal_value=f"{int_pos.side.value}:{int_pos.quantity}",
                        exchange_value="FLAT",
                        action_taken="PURGED_STALE_INTERNAL_STATE",
                    )
                )
                continue

            assert int_pos is not None and exch_pos is not None
            if int_pos.side != exch_pos.side:
                kill_triggered = True
                if self.on_kill_switch:
                    self.on_kill_switch(f"SIDE_MISMATCH:{sym}:INT={int_pos.side.value}:EXCH={exch_pos.side.value}")
                actions_taken.append(f"KILL_SWITCH_SIDE_MISMATCH:{sym}")
                discrepancies.append(
                    ReconciliationDiscrepancy(
                        discrepancy_type="SIDE_MISMATCH",
                        symbol=sym,
                        severity=DiscrepancySeverity.CRITICAL,
                        internal_value=f"{int_pos.side.value}:{int_pos.quantity}",
                        exchange_value=f"{exch_pos.side.value}:{exch_pos.quantity}",
                        action_taken="TRIGGERED_KILL_SWITCH",
                    )
                )
                continue

            qty_diff = abs(int_pos.quantity - exch_pos.quantity)
            denom = max(int_pos.quantity, exch_pos.quantity, Decimal("1e-9"))
            rel_diff = qty_diff / denom
            if rel_diff > self.config.qty_mismatch_tolerance_pct:
                if self.on_sync_internal_position:
                    self.on_sync_internal_position(sym, exch_pos)
                actions_taken.append(f"RESYNC_QTY:{sym}:{int_pos.quantity}->{exch_pos.quantity}")
                discrepancies.append(
                    ReconciliationDiscrepancy(
                        discrepancy_type="QTY_MISMATCH",
                        symbol=sym,
                        severity=DiscrepancySeverity.WARNING,
                        internal_value=str(int_pos.quantity),
                        exchange_value=str(exch_pos.quantity),
                        action_taken="SYNCED_INTERNAL_TO_EXCHANGE_QTY",
                    )
                )

        for ord_info in exchange_orders:
            oid = str(ord_info.get("order_id") or ord_info.get("orderId") or "")
            osym = str(ord_info.get("symbol", "UNKNOWN")).strip().upper()
            if oid and oid not in known_order_ids:
                cancelled = False
                try:
                    cancelled = bool(self.adapter.cancel_order(osym, oid))
                except Exception:
                    cancelled = False
                act = "CANCELLED_ORPHAN_ORDER" if cancelled else "ORPHAN_CANCEL_FAILED"
                actions_taken.append(f"{act}:{osym}:{oid}")
                discrepancies.append(
                    ReconciliationDiscrepancy(
                        discrepancy_type="ORPHAN_OPEN_ORDER",
                        symbol=osym,
                        severity=DiscrepancySeverity.WARNING,
                        internal_value="UNTRACKED",
                        exchange_value=f"ORDER:{oid}",
                        action_taken=act,
                    )
                )

        report = ReconciliationReport(
            timestamp_utc=now_utc,
            is_synchronized=(len(discrepancies) == 0),
            discrepancies=discrepancies,
            kill_switch_triggered=kill_triggered,
            actions_taken=actions_taken,
        )
        self.last_report = report
        return report

    async def run_loop(
        self,
        get_internal_state: Callable[[], Tuple[Dict[str, PositionSnapshot], List[str]]],
        max_iterations: Optional[int] = None,
    ) -> None:
        self._running = True
        iterations = 0
        sleep_s = float(self.config.reconcile_interval_seconds)
        try:
            while self._running:
                positions, open_orders = get_internal_state()
                self.reconcile_once(positions, open_orders)
                iterations += 1
                if max_iterations is not None and iterations >= max_iterations:
                    break
                await asyncio.sleep(sleep_s)
        finally:
            self._running = False

    def stop(self) -> None:
        self._running = False
