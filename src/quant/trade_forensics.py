"""
Unified Trade Forensics Engine
Complies with Kronos Foundation & Quant Architecture Invariants:
- Zero Float Financial Math (decimal.Decimal strictly for prices, PnL, fees, sizes).
- Multi-Phase Telemetry (46 items).
- Decouples Directional Prediction from Execution Friction.
- Enforces Live (1.0) vs Paper (0.5 alpha / 0.0 friction) asymmetric weighting.
"""

from decimal import Decimal
from dataclasses import dataclass
from typing import Optional, Literal
from datetime import datetime


@dataclass(frozen=True)
class TelemetryRecord:
    # Bucket 1: Base Accounting (Items 1-14)
    trade_id: str
    trade_mode: Literal["LIVE", "PAPER"]
    symbol: str
    direction: Literal["LONG", "SHORT"]
    entry_timestamp: str
    exit_timestamp: str
    entry_price: Decimal
    exit_price: Decimal
    position_size: Decimal
    notional_value_usd: Decimal
    gross_pnl_usd: Decimal
    exchange_fees_usd: Decimal
    net_pnl_usd: Decimal
    return_pct: Decimal

    # Bucket 2: Bot Decision & Model Thesis (Items 15-22)
    decision_timestamp: str
    decision_mid_price: Decimal
    model_confidence_score: Decimal
    model_checkpoint_id: str
    planned_target_price: Decimal
    planned_stop_price: Decimal
    target_horizon_bars: int
    planned_risk_reward_ratio: Decimal

    # Bucket 3: Market Context Snapshot at Entry (Items 23-29)
    rsi_14: Decimal
    atr_current: Decimal
    atr_ratio: Decimal
    ema_distance_pct: Decimal
    volume_clumping_ratio: Decimal
    order_book_imbalance_top5: Decimal
    funding_rate_current: Decimal

    # Bucket 4: Execution Quality & Microstructure (Items 30-35)
    transit_latency_ms: int
    entry_slippage_bps: Decimal
    order_type_executed: Literal["LIMIT_MAKER", "MARKET_TAKER"]
    effective_spread_bps: Decimal
    theoretical_pnl_usd: Decimal
    realization_tax_bps: Decimal

    # Bucket 5: In-Trade Path Dynamics (Items 36-42)
    mae_pct: Decimal
    mfe_pct: Decimal
    time_to_mae_seconds: int
    time_to_mfe_seconds: int
    holding_duration_seconds: int
    profit_giveback_pct: Decimal
    exit_trigger_reason: Literal[
        "TAKE_PROFIT_HIT",
        "STOP_LOSS_HIT",
        "TRAILING_STOP",
        "TIME_EXPIRATION",
        "MANUAL_OVERRIDE"
    ]

    # Bucket 6: Diagnostic Synthesis & Actionable Rules (Items 43-46)
    directional_accuracy: bool
    root_cause_diagnosis: Literal[
        "CONVICTION_WIN",
        "TOXIC_LUCKY_WIN",
        "FRICTION_BLEED",
        "STOP_INSIDE_NOISE",
        "REGIME_MISREAD",
        "ALPHA_INVALIDATION"
    ]
    alpha_learning_weight: Decimal
    friction_learning_weight: Decimal
    actionable_remedy: str


