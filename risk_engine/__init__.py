"""
risk_engine — Holistic, Decoupled Institutional Risk Management Engine (v3 Real-Money Integrity).

Zero dependency on alpha generation logic. Exposes a single deterministic
synchronous gatekeeper: RiskEngine.evaluate_order(proposed_order, portfolio_state, market_snapshot).
"""

from risk_engine.adapter import (
    BinanceExecutorReconciliationAdapter,
    RiskGatedGateway,
    build_market_snapshot_from_orderbook,
    build_portfolio_state_from_summary,
    ticket_to_proposed_order,
)
from risk_engine.config import DEFAULT_CONFIG_PATH, RiskConfig
from risk_engine.engine import RiskEngine
from risk_engine.layers import (
    ExchangeReconciliationAdapter,
    GatewayKillSwitchLayer,
    PreTradeOMSLayer,
    RegimeLayer,
    StateReconciler,
)
from risk_engine.ledger import RiskLedger
from risk_engine.lesson_alignment import (
    LESSON_REGISTRY,
    AlignmentIssue,
    LessonAlignmentReport,
    LessonBinding,
    LessonTier,
    audit_lesson_alignment,
)
from risk_engine.models import (
    DecisionStatus,
    DiscrepancySeverity,
    MarketSnapshot,
    OrderBookSnapshot,
    OrderSide,
    OrderType,
    PortfolioState,
    PositionSnapshot,
    ProposedOrder,
    ReconciliationDiscrepancy,
    ReconciliationReport,
    RiskDecision,
    RiskMode,
)
from risk_engine.sizing import (
    SizingResult,
    compute_empirical_cvar,
    compute_fractional_kelly,
    compute_target_quantity,
    compute_volatility_scalar,
)
from risk_engine.telemetry import RiskAuditLogger

__all__ = [
    "DEFAULT_CONFIG_PATH",
    "RiskConfig",
    "RiskEngine",
    "RiskLedger",
    "RiskGatedGateway",
    "BinanceExecutorReconciliationAdapter",
    "build_market_snapshot_from_orderbook",
    "build_portfolio_state_from_summary",
    "ticket_to_proposed_order",
    "ExchangeReconciliationAdapter",
    "GatewayKillSwitchLayer",
    "PreTradeOMSLayer",
    "RegimeLayer",
    "StateReconciler",
    "LESSON_REGISTRY",
    "AlignmentIssue",
    "LessonAlignmentReport",
    "LessonBinding",
    "LessonTier",
    "audit_lesson_alignment",
    "DecisionStatus",
    "DiscrepancySeverity",
    "MarketSnapshot",
    "OrderBookSnapshot",
    "OrderSide",
    "OrderType",
    "PortfolioState",
    "PositionSnapshot",
    "ProposedOrder",
    "ReconciliationDiscrepancy",
    "ReconciliationReport",
    "RiskDecision",
    "RiskMode",
    "SizingResult",
    "compute_empirical_cvar",
    "compute_fractional_kelly",
    "compute_target_quantity",
    "compute_volatility_scalar",
    "RiskAuditLogger",
]
