# ==============================================================================
# Kronos Quantitative Architecture — Capital Recycler & Active Trade Overseer
# File: src/quant/capital_recycler.py
# Tag: QUANT-OVERSEER | SENTINEL-ARBITER | CAPITAL-RECYCLER
#
# INVARIANTS:
# 1. Zero Float Financial Math (AGENTS.md Invariant #1): All prices, notional,
#    PnL, percentages, and fees use decimal.Decimal.
# 2. Zero Orphan Guarantee: When exiting an active position, all associated
#    resting conditional orders (TP/SL) must be atomically cancelled.
# 3. Post-Exit Quarantine Enforcement (Lesson #22): Closed symbols are
#    automatically quarantined to prevent instant churn.
# 4. Asymmetric Loss Mitigation (Lesson #37): Moving on from dead trades at
#    small taker fee (-0.05%) dominates holding decaying positions into full
#    stop-loss (-1.5% to -5.5%).
# ==============================================================================

import os
import sqlite3
import datetime
import logging
from enum import Enum
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional, List, Dict, Any, Callable, Set
from dataclasses import dataclass, field

logger = logging.getLogger("Kronos.CapitalRecycler")
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter(
        "[%(asctime)s UTC] [%(levelname)s] [CapitalRecycler] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


class RecyclerDecision(str, Enum):
    """Decision emitted by the Capital Recycler for an active position."""
    MAINTAIN = "MAINTAIN"
    RATCHET_PROTECT = "RATCHET_PROTECT"
    MOVE_ON_STALL = "MOVE_ON_STALL"
    MOVE_ON_CVD_INVERSION = "MOVE_ON_CVD_INVERSION"
    MOVE_ON_BETA_WEAKNESS = "MOVE_ON_BETA_WEAKNESS"
    MOVE_ON_DISPLACEMENT = "MOVE_ON_DISPLACEMENT"
    EMERGENCY_KILL = "EMERGENCY_KILL"


@dataclass
class RecyclerConfig:
    """Operational parameters and guardrails for Capital Recycler."""
    # Minimum observation buffer (prevents jittery exits on entry candle noise)
    min_observation_minutes_scalp: Decimal = Decimal("3.0")
    min_observation_minutes_macro: Decimal = Decimal("15.0")

    # Maximum stagnation duration (minutes without follow-through before triggering move-on)
    max_stall_minutes_scalp: Decimal = Decimal("8.0")    # Sweetspot: 8 minutes (down from 12m)
    max_stall_minutes_macro: Decimal = Decimal("90.0")   # Sweetspot: 90 minutes / 1.5h (down from 180m / 3h)

    # Dead band bounds around entry (+/- percentage of price where trade is dead/stalled)
    dead_band_pct: Decimal = Decimal("0.0025")           # +/- 0.25%

    # Minimum required follow-through MFE to prove alpha is alive
    min_follow_through_mfe_scalp: Decimal = Decimal("0.0020")  # +0.20%
    min_follow_through_mfe_macro: Decimal = Decimal("0.0050")  # +0.50%

    # Maximum Favorable Excursion required to permit ratchet to breakeven + buffer
    mfe_ratchet_trigger_scalp: Decimal = Decimal("0.0060")     # +0.60%
    mfe_ratchet_trigger_macro: Decimal = Decimal("0.0120")     # +1.20%

    # Plateau duration (minutes of sideways chop after peak MFE before triggering ratchet)
    plateau_ratchet_minutes_scalp: Decimal = Decimal("4.0")   # Sweetspot: 4 minutes
    plateau_ratchet_minutes_macro: Decimal = Decimal("30.0")  # Sweetspot: 30 minutes

    # Breakeven fee buffer (protects against taker exit fee 0.05% + roundtrip friction)
    breakeven_fee_buffer_pct: Decimal = Decimal("0.0012")      # +0.12% above entry for LONG

    # Orderflow CVD inversion z-score threshold (Lesson #32)
    cvd_inversion_zscore_threshold: Decimal = Decimal("2.0")

    # Beta divergence threshold (Lesson #28 & #38: asset lagging BTC trend)
    beta_divergence_threshold_pct: Decimal = Decimal("0.0080") # 0.80% lag vs BTC

    # Post-Exit Quarantine window (Lesson #22)
    quarantine_duration_minutes: int = 15

    # Binance taker fee rate (used for net EV comparison)
    taker_fee_pct: Decimal = Decimal("0.0005")                 # 0.05%

    # SQLite autopsy database storage path
    database_path: str = "data/trade_autopsies.db"


@dataclass
class NormalizedPosition:
    """Standardized position representation agnostic to Strategy #1 or Strategy #3."""
    position_id: str
    symbol: str
    side: str                          # "BUY" or "SELL"
    entry_price: Decimal
    stop_loss: Decimal
    take_profit: Decimal
    quantity: Decimal
    entry_time_utc: datetime.datetime
    strategy_tag: str                  # "STRATEGY_1_MACRO" or "STRATEGY_3_TIGER"
    notional_usd: Decimal = Decimal("100.00")
    highest_favorable_price: Optional[Decimal] = None
    lowest_adverse_price: Optional[Decimal] = None
    is_breakeven_ratcheted: bool = False
    last_peak_time_utc: Optional[datetime.datetime] = None


@dataclass(frozen=True)
class TradeHealthEvaluation:
    """Comprehensive diagnostic verdict emitted by CapitalRecycler."""
    symbol: str
    position_id: str
    decision: RecyclerDecision
    health_score: Decimal              # 0.00 to 100.00
    current_pnl_pct: Decimal
    mfe_pct: Decimal                   # Maximum Favorable Excursion
    mae_pct: Decimal                   # Maximum Adverse Excursion
    elapsed_minutes: Decimal
    plateau_minutes: Decimal
    action_reason: str
    should_exit: bool
    should_ratchet: bool
    recommended_new_sl: Optional[Decimal] = None
    displaced_by_candidate: Optional[str] = None


@dataclass
class RecyclerExecutionReceipt:
    """Execution receipt documenting atomic position resolution."""
    success: bool
    position_id: str
    symbol: str
    action_taken: str
    exit_price: Optional[Decimal] = None
    net_pnl_pct: Optional[Decimal] = None
    quarantine_expires_utc: Optional[datetime.datetime] = None
    liberated_slot: bool = False
    error_message: Optional[str] = None


class CapitalRecycler:
    """
    Autonomous Active Position Overseer & Capital Recycler.
    
    Monitors live committed positions in real time. Evaluates whether the underlying
    predictive edge has expired or stalled. When an active trade is determined to be
    dead money, the Recycler executes an atomic market close, cancels all resting
    conditional brackets (zero-orphan guarantee), quarantines the asset, and liberates
    the portfolio slot so fresh high-momentum candidates can be deployed.
    """

    def __init__(self, config: Optional[RecyclerConfig] = None):
        self.config = config or RecyclerConfig()
        self.quarantine_registry: Dict[str, Dict[str, Any]] = {}
        self._init_database()

    def _init_database(self) -> None:
        """Initializes the SQLite trade autopsy database and schema."""
        db_dir = os.path.dirname(self.config.database_path)
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir, exist_ok=True)

        try:
            with sqlite3.connect(self.config.database_path) as conn:
                conn.execute("PRAGMA journal_mode=WAL;")
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS sentinel_autopsies (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp_utc TEXT NOT NULL,
                        position_id TEXT NOT NULL,
                        symbol TEXT NOT NULL,
                        side TEXT NOT NULL,
                        strategy_tag TEXT NOT NULL,
                        entry_price REAL NOT NULL,
                        exit_price REAL NOT NULL,
                        pnl_pct REAL NOT NULL,
                        mfe_pct REAL NOT NULL,
                        mae_pct REAL NOT NULL,
                        elapsed_minutes REAL NOT NULL,
                        decision TEXT NOT NULL,
                        action_reason TEXT NOT NULL,
                        health_score REAL NOT NULL,
                        displaced_by_candidate TEXT
                    )
                """)
                conn.commit()
        except Exception as e:
            logger.error("Failed to initialize autopsy database: %s", e)

    @staticmethod
    def normalize_position(raw_pos: Any) -> NormalizedPosition:
        """Adapts heterogeneous position structures to NormalizedPosition."""
        if isinstance(raw_pos, NormalizedPosition):
            return raw_pos

        # Check for Strategy #3 ActiveTigerPosition
        if hasattr(raw_pos, "is_slow_regime"):
            return NormalizedPosition(
                position_id=getattr(raw_pos, "position_id"),
                symbol=getattr(raw_pos, "symbol"),
                side=getattr(raw_pos, "side"),
                entry_price=Decimal(str(getattr(raw_pos, "entry_price"))),
                stop_loss=Decimal(str(getattr(raw_pos, "stop_loss"))),
                take_profit=Decimal(str(getattr(raw_pos, "take_profit"))),
                quantity=Decimal(str(getattr(raw_pos, "quantity"))),
                entry_time_utc=getattr(raw_pos, "entry_time_utc"),
                strategy_tag="STRATEGY_3_TIGER",
                notional_usd=Decimal(str(getattr(raw_pos, "notional_usd", "100.0"))),
                highest_favorable_price=getattr(raw_pos, "highest_favorable_price", None),
                lowest_adverse_price=getattr(raw_pos, "lowest_adverse_price", None),
                is_breakeven_ratcheted=getattr(raw_pos, "is_breakeven_ratcheted", False)
            )

        # Check for Strategy #1 ActiveBracketPosition
        if hasattr(raw_pos, "entry_order_id"):
            entry_t = getattr(raw_pos, "entry_fill_time_utc", None)
            if entry_t is None:
                entry_t = datetime.datetime.now(datetime.timezone.utc)
            return NormalizedPosition(
                position_id=getattr(raw_pos, "position_id"),
                symbol=getattr(raw_pos, "symbol"),
                side=getattr(raw_pos, "side"),
                entry_price=Decimal(str(getattr(raw_pos, "entry_price"))),
                stop_loss=Decimal(str(getattr(raw_pos, "stop_loss"))),
                take_profit=Decimal(str(getattr(raw_pos, "take_profit"))),
                quantity=Decimal(str(getattr(raw_pos, "quantity"))),
                entry_time_utc=entry_t,
                strategy_tag="STRATEGY_1_MACRO",
                notional_usd=getattr(raw_pos, "quantity", Decimal("1")) * Decimal(str(getattr(raw_pos, "entry_price"))),
                is_breakeven_ratcheted=getattr(raw_pos, "is_breakeven_ratcheted", False)
            )

        # Check for dictionary representation
        if isinstance(raw_pos, dict):
            entry_t_raw = raw_pos.get("entry_time_utc") or raw_pos.get("entry_fill_time_utc")
            if isinstance(entry_t_raw, str):
                entry_t = datetime.datetime.fromisoformat(entry_t_raw)
            elif isinstance(entry_t_raw, datetime.datetime):
                entry_t = entry_t_raw
            else:
                entry_t = datetime.datetime.now(datetime.timezone.utc)

            return NormalizedPosition(
                position_id=str(raw_pos.get("position_id", "UNKNOWN")),
                symbol=str(raw_pos.get("symbol", "UNKNOWN")),
                side=str(raw_pos.get("side", "BUY")),
                entry_price=Decimal(str(raw_pos.get("entry_price", "0.0"))),
                stop_loss=Decimal(str(raw_pos.get("stop_loss", "0.0"))),
                take_profit=Decimal(str(raw_pos.get("take_profit", "0.0"))),
                quantity=Decimal(str(raw_pos.get("quantity", "0.0"))),
                entry_time_utc=entry_t,
                strategy_tag=str(raw_pos.get("strategy_tag", "STRATEGY_3_TIGER")),
                notional_usd=Decimal(str(raw_pos.get("notional_usd", "100.0"))),
                is_breakeven_ratcheted=bool(raw_pos.get("is_breakeven_ratcheted", False))
            )

        raise ValueError(f"Unsupported position structure: {type(raw_pos)}")

    def evaluate(
        self,
        raw_position: Any,
        current_price: Decimal,
        current_time_utc: datetime.datetime,
        btc_price_change_pct: Optional[Decimal] = None,
        cvd_zscore: Optional[Decimal] = None,
        ofi_imbalance: Optional[Decimal] = None,
        scanner_candidates: Optional[List[Any]] = None,
        is_tsunami_shock: bool = False
    ) -> TradeHealthEvaluation:
        """
        Conducts a comprehensive multi-factor audit of an active position.
        
        Returns a TradeHealthEvaluation containing the diagnosis, health score,
        and atomic action recommendation.
        """
        pos = self.normalize_position(raw_position)
        is_scalp = (pos.strategy_tag == "STRATEGY_3_TIGER")

        # 1. Temporal Tracking
        elapsed_delta = current_time_utc - pos.entry_time_utc
        elapsed_minutes = Decimal(str(max(0.0, elapsed_delta.total_seconds() / 60.0)))

        # 2. Price Return Calculation
        if pos.entry_price > Decimal("0"):
            if pos.side == "BUY":
                pnl_pct = (current_price - pos.entry_price) / pos.entry_price
            else:
                pnl_pct = (pos.entry_price - current_price) / pos.entry_price
        else:
            pnl_pct = Decimal("0.0")

        # 3. Peak Excursion Updates
        highest_fav = pos.highest_favorable_price or current_price
        lowest_adv = pos.lowest_adverse_price or current_price

        if pos.side == "BUY":
            if current_price > highest_fav:
                highest_fav = current_price
                pos.last_peak_time_utc = current_time_utc
            if current_price < lowest_adv:
                lowest_adv = current_price
            mfe_pct = (highest_fav - pos.entry_price) / pos.entry_price if pos.entry_price > 0 else Decimal("0")
            mae_pct = (pos.entry_price - lowest_adv) / pos.entry_price if pos.entry_price > 0 else Decimal("0")
        else:
            if current_price < highest_fav:
                highest_fav = current_price
                pos.last_peak_time_utc = current_time_utc
            if current_price > lowest_adv:
                lowest_adv = current_price
            mfe_pct = (pos.entry_price - highest_fav) / pos.entry_price if pos.entry_price > 0 else Decimal("0")
            mae_pct = (lowest_adv - pos.entry_price) / pos.entry_price if pos.entry_price > 0 else Decimal("0")

        pos.highest_favorable_price = highest_fav
        pos.lowest_adverse_price = lowest_adv

        # Plateau minutes since highest favorable excursion
        peak_t = pos.last_peak_time_utc or pos.entry_time_utc
        plateau_delta = current_time_utc - peak_t
        plateau_minutes = Decimal(str(max(0.0, plateau_delta.total_seconds() / 60.0)))

        # Operational Bounds based on strategy horizon
        min_obs = self.config.min_observation_minutes_scalp if is_scalp else self.config.min_observation_minutes_macro
        max_stall = self.config.max_stall_minutes_scalp if is_scalp else self.config.max_stall_minutes_macro
        min_follow_mfe = self.config.min_follow_through_mfe_scalp if is_scalp else self.config.min_follow_through_mfe_macro
        mfe_ratchet_trigger = self.config.mfe_ratchet_trigger_scalp if is_scalp else self.config.mfe_ratchet_trigger_macro
        plateau_ratchet_time = self.config.plateau_ratchet_minutes_scalp if is_scalp else self.config.plateau_ratchet_minutes_macro

        # ==============================================================================
        # TRIGGER 0: Tsunami Shock / Emergency Liquidation (Lesson #24)
        # ==============================================================================
        if is_tsunami_shock:
            return TradeHealthEvaluation(
                symbol=pos.symbol,
                position_id=pos.position_id,
                decision=RecyclerDecision.EMERGENCY_KILL,
                health_score=Decimal("0.00"),
                current_pnl_pct=pnl_pct,
                mfe_pct=mfe_pct,
                mae_pct=mae_pct,
                elapsed_minutes=elapsed_minutes,
                plateau_minutes=plateau_minutes,
                action_reason="Tsunami shock detected. Emergency fleet liquidation active to preserve equity.",
                should_exit=True,
                should_ratchet=False
            )

        # ==============================================================================
        # MINIMUM OBSERVATION BUFFER (Prevents knee-jerk exits on entry noise)
        # ==============================================================================
        if elapsed_minutes < min_obs:
            return TradeHealthEvaluation(
                symbol=pos.symbol,
                position_id=pos.position_id,
                decision=RecyclerDecision.MAINTAIN,
                health_score=Decimal("85.00"),
                current_pnl_pct=pnl_pct,
                mfe_pct=mfe_pct,
                mae_pct=mae_pct,
                elapsed_minutes=elapsed_minutes,
                plateau_minutes=plateau_minutes,
                action_reason=f"Position within initial observation window ({elapsed_minutes:.1f}m < {min_obs:.1f}m). Edge incubating.",
                should_exit=False,
                should_ratchet=False
            )

        # ==============================================================================
        # TRIGGER 1: Orderflow & CVD Inversion (Lesson #32)
        # ==============================================================================
        if cvd_zscore is not None:
            if pos.side == "BUY" and cvd_zscore <= -self.config.cvd_inversion_zscore_threshold:
                return TradeHealthEvaluation(
                    symbol=pos.symbol,
                    position_id=pos.position_id,
                    decision=RecyclerDecision.MOVE_ON_CVD_INVERSION,
                    health_score=Decimal("15.00"),
                    current_pnl_pct=pnl_pct,
                    mfe_pct=mfe_pct,
                    mae_pct=mae_pct,
                    elapsed_minutes=elapsed_minutes,
                    plateau_minutes=plateau_minutes,
                    action_reason=f"CVD delta inverted to extreme sell pressure (Z={cvd_zscore:.2f}). Trapped longs detected.",
                    should_exit=True,
                    should_ratchet=False
                )
            elif pos.side == "SELL" and cvd_zscore >= self.config.cvd_inversion_zscore_threshold:
                return TradeHealthEvaluation(
                    symbol=pos.symbol,
                    position_id=pos.position_id,
                    decision=RecyclerDecision.MOVE_ON_CVD_INVERSION,
                    health_score=Decimal("15.00"),
                    current_pnl_pct=pnl_pct,
                    mfe_pct=mfe_pct,
                    mae_pct=mae_pct,
                    elapsed_minutes=elapsed_minutes,
                    plateau_minutes=plateau_minutes,
                    action_reason=f"CVD delta inverted to aggressive buyer absorption (Z={cvd_zscore:.2f}). Trapped shorts detected.",
                    should_exit=True,
                    should_ratchet=False
                )

        # ==============================================================================
        # TRIGGER 2: Relative Beta Weakness / Decoupling from BTC (Lesson #28 & #38)
        # ==============================================================================
        if btc_price_change_pct is not None:
            if pos.side == "BUY" and btc_price_change_pct >= Decimal("0.0030"):
                # BTC is strongly green, but asset is lagging into negative territory
                relative_lag = btc_price_change_pct - pnl_pct
                if relative_lag >= self.config.beta_divergence_threshold_pct and pnl_pct < Decimal("0"):
                    return TradeHealthEvaluation(
                        symbol=pos.symbol,
                        position_id=pos.position_id,
                        decision=RecyclerDecision.MOVE_ON_BETA_WEAKNESS,
                        health_score=Decimal("20.00"),
                        current_pnl_pct=pnl_pct,
                        mfe_pct=mfe_pct,
                        mae_pct=mae_pct,
                        elapsed_minutes=elapsed_minutes,
                        plateau_minutes=plateau_minutes,
                        action_reason=f"Relative beta breakdown: BTC up +{btc_price_change_pct*100:.2f}% while {pos.symbol} down {pnl_pct*100:.2f}% (Lag: {relative_lag*100:.2f}%).",
                        should_exit=True,
                        should_ratchet=False
                    )
            elif pos.side == "SELL" and btc_price_change_pct <= Decimal("-0.0030"):
                # BTC is strongly dumping, but asset is holding/rising against our short
                relative_lag = pnl_pct - btc_price_change_pct
                if relative_lag >= self.config.beta_divergence_threshold_pct and pnl_pct < Decimal("0"):
                    return TradeHealthEvaluation(
                        symbol=pos.symbol,
                        position_id=pos.position_id,
                        decision=RecyclerDecision.MOVE_ON_BETA_WEAKNESS,
                        health_score=Decimal("20.00"),
                        current_pnl_pct=pnl_pct,
                        mfe_pct=mfe_pct,
                        mae_pct=mae_pct,
                        elapsed_minutes=elapsed_minutes,
                        plateau_minutes=plateau_minutes,
                        action_reason=f"Relative beta decoupling against short: BTC dumping but {pos.symbol} exhibiting stubborn bid strength.",
                        should_exit=True,
                        should_ratchet=False
                    )

        # ==============================================================================
        # TRIGGER 3: Plateau Breakeven Ratchet Protection (Lesson #20, #21 & #35)
        # ==============================================================================
        if not pos.is_breakeven_ratcheted and mfe_pct >= mfe_ratchet_trigger:
            if plateau_minutes >= plateau_ratchet_time:
                # Price expanded, but is now plateauing without completing target
                if pos.side == "BUY":
                    new_sl = pos.entry_price * (Decimal("1.0") + self.config.breakeven_fee_buffer_pct)
                    valid_ratchet = (new_sl > pos.stop_loss and current_price > new_sl)
                else:
                    new_sl = pos.entry_price * (Decimal("1.0") - self.config.breakeven_fee_buffer_pct)
                    valid_ratchet = (new_sl < pos.stop_loss and current_price < new_sl)

                if valid_ratchet:
                    return TradeHealthEvaluation(
                        symbol=pos.symbol,
                        position_id=pos.position_id,
                        decision=RecyclerDecision.RATCHET_PROTECT,
                        health_score=Decimal("65.00"),
                        current_pnl_pct=pnl_pct,
                        mfe_pct=mfe_pct,
                        mae_pct=mae_pct,
                        elapsed_minutes=elapsed_minutes,
                        plateau_minutes=plateau_minutes,
                        action_reason=f"MFE peaked at +{mfe_pct*100:.2f}% and plateaued for {plateau_minutes:.1f}m. Ratcheting SL to lock Breakeven + fee buffer.",
                        should_exit=False,
                        should_ratchet=True,
                        recommended_new_sl=new_sl
                    )

        # ==============================================================================
        # TRIGGER 4: Temporal Stagnation / Dead Band Decay (Lesson #17 & #35)
        # ==============================================================================
        is_in_dead_band = (
            pnl_pct <= self.config.dead_band_pct and
            pnl_pct >= -self.config.dead_band_pct
        )
        lacks_follow_through = (mfe_pct < min_follow_mfe)

        if elapsed_minutes >= max_stall:
            if is_in_dead_band or lacks_follow_through or pnl_pct < Decimal("0"):
                return TradeHealthEvaluation(
                    symbol=pos.symbol,
                    position_id=pos.position_id,
                    decision=RecyclerDecision.MOVE_ON_STALL,
                    health_score=Decimal("25.00"),
                    current_pnl_pct=pnl_pct,
                    mfe_pct=mfe_pct,
                    mae_pct=mae_pct,
                    elapsed_minutes=elapsed_minutes,
                    plateau_minutes=plateau_minutes,
                    action_reason=f"Temporal edge expired at {elapsed_minutes:.1f}m (Max: {max_stall:.1f}m). Price flat ({pnl_pct*100:.2f}%) with no follow-through (MFE: +{mfe_pct*100:.2f}%). Liberating slot.",
                    should_exit=True,
                    should_ratchet=False
                )

        # ==============================================================================
        # TRIGGER 5: Opportunity Displacement / Scanner Demand (Recycling Power)
        # ==============================================================================
        if scanner_candidates and len(scanner_candidates) > 0:
            # Check if this active trade is stalling or sluggish while prime candidates queue
            if elapsed_minutes >= (max_stall * Decimal("0.60")) and (pnl_pct <= Decimal("0.0010")):
                top_candidate = scanner_candidates[0]
                top_symbol = getattr(top_candidate, "symbol", str(top_candidate))
                top_score = getattr(top_candidate, "volatility_score", None)

                # If top candidate is not the current symbol and has compelling volume/volatility
                if top_symbol != pos.symbol and (top_score is None or top_score >= Decimal("0.025")):
                    return TradeHealthEvaluation(
                        symbol=pos.symbol,
                        position_id=pos.position_id,
                        decision=RecyclerDecision.MOVE_ON_DISPLACEMENT,
                        health_score=Decimal("28.00"),
                        current_pnl_pct=pnl_pct,
                        mfe_pct=mfe_pct,
                        mae_pct=mae_pct,
                        elapsed_minutes=elapsed_minutes,
                        plateau_minutes=plateau_minutes,
                        action_reason=f"Displaced by higher-conviction asset {top_symbol}. Current trade sluggish after {elapsed_minutes:.1f}m. Liberating capital.",
                        should_exit=True,
                        should_ratchet=False,
                        displaced_by_candidate=top_symbol
                    )

        # ==============================================================================
        # DEFAULT: Maintain Position (Alpha intact, room to run)
        # ==============================================================================
        # Compute dynamic health score (0 to 100)
        # Higher score = high positive PnL, fresh elapsed time, high MFE
        time_factor = max(Decimal("0"), Decimal("1.0") - (elapsed_minutes / max_stall))
        pnl_factor = Decimal("50.0") + (pnl_pct * Decimal("2000.0"))
        health_score = (pnl_factor * Decimal("0.60")) + (time_factor * Decimal("40.0"))
        health_score = max(Decimal("0.0"), min(Decimal("100.0"), health_score))

        return TradeHealthEvaluation(
            symbol=pos.symbol,
            position_id=pos.position_id,
            decision=RecyclerDecision.MAINTAIN,
            health_score=health_score,
            current_pnl_pct=pnl_pct,
            mfe_pct=mfe_pct,
            mae_pct=mae_pct,
            elapsed_minutes=elapsed_minutes,
            plateau_minutes=plateau_minutes,
            action_reason=f"Position healthy (Score: {health_score:.1f}/100, PnL: {pnl_pct*100:+.2f}%). Edge running toward target.",
            should_exit=False,
            should_ratchet=False
        )

    def execute_move_on(
        self,
        raw_position: Any,
        evaluation: TradeHealthEvaluation,
        current_price: Decimal,
        current_time_utc: datetime.datetime,
        binance_client: Optional[Any] = None,
        quarantine_registry: Optional[Any] = None,
        on_slot_liberated: Optional[Callable[[str, str], None]] = None
    ) -> RecyclerExecutionReceipt:
        """
        Executes an atomic exit with Zero Orphan Guarantee.
        
        1. Atomically cancels all resting conditional orders on the symbol.
        2. Submits market close order (reduce_only=True).
        3. Quarantines the symbol to prevent churn.
        4. Invokes slot liberation callback.
        5. Logs forensic autopsy to database.
        """
        pos = self.normalize_position(raw_position)
        symbol = pos.symbol
        close_side = "SELL" if pos.side == "BUY" else "BUY"

        logger.info(
            "Executing autonomous Move-On for %s [%s] | Reason: %s | PnL: %+.2f%%",
            symbol, pos.position_id, evaluation.action_reason, evaluation.current_pnl_pct * 100
        )

        try:
            # Step 1: Zero-Orphan Guarantee — Cancel all resting brackets
            if binance_client is not None and hasattr(binance_client, "cancel_all_open_orders"):
                binance_client.cancel_all_open_orders(symbol=symbol)

            # Step 2: Flatten position via market order
            if binance_client is not None and hasattr(binance_client, "submit_market_order"):
                binance_client.submit_market_order(
                    symbol=symbol,
                    side=close_side,
                    quantity=pos.quantity,
                    reduce_only=True
                )

            # Step 3: Register Symbol Quarantine (Lesson #22)
            quarantine_expiry = current_time_utc + datetime.timedelta(
                minutes=self.config.quarantine_duration_minutes
            )
            quarantine_target = quarantine_registry if quarantine_registry is not None else self.quarantine_registry
            if isinstance(quarantine_target, dict):
                quarantine_target[symbol] = {
                    "expires_utc": quarantine_expiry,
                    "reason": f"CAPITAL_RECYCLER: {evaluation.decision.value}",
                    "quarantine_minutes": self.config.quarantine_duration_minutes
                }

            # Step 4: Liberate Slot Callback
            if on_slot_liberated is not None:
                try:
                    on_slot_liberated(pos.position_id, symbol)
                except Exception as cb_err:
                    logger.warning("Error invoking slot liberation callback: %s", cb_err)

            # Step 5: Log Forensic Autopsy
            self._log_autopsy(pos, evaluation, current_price, current_time_utc)

            return RecyclerExecutionReceipt(
                success=True,
                position_id=pos.position_id,
                symbol=symbol,
                action_taken=evaluation.decision.value,
                exit_price=current_price,
                net_pnl_pct=evaluation.current_pnl_pct,
                quarantine_expires_utc=quarantine_expiry,
                liberated_slot=True
            )

        except Exception as e:
            logger.error("Failed to execute move-on for %s: %s", symbol, e)
            return RecyclerExecutionReceipt(
                success=False,
                position_id=pos.position_id,
                symbol=symbol,
                action_taken=evaluation.decision.value,
                error_message=str(e)
            )

    def execute_ratchet(
        self,
        raw_position: Any,
        evaluation: TradeHealthEvaluation,
        binance_client: Optional[Any] = None
    ) -> bool:
        """
        Executes an atomic stop-loss ratchet to Breakeven + Fee Buffer.
        """
        if not evaluation.should_ratchet or evaluation.recommended_new_sl is None:
            return False

        pos = self.normalize_position(raw_position)
        symbol = pos.symbol
        new_sl = evaluation.recommended_new_sl

        logger.info(
            "Ratcheting SL for %s [%s] -> %s (Old SL: %s) | Locking in Breakeven + buffer",
            symbol, pos.position_id, new_sl, pos.stop_loss
        )

        try:
            if binance_client is not None and hasattr(binance_client, "update_stop_loss"):
                binance_client.update_stop_loss(symbol=symbol, new_stop_price=new_sl)

            # Update in-memory position state if mutable
            if hasattr(raw_position, "stop_loss"):
                raw_position.stop_loss = new_sl
            if hasattr(raw_position, "is_breakeven_ratcheted"):
                raw_position.is_breakeven_ratcheted = True

            return True
        except Exception as e:
            logger.error("Failed to ratchet SL for %s: %s", symbol, e)
            return False

    def is_symbol_in_quarantine(self, symbol: str, current_time_utc: datetime.datetime) -> bool:
        """Checks whether a symbol is currently under post-exit quarantine."""
        entry = self.quarantine_registry.get(symbol)
        if not entry:
            return False
        expires = entry.get("expires_utc")
        return bool(expires and current_time_utc < expires)

    def get_active_quarantined_symbols(self, current_time_utc: datetime.datetime) -> Set[str]:
        """Returns a snapshot set of active quarantined symbols and cleans expired entries safely."""
        active = set()
        expired = []
        for sym, entry in list(self.quarantine_registry.items()):
            expires = entry.get("expires_utc")
            if expires and current_time_utc < expires:
                active.add(sym)
            else:
                expired.append(sym)
        for sym in expired:
            self.quarantine_registry.pop(sym, None)
        return active

    def _log_autopsy(
        self,
        pos: NormalizedPosition,
        evaluation: TradeHealthEvaluation,
        exit_price: Decimal,
        current_time_utc: datetime.datetime
    ) -> None:
        """Persists autopsy record to SQLite."""
        try:
            with sqlite3.connect(self.config.database_path) as conn:
                conn.execute("""
                    INSERT INTO sentinel_autopsies (
                        timestamp_utc, position_id, symbol, side, strategy_tag,
                        entry_price, exit_price, pnl_pct, mfe_pct, mae_pct,
                        elapsed_minutes, decision, action_reason, health_score,
                        displaced_by_candidate
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    current_time_utc.isoformat(),
                    pos.position_id,
                    pos.symbol,
                    pos.side,
                    pos.strategy_tag,
                    float(pos.entry_price),
                    float(exit_price),
                    float(evaluation.current_pnl_pct),
                    float(evaluation.mfe_pct),
                    float(evaluation.mae_pct),
                    float(evaluation.elapsed_minutes),
                    evaluation.decision.value,
                    evaluation.action_reason,
                    float(evaluation.health_score),
                    evaluation.displaced_by_candidate
                ))
                conn.commit()
        except Exception as e:
            logger.warning("Could not persist autopsy to database: %s", e)