class TradeForensicsEngine:
    """
    Evaluates historical trade outcomes using the 46-item forensics framework.
    """

    @staticmethod
    def assess_trade(
        raw_trade: dict,
        trade_mode: Literal["LIVE", "PAPER"] = "LIVE"
    ) -> TelemetryRecord:
        """
        Parses raw trade data, runs the diagnostic decision tree, and builds TelemetryRecord.
        """
        direction = raw_trade["direction"]
        entry_price = Decimal(str(raw_trade["entry_price"]))
        exit_price = Decimal(str(raw_trade["exit_price"]))
        pos_size = Decimal(str(raw_trade["position_size"]))
        fees = Decimal(str(raw_trade.get("exchange_fees_usd", "0.0")))
        
        # Financial Accounting
        notional = entry_price * pos_size
        if direction == "LONG":
            gross_pnl = (exit_price - entry_price) * pos_size
        else:
            gross_pnl = (entry_price - exit_price) * pos_size
        net_pnl = gross_pnl - fees
        return_pct = (net_pnl / notional) * Decimal("100") if notional > 0 else Decimal("0")

        # Intent
        decision_mid = Decimal(str(raw_trade.get("decision_mid_price", entry_price)))
        planned_tp = Decimal(str(raw_trade["planned_target_price"]))
        planned_sl = Decimal(str(raw_trade["planned_stop_price"]))
        
        # Context
        rsi = Decimal(str(raw_trade.get("rsi_14", "50.0")))
        atr_curr = Decimal(str(raw_trade.get("atr_current", "1.0")))
        atr_ratio = Decimal(str(raw_trade.get("atr_ratio", "1.0")))
        
        # Path & Excursion
        mfe_pct = Decimal(str(raw_trade["mfe_pct"]))
        mae_pct = Decimal(str(raw_trade["mae_pct"])) # negative or 0
        t_mfe = int(raw_trade.get("time_to_mfe_seconds", 0))
        t_mae = int(raw_trade.get("time_to_mae_seconds", 0))

        # 1. Did the bot guess the outcome accurately?
        # Target threshold: intended profit in pct
        if direction == "LONG":
            target_pct = ((planned_tp - entry_price) / entry_price) * Decimal("100")
            stop_pct = ((planned_sl - entry_price) / entry_price) * Decimal("100")
        else:
            target_pct = ((entry_price - planned_tp) / entry_price) * Decimal("100")
            stop_pct = ((entry_price - planned_sl) / entry_price) * Decimal("100")

        # Directional accuracy test: Price reached target before invalidation breach
        guessed_correctly = (mfe_pct >= target_pct) and (abs(mae_pct) < abs(stop_pct) or t_mfe < t_mae)

        # 2. Friction & Realization Tax
        theo_pnl = Decimal(str(raw_trade.get("theoretical_pnl_usd", gross_pnl)))
        realization_tax_bps = ((theo_pnl - net_pnl) / notional) * Decimal("10000") if notional > 0 else Decimal("0")

        # 3. Deterministic Root-Cause Categorization
        if net_pnl > 0:
            if abs(mae_pct) > (mfe_pct * Decimal("1.5")):
                root = "TOXIC_LUCKY_WIN"
                remedy = "Trade survived deep drawdown. Penalize model confidence on this pattern."
            else:
                root = "CONVICTION_WIN"
                remedy = "Clean execution and timing. Reinforce setup feature weights."
        else:
            # Loss Diagnoses
            if guessed_correctly and gross_pnl > 0 and net_pnl <= 0:
                root = "FRICTION_BLEED"
                remedy = "Target profit was below fee/slippage floor. Raise minimum take-profit threshold."
            elif guessed_correctly and abs(mae_pct) <= (atr_curr / entry_price * Decimal("100") * Decimal("1.0")):
                root = "STOP_INSIDE_NOISE"
                remedy = "Stop was placed inside ordinary ATR volatility noise. Scale SL to 1.5x ATR."
            elif (direction == "LONG" and rsi > Decimal("75")) or (direction == "SHORT" and rsi < Decimal("25")) or (atr_ratio < Decimal("0.6")):
                root = "REGIME_MISREAD"
                remedy = "Order launched into exhausted momentum or dead chop. Enforce regime filter."
            else:
                root = "ALPHA_INVALIDATION"
                remedy = "Normal statistical variance within Sharpe expectation. No knee-jerk adjustment."

        # 4. Asymmetric Live vs Paper Weights
        if trade_mode == "LIVE":
            alpha_w = Decimal("1.0")
            fric_w = Decimal("1.0")
        else:
            alpha_w = Decimal("0.50")
            fric_w = Decimal("0.00")

        return TelemetryRecord(
            trade_id=str(raw_trade["trade_id"]),
            trade_mode=trade_mode,
            symbol=str(raw_trade["symbol"]),
            direction=direction,
            entry_timestamp=str(raw_trade["entry_timestamp"]),
            exit_timestamp=str(raw_trade["exit_timestamp"]),
            entry_price=entry_price,
            exit_price=exit_price,
            position_size=pos_size,
            notional_value_usd=notional,
            gross_pnl_usd=gross_pnl,
            exchange_fees_usd=fees,
            net_pnl_usd=net_pnl,
            return_pct=return_pct,
            decision_timestamp=str(raw_trade.get("decision_timestamp", raw_trade["entry_timestamp"])),
            decision_mid_price=decision_mid,
            model_confidence_score=Decimal(str(raw_trade.get("model_confidence_score", "0.5"))),
            model_checkpoint_id=str(raw_trade.get("model_checkpoint_id", "kronos-base")),
            planned_target_price=planned_tp,
            planned_stop_price=planned_sl,
            target_horizon_bars=int(raw_trade.get("target_horizon_bars", 10)),
            planned_risk_reward_ratio=Decimal(str(raw_trade.get("planned_risk_reward_ratio", "2.0"))),
            rsi_14=rsi,
            atr_current=atr_curr,
            atr_ratio=atr_ratio,
            ema_distance_pct=Decimal(str(raw_trade.get("ema_distance_pct", "0.0"))),
            volume_clumping_ratio=Decimal(str(raw_trade.get("volume_clumping_ratio", "1.0"))),
            order_book_imbalance_top5=Decimal(str(raw_trade.get("order_book_imbalance_top5", "0.0"))),
            funding_rate_current=Decimal(str(raw_trade.get("funding_rate_current", "0.0001"))),
            transit_latency_ms=int(raw_trade.get("transit_latency_ms", 15)),
            entry_slippage_bps=Decimal(str(raw_trade.get("entry_slippage_bps", "1.2"))),
            order_type_executed=raw_trade.get("order_type_executed", "MARKET_TAKER"),
            effective_spread_bps=Decimal(str(raw_trade.get("effective_spread_bps", "2.0"))),
            theoretical_pnl_usd=theo_pnl,
            realization_tax_bps=realization_tax_bps,
            mae_pct=mae_pct,
            mfe_pct=mfe_pct,
            time_to_mae_seconds=t_mae,
            time_to_mfe_seconds=t_mfe,
            holding_duration_seconds=int(raw_trade.get("holding_duration_seconds", 300)),
            profit_giveback_pct=Decimal(str(raw_trade.get("profit_giveback_pct", "0.0"))),
            exit_trigger_reason=raw_trade.get("exit_trigger_reason", "STOP_LOSS_HIT"),
            directional_accuracy=guessed_correctly,
            root_cause_diagnosis=root,
            alpha_learning_weight=alpha_w,
            friction_learning_weight=fric_w,
            actionable_remedy=remedy
        )
