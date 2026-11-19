"""
risk_engine/engine.py — Synchronous Institutional Risk Management Gatekeeper (v3 Real-Money Integrity).

Core Mandate:
    Survival and geometric compounding take absolute priority over signal prediction.
    Zero dependency on alpha generation logic. No order may reach an exchange without
    explicit clearance from RiskEngine.evaluate_order().
"""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal, ROUND_HALF_UP
import logging
import time
import uuid
from typing import Any, Callable, Dict, List, Optional

from risk_engine.config import RiskConfig
from risk_engine.layers import (
    GatewayKillSwitchLayer,
    PreTradeOMSLayer,
    RegimeLayer,
)
from risk_engine.ledger import RiskLedger
from risk_engine.models import (
    DecisionStatus,
    MarketSnapshot,
    PortfolioState,
    ProposedOrder,
    RiskDecision,
    RiskMode,
)
from risk_engine.sizing import (
    compute_empirical_cvar,
    compute_fractional_kelly,
    compute_target_quantity,
)
from risk_engine.telemetry import RiskAuditLogger

logger = logging.getLogger("risk_engine.engine")


class RiskEngine:
    """
    Isolated, deterministic, synchronous Risk Management Engine.
    Single entry point: `evaluate_order(proposed_order, portfolio_state, market_snapshot) -> RiskDecision`.
    """

    def __init__(
        self,
        config: Optional[RiskConfig] = None,
        audit_logger: Optional[RiskAuditLogger] = None,
        on_cancel_all_orders: Optional[Callable[[str], Any]] = None,
        on_flatten_all_positions: Optional[Callable[[str], Any]] = None,
        ledger: Optional[RiskLedger] = None,
    ):
        self.config = config or RiskConfig()
        self.ledger = ledger or (RiskLedger(self.config.ledger_db_path) if self.config.ledger_db_path else None)
        self.regime_layer = RegimeLayer(self.config)
        self.oms_layer = PreTradeOMSLayer(self.config)
        self.gateway_layer = GatewayKillSwitchLayer(self.config, ledger=self.ledger)
        self.audit_logger = audit_logger or RiskAuditLogger(
            log_dir=self.config.audit_log_dir,
            log_all_decisions=self.config.log_all_decisions,
        )
        self._on_cancel_all_orders = on_cancel_all_orders
        self._on_flatten_all_positions = on_flatten_all_positions
        self._kill_actions_dispatched: bool = False

    @property
    def is_halted(self) -> bool:
        return self.gateway_layer.is_halted

    @property
    def halt_reason(self) -> Optional[str]:
        return self.gateway_layer.halt_reason

    @property
    def is_desync_halt(self) -> bool:
        return self.gateway_layer.is_desync_halt

    def record_gateway_heartbeat(self, now_ms: Optional[int] = None) -> None:
        self.gateway_layer.record_heartbeat(now_ms)

    def build_cancel_on_disconnect_payload(self, symbol: Optional[str] = None) -> Dict[str, Any]:
        return self.gateway_layer.build_cancel_on_disconnect_payload(symbol)

    def release_slot_reservation(self, reservation_id: Optional[str]) -> None:
        if self.ledger is not None and reservation_id:
            self.ledger.release_slot(reservation_id)

    def trigger_kill_switch(
        self,
        reason: str,
        flatten_positions: bool = True,
        is_desync_halt: Optional[bool] = None,
    ) -> RiskDecision:
        """
        Programmatically engage KILL_SWITCH: cancel all resting orders, optionally flatten
        active positions, and lock the engine into HALTED state requiring manual reset.
        """
        inferred_desync = (
            is_desync_halt
            if is_desync_halt is not None
            else any(tag in reason.upper() for tag in ("SIDE_MISMATCH", "RECONCILE_FETCH_ERROR", "DESYNC", "CORRUPT"))
        )
        self.gateway_layer.latch_halt(
            reason,
            is_desync_halt=inferred_desync,
            persist_control_token="FLATTEN" if flatten_positions else "HALT",
        )
        actions = ["CANCEL_ALL_ORDERS", "LOCK_HALTED"]
        if flatten_positions:
            actions.insert(1, "FLATTEN_ALL_POSITIONS")

        self._execute_kill_callbacks(reason, flatten=flatten_positions)

        decision = RiskDecision(
            status=DecisionStatus.KILL_SWITCH,
            approved_qty=Decimal("0"),
            reason_codes=[f"MANUAL_OR_EXTERNAL_KILL_SWITCH:{reason}"],
            metrics_snapshot={
                "kill_reason": reason,
                "is_desync_halt": inferred_desync,
                "risk_mode": RiskMode.HALTED.value,
            },
            risk_mode=RiskMode.HALTED,
            actions_required=actions,
        )
        self.audit_logger.log_decision(decision)
        return decision

    def manual_reset(self, operator_id: str, reason: str) -> bool:
        ok, msg = self.gateway_layer.manual_reset(operator_id, reason)
        if ok:
            self._kill_actions_dispatched = False
            self.oms_layer.reset_history()
        else:
            logger.warning("RiskEngine manual_reset refused: %s", msg)
        return ok

    def _execute_kill_callbacks(self, reason: str, flatten: bool) -> None:
        if self._kill_actions_dispatched:
            return
        self._kill_actions_dispatched = True
        if self._on_cancel_all_orders:
            try:
                self._on_cancel_all_orders(reason)
            except Exception as exc:
                logger.error("Kill-switch cancel_all callback failed: %s", exc)
        if flatten and self._on_flatten_all_positions:
            try:
                self._on_flatten_all_positions(reason)
            except Exception as exc:
                logger.error("Kill-switch flatten_all callback failed: %s", exc)

    def _base_metrics(
        self,
        order: ProposedOrder,
        portfolio: PortfolioState,
        market: MarketSnapshot,
        risk_mode: RiskMode,
    ) -> Dict[str, Any]:
        win_rate = order.win_rate if order.win_rate is not None else self.config.default_win_rate
        payoff = order.payoff_ratio if order.payoff_ratio is not None else self.config.default_payoff_ratio
        is_gross = True if (order.win_rate is None or order.payoff_ratio is None) else order.is_gross_edge_estimate
        _, frac_kelly = compute_fractional_kelly(win_rate, payoff, self.config, is_gross_estimate=is_gross)
        emp_cvar = compute_empirical_cvar(
            returns_series=market.asset_returns_series,
            confidence_level=self.config.cvar_confidence_level,
            fallback_vol=max(market.realized_vol, market.atr_pct or Decimal("0")),
            fat_tail_multiplier=self.config.cvar_fat_tail_multiplier,
            min_samples=self.config.cvar_min_samples,
        )
        eff_dd = portfolio.effective_drawdown_pct()
        sym_exp_pct = (
            portfolio.symbol_exposure_usd(order.symbol) / portfolio.equity_usd
            if portfolio.equity_usd > Decimal("0")
            else Decimal("999")
        )
        return {
            "symbol": order.symbol,
            "side": order.side.value,
            "order_type": order.order_type.value,
            "proposed_qty": order.quantity,
            "order_notional_usd": order.notional_usd,
            "equity_usd": portfolio.equity_usd,
            "drawdown_pct": eff_dd.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP),
            "rolling_drawdown_pct": portfolio.rolling_drawdown_pct().quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP),
            "intraday_drawdown_pct": portfolio.intraday_drawdown_pct().quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP),
            "realized_vol": market.realized_vol,
            "kelly_fraction": frac_kelly.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP),
            "spread_bps": market.order_book.spread_bps().quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
            "empirical_cvar_pct": emp_cvar.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP),
            "gross_leverage": portfolio.gross_leverage().quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP),
            "net_leverage": portfolio.net_leverage().quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP),
            "single_asset_exposure_pct": sym_exp_pct.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP),
            "open_stop_risk_usd": portfolio.total_open_stop_risk_usd().quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP),
            "risk_mode": risk_mode.value,
        }

    def _finalize(self, decision: RiskDecision) -> RiskDecision:
        self.audit_logger.log_decision(decision)
        return decision

    def evaluate_order(
        self,
        proposed_order: ProposedOrder,
        portfolio_state: PortfolioState,
        market_snapshot: MarketSnapshot,
        now_ms: Optional[int] = None,
    ) -> RiskDecision:
        """
        Single deterministic synchronous gatekeeper entry point.
        Fail-closed: any malformed input or internal exception returns VETOED (qty=0).
        """
        try:
            return self._evaluate_order_impl(
                proposed_order, portfolio_state, market_snapshot, now_ms
            )
        except Exception as exc:
            logger.exception("RiskEngine fail-closed on unexpected error: %s", exc)
            decision = RiskDecision(
                status=DecisionStatus.VETOED,
                approved_qty=Decimal("0"),
                reason_codes=["RISK_ENGINE_FAIL_CLOSED_ERROR"],
                metrics_snapshot={"error": str(exc), "risk_mode": RiskMode.HALTED.value},
                risk_mode=RiskMode.HALTED if self.is_halted else RiskMode.NORMAL,
            )
            return self._finalize(decision)

    def _evaluate_order_impl(
        self,
        proposed_order: ProposedOrder,
        portfolio_state: PortfolioState,
        market_snapshot: MarketSnapshot,
        now_ms: Optional[int],
    ) -> RiskDecision:
        if not isinstance(proposed_order, ProposedOrder):
            raise TypeError("proposed_order must be a ProposedOrder instance")
        if not isinstance(portfolio_state, PortfolioState):
            raise TypeError("portfolio_state must be a PortfolioState instance")
        if not isinstance(market_snapshot, MarketSnapshot):
            raise TypeError("market_snapshot must be a MarketSnapshot instance")

        eval_ms = (
            now_ms
            if now_ms is not None
            else (proposed_order.timestamp_ms if proposed_order.timestamp_ms is not None else int(time.time() * 1000))
        )

        # 0. Non-positive equity -> immediate KILL_SWITCH
        if portfolio_state.equity_usd <= Decimal("0"):
            self.gateway_layer.latch_halt("PORTFOLIO_EQUITY_DEPLETED", is_desync_halt=False, persist_control_token="FLATTEN")
            self._execute_kill_callbacks("PORTFOLIO_EQUITY_DEPLETED", flatten=True)
            metrics = self._base_metrics(proposed_order, portfolio_state, market_snapshot, RiskMode.HALTED)
            return self._finalize(
                RiskDecision(
                    status=DecisionStatus.KILL_SWITCH,
                    approved_qty=Decimal("0"),
                    reason_codes=["PORTFOLIO_EQUITY_DEPLETED"],
                    metrics_snapshot=metrics,
                    risk_mode=RiskMode.HALTED,
                    actions_required=["CANCEL_ALL_ORDERS", "FLATTEN_ALL_POSITIONS", "LOCK_HALTED"],
                )
            )

        # 0b. Sync Mark-to-Market equity watermarks across restarts if ledger is enabled
        if self.ledger is not None:
            persisted_peak, persisted_intra = self.ledger.sync_watermarks(portfolio_state.equity_usd, now_ms=eval_ms)
            eff_peak = max(portfolio_state.peak_equity_usd, persisted_peak)
            eff_intra = max(portfolio_state.intraday_start_equity_usd, persisted_intra)
            portfolio_state = replace(
                portfolio_state,
                peak_equity_usd=eff_peak,
                intraday_start_equity_usd=eff_intra,
            )

        # 1. Layer 3: Kill-Switch, External Control File, COD Heartbeat, & Split Drawdown Clocks
        risk_mode, mode_reasons, mode_actions = self.gateway_layer.evaluate_risk_mode(
            portfolio_state, now_ms=eval_ms
        )
        metrics = self._base_metrics(proposed_order, portfolio_state, market_snapshot, risk_mode)

        if risk_mode == RiskMode.HALTED:
            should_flatten = "FLATTEN_ALL_POSITIONS" in mode_actions
            if mode_actions and ("CANCEL_ALL_ORDERS" in mode_actions or should_flatten):
                self._execute_kill_callbacks("|".join(mode_reasons), flatten=should_flatten)

            # Safe HALTED Exit Gate (v3):
            # Permit reduce_only exits ONLY if:
            #  (a) config allows it,
            #  (b) halt is NOT a state-desync halt (SIDE_MISMATCH / RECONCILE_FETCH_ERROR / CORRUPTED),
            #  (c) wire protocol enforces native exchange-side `reduceOnly="true"`.
            safe_reduce_exit = (
                self.config.allow_reduce_only_in_non_desync_halt
                and proposed_order.reduce_only
                and proposed_order.exchange_enforces_reduce_only
                and (not self.gateway_layer.is_desync_halt)
            )
            if not safe_reduce_exit:
                extra = ["HALTED_REDUCE_ONLY_BLOCKED_DESYNC_OR_UNPROTECTED"] if proposed_order.reduce_only else []
                return self._finalize(
                    RiskDecision(
                        status=DecisionStatus.KILL_SWITCH,
                        approved_qty=Decimal("0"),
                        reason_codes=mode_reasons + extra,
                        metrics_snapshot=metrics,
                        risk_mode=RiskMode.HALTED,
                        actions_required=mode_actions,
                    )
                )
            # Fall through to rate-limit + OMS + reduce-only sizing ONLY for safe protective exit
            mode_reasons = mode_reasons + ["SAFE_REDUCE_ONLY_EXIT_IN_NON_DESYNC_HALT"]

        if risk_mode == RiskMode.REDUCE_ONLY and not proposed_order.reduce_only:
            return self._finalize(
                RiskDecision(
                    status=DecisionStatus.VETOED,
                    approved_qty=Decimal("0"),
                    reason_codes=mode_reasons + ["NEW_ENTRY_BLOCKED_IN_REDUCE_ONLY_MODE"],
                    metrics_snapshot=metrics,
                    risk_mode=risk_mode,
                )
            )

        # 2. Layer 3: API Message-Rate Throttle
        rate_ok, rate_reason = self.gateway_layer.check_and_consume_rate_limit(eval_ms)
        if not rate_ok:
            return self._finalize(
                RiskDecision(
                    status=DecisionStatus.VETOED,
                    approved_qty=Decimal("0"),
                    reason_codes=[rate_reason or "GATEWAY_RATE_LIMIT_EXCEEDED"],
                    metrics_snapshot=metrics,
                    risk_mode=risk_mode,
                )
            )

        # 3. Layer 2: Pre-Trade OMS Defense
        oms_ok, oms_reasons = self.oms_layer.evaluate(
            proposed_order, portfolio_state, market_snapshot, risk_mode=risk_mode, now_ms=eval_ms
        )
        if not oms_ok:
            return self._finalize(
                RiskDecision(
                    status=DecisionStatus.VETOED,
                    approved_qty=Decimal("0"),
                    reason_codes=oms_reasons,
                    metrics_snapshot=metrics,
                    risk_mode=risk_mode,
                )
            )

        # 4. Layer 1: Signal & Regime Defense
        regime_ok, regime_reasons, regime_metrics = self.regime_layer.evaluate(
            proposed_order, portfolio_state, market_snapshot, risk_mode
        )
        metrics.update(regime_metrics)
        if not regime_ok:
            return self._finalize(
                RiskDecision(
                    status=DecisionStatus.VETOED,
                    approved_qty=Decimal("0"),
                    reason_codes=mode_reasons + regime_reasons,
                    metrics_snapshot=metrics,
                    risk_mode=risk_mode,
                )
            )

        # 5. Quantitative Sizing & Tail-Risk Governance
        sizing = compute_target_quantity(
            proposed_order=proposed_order,
            portfolio_state=portfolio_state,
            market_snapshot=market_snapshot,
            config=self.config,
            risk_mode=risk_mode,
        )
        metrics.update(
            {
                "raw_kelly": sizing.raw_kelly.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP),
                "kelly_fraction": sizing.fractional_kelly.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP),
                "vol_scalar": sizing.vol_scalar.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP),
                "empirical_cvar_pct": sizing.empirical_cvar_pct.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP),
                "portfolio_cvar_pct": sizing.portfolio_cvar_pct.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP),
                "book_impact_pct": sizing.book_impact_pct.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP),
                "approved_notional_usd": sizing.max_notional_usd,
                "trade_stop_risk_usd": sizing.trade_stop_risk_usd,
                "projected_portfolio_stop_risk_usd": sizing.portfolio_open_stop_risk_usd,
            }
        )

        if sizing.vetoed or sizing.approved_qty <= Decimal("0"):
            return self._finalize(
                RiskDecision(
                    status=DecisionStatus.VETOED,
                    approved_qty=Decimal("0"),
                    reason_codes=mode_reasons + sizing.reason_codes,
                    metrics_snapshot=metrics,
                    risk_mode=risk_mode,
                )
            )

        # 6. Cross-Process Atomic Slot Reservation (prevents Macro + Tiger TOCTOU races!)
        if self.ledger is not None and not proposed_order.reduce_only:
            max_conc = (
                self.config.tier1_max_concurrent_positions
                if risk_mode == RiskMode.THROTTLED_TIER1
                else self.config.max_concurrent_positions
            )
            res_id = proposed_order.client_order_id or f"RES_{proposed_order.symbol}_{uuid.uuid4().hex[:10]}"
            active_syms = [k for k, v in portfolio_state.positions.items() if v.quantity > Decimal("0")]
            reserved, res_err = self.ledger.try_reserve_slot(
                reservation_id=res_id,
                symbol=proposed_order.symbol,
                side=proposed_order.side.value,
                notional_usd=sizing.max_notional_usd,
                stop_risk_usd=sizing.trade_stop_risk_usd,
                active_exchange_symbols=active_syms,
                max_concurrent_positions=max_conc,
                max_positions_per_symbol=self.config.max_positions_per_symbol,
                ttl_ms=self.config.slot_reservation_ttl_ms,
                now_ms=eval_ms,
            )
            if not reserved:
                return self._finalize(
                    RiskDecision(
                        status=DecisionStatus.VETOED,
                        approved_qty=Decimal("0"),
                        reason_codes=mode_reasons + [res_err or "LEDGER_SLOT_RESERVATION_FAILED"],
                        metrics_snapshot=metrics,
                        risk_mode=risk_mode,
                    )
                )
            metrics["reservation_id"] = res_id

        if sizing.was_resized:
            return self._finalize(
                RiskDecision(
                    status=DecisionStatus.RESIZED,
                    approved_qty=sizing.approved_qty,
                    reason_codes=mode_reasons + sizing.reason_codes,
                    metrics_snapshot=metrics,
                    risk_mode=risk_mode,
                )
            )

        return self._finalize(
            RiskDecision(
                status=DecisionStatus.APPROVED,
                approved_qty=sizing.approved_qty,
                reason_codes=mode_reasons + ["ALL_RISK_GATES_PASSED"],
                metrics_snapshot=metrics,
                risk_mode=risk_mode,
            )
        )
