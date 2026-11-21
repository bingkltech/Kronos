"""
src/quant/tiger_scalper.py — Core Strategy #3 (Stalking Tiger) Execution & Temporal Lifecycle Engine.

Enforces:
1. 90-second Signal TTL (cancels stale un-triggered orders).
2. The 8-12-15 Minute Decay Ladder (Velocity check at 8m, Stall Scratch at 12m, Hard Kill at 15m).
3. Dual-Regime Volatility Brackets (+1.01%/-0.66% slow vol, +1.90%/-1.10% fast vol).
4. ROI Risk Clamping (-5.5% max ROI) and 5-consecutive-loss pause.
5. Strict AGENTS.md Invariant 1 (Zero Float Financial Math with Decimal).
"""

from dataclasses import dataclass, asdict
import datetime
from decimal import Decimal
import json
import logging
import os
from typing import Any, Dict, List, Optional, Tuple

from src.quant.tiger_config import (
    TigerMasterConfig,
    TigerBracketConfig,
    TigerTemporalConfig,
    DEFAULT_TIGER_CONFIG,
)
from src.quant.tiger_orderflow import AbsorptionSignal
from src.quant.volume_profile import VolumeProfileEngine, VolumeProfileSnapshot

logger = logging.getLogger("kronos.tiger_scalper")


@dataclass
class PendingTigerSignal:
    """An active predatory signal waiting for trigger fill within 90s TTL."""
    signal_id: str
    symbol: str
    action: str                        # "BUY" or "SELL"
    entry_trigger_price: Decimal
    stop_loss_price: Decimal
    take_profit_price: Decimal
    created_at_utc: datetime.datetime
    expires_at_utc: datetime.datetime
    is_slow_regime: bool
    status: str = "PENDING"            # "PENDING", "FILLED", "EXPIRED", "CANCELLED"

    def is_expired(self, current_time_utc: datetime.datetime) -> bool:
        return current_time_utc >= self.expires_at_utc


@dataclass
class ActiveTigerPosition:
    """An open Strategy #3 position governed by the 8-12-15m Temporal Ladder."""
    position_id: str
    symbol: str
    side: str                          # "BUY" (Long) or "SELL" (Short)
    entry_price: Decimal
    take_profit: Decimal
    stop_loss: Decimal
    quantity: Decimal
    entry_time_utc: datetime.datetime
    is_slow_regime: bool
    leverage: int = 5
    notional_usd: Decimal = Decimal("100.00")
    highest_favorable_price: Optional[Decimal] = None
    lowest_adverse_price: Optional[Decimal] = None
    is_breakeven_ratcheted: bool = False

    def elapsed_minutes(self, current_time_utc: datetime.datetime) -> float:
        delta = current_time_utc - self.entry_time_utc
        return delta.total_seconds() / 60.0

    def current_pnl_pct(self, current_price: Decimal) -> Decimal:
        """Computes current gross price return percentage."""
        if self.entry_price <= Decimal("0"):
            return Decimal("0")
        if self.side == "BUY":
            return (current_price - self.entry_price) / self.entry_price
        else:
            return (self.entry_price - current_price) / self.entry_price


class TigerExecutionEngine:
    """
    Sovereign execution arbiter for Strategy #3.
    Operates independently with zero coupling to Strategy #1 or #2.
    """
    def __init__(
        self,
        config: Optional[TigerMasterConfig] = None,
        state_file: str = "data/tiger_state.json"
    ):
        self.cfg = config or DEFAULT_TIGER_CONFIG
        self.state_file = state_file
        self.pending_signals: Dict[str, PendingTigerSignal] = {}
        self.active_positions: Dict[str, ActiveTigerPosition] = {}
        self.consecutive_losses: int = 0
        self.pause_until_utc: Optional[datetime.datetime] = None
        self.total_trades_count: int = 0
        self.total_wins_count: int = 0
        self.symbol_cooldowns: Dict[str, datetime.datetime] = {}
        self.last_fleet_action_time_utc: Optional[datetime.datetime] = None
        self.load_state()

    def is_fleet_in_cooldown(self, current_time_utc: datetime.datetime) -> bool:
        """Checks if the global inter-trade fleet cooldown is active to prevent cross-symbol burst churn."""
        if self.last_fleet_action_time_utc is None:
            return False
        elapsed = (current_time_utc - self.last_fleet_action_time_utc).total_seconds()
        return elapsed < self.cfg.temporal.fleet_inter_trade_cooldown_seconds

    def is_symbol_in_cooldown(self, symbol: str, current_time_utc: datetime.datetime) -> bool:
        """Checks if a symbol is in the post-exit cooling period to eliminate re-entry churn."""
        cd = self.symbol_cooldowns.get(symbol)
        return bool(cd and current_time_utc < cd)

    def cleanup_expired_cooldowns(self, current_time_utc: datetime.datetime) -> None:
        """Safely cleans expired symbol cooldown entries without mutating during iteration."""
        expired = [sym for sym, cd in list(self.symbol_cooldowns.items()) if current_time_utc >= cd]
        for sym in expired:
            self.symbol_cooldowns.pop(sym, None)

    def calculate_volatility_parity_sizing(
        self,
        entry_price: Decimal,
        sl_price: Decimal
    ) -> Tuple[Decimal, Decimal]:
        """
        Calculates position notional and contract quantity based on strict dollar risk parity.
        Risk = Notional * Stop_Loss_Pct.
        Therefore: Notional = Target_Risk_USD / Stop_Loss_Pct.
        Returns:
            (notional_usd, quantity)
        """
        if entry_price <= Decimal("0") or sl_price <= Decimal("0"):
            return self.cfg.brackets.min_notional_usd, Decimal("0")

        sl_pct = abs(entry_price - sl_price) / entry_price
        if sl_pct <= Decimal("0.0010"):  # Safeguard against zero division
            sl_pct = Decimal("0.0066")

        target_risk = self.cfg.brackets.risk_budget_per_trade_usd
        raw_notional = target_risk / sl_pct

        # Clamp notional within safety bounds
        clamped_notional = max(
            self.cfg.brackets.min_notional_usd,
            min(self.cfg.brackets.max_notional_usd, raw_notional)
        )
        qty = (clamped_notional / entry_price).quantize(Decimal("0.001"))
        return clamped_notional, qty

    def is_paused(self, current_time_utc: datetime.datetime) -> bool:
        """Checks if 5-loss circuit breaker is active."""
        if self.pause_until_utc and current_time_utc < self.pause_until_utc:
            return True
        if self.pause_until_utc and current_time_utc >= self.pause_until_utc:
            logger.info("[TIGER ENGINE] 60-minute pause cooldown expired. Resuming stalking.")
            self.pause_until_utc = None
            self.consecutive_losses = 0
            self.save_state()
        return False

    def create_signal_from_absorption(
        self,
        signal: AbsorptionSignal,
        atr_pct: Decimal,
        current_time_utc: datetime.datetime,
        custom_tp_pct: Optional[Decimal] = None,
        custom_sl_pct: Optional[Decimal] = None,
        volume_profile: Optional[VolumeProfileSnapshot] = None
    ) -> Optional[PendingTigerSignal]:
        """
        Transforms a Trapped Trader Absorption event into a calibrated PendingTigerSignal.
        Enforces Dual-Regime Volatility Brackets (or dynamically learned custom brackets) and 90s Signal TTL.
        """
        if not signal.is_valid or signal.action not in ("BUY", "SELL"):
            return None

        if self.is_paused(current_time_utc):
            logger.warning("[TIGER ENGINE] Signal rejected: Engine currently in 5-loss cooldown.")
            return None

        # 1. Global Fleet Inter-Trade Cooldown (Anti-Burst & Cross-Symbol Churn Shield)
        if self.is_fleet_in_cooldown(current_time_utc):
            elapsed = int((current_time_utc - self.last_fleet_action_time_utc).total_seconds()) if self.last_fleet_action_time_utc else 0
            logger.info(f"[TIGER ENGINE] Signal for {signal.symbol} vetoed: Global Fleet Cooldown active ({elapsed}s < {self.cfg.temporal.fleet_inter_trade_cooldown_seconds}s).")
            return None

        # 2. Per-Symbol 15m Post-Exit Cooldown
        if self.is_symbol_in_cooldown(signal.symbol, current_time_utc):
            logger.info(f"[TIGER ENGINE] Signal for {signal.symbol} vetoed: Symbol in 15m post-exit cooldown.")
            return None

        # 3. Duplicate Order / Position Guards
        if any(s.symbol == signal.symbol for s in self.pending_signals.values()):
            logger.info(f"[TIGER ENGINE] Signal for {signal.symbol} rejected: Pending order already exists.")
            return None

        if any(p.symbol == signal.symbol for p in self.active_positions.values()):
            logger.info(f"[TIGER ENGINE] Signal for {signal.symbol} rejected: Position already active for symbol.")
            return None

        # 4. Total Committed Slot Hard Ceiling (Active + Pending <= max_concurrent_positions)
        total_committed = len(self.active_positions) + len(self.pending_signals)
        if total_committed >= self.cfg.brackets.max_concurrent_positions:
            logger.info(f"[TIGER ENGINE] Signal rejected: Total committed slots ({total_committed} = {len(self.active_positions)} active + {len(self.pending_signals)} pending) >= max {self.cfg.brackets.max_concurrent_positions}.")
            return None

        brk = self.cfg.brackets
        is_slow = atr_pct < brk.slow_vol_atr_threshold_pct

        if custom_tp_pct is not None:
            tp_pct = custom_tp_pct
        else:
            tp_pct = brk.slow_vol_tp_price_pct if is_slow else brk.fast_vol_tp_price_pct

        if custom_sl_pct is not None:
            sl_pct = custom_sl_pct
        else:
            sl_pct = brk.slow_vol_sl_price_pct if is_slow else brk.fast_vol_sl_price_pct

        entry = signal.entry_trigger_price
        if entry <= Decimal("0"):
            return None

        # 5. Spatial Liquidity Veto Gate (Previous-UTC-Day Volume Profile H1 + H4 + FADING_BREAKOUT):
        # Prevents fading runaway breakouts outside yesterday's Value Area (15.4% WR bleed)
        # as well as firing into opposing pPOC or HVN chop zones.
        if volume_profile is not None:
            vp_res = VolumeProfileEngine.evaluate_spatial_veto(
                profile=volume_profile,
                entry_price=entry,
                side=signal.action,
                veto_firing_into_poc=True,
                veto_hvn_chop=True,
                veto_fading_breakout=True,
            )
            if not vp_res.approved:
                logger.info(f"[TIGER VP VETO] {signal.symbol}: {vp_res.reason}")
                return None

        if signal.action == "SELL":  # Shorting trapped bulls
            tp_price = entry * (Decimal("1") - tp_pct)
            sl_price = entry * (Decimal("1") + sl_pct)
        else:                        # Longing trapped bears
            tp_price = entry * (Decimal("1") + tp_pct)
            sl_price = entry * (Decimal("1") - sl_pct)

        ttl_seconds = self.cfg.temporal.signal_ttl_seconds
        expires_utc = current_time_utc + datetime.timedelta(seconds=ttl_seconds)
        signal_id = f"TIGER_SIG_{signal.symbol}_{int(current_time_utc.timestamp())}"

        pending = PendingTigerSignal(
            signal_id=signal_id,
            symbol=signal.symbol,
            action=signal.action,
            entry_trigger_price=entry,
            stop_loss_price=sl_price,
            take_profit_price=tp_price,
            created_at_utc=current_time_utc,
            expires_at_utc=expires_utc,
            is_slow_regime=is_slow,
            status="PENDING"
        )

        self.pending_signals[signal_id] = pending
        self.last_fleet_action_time_utc = current_time_utc
        self.save_state()
        return pending

    def check_signal_expiration(
        self,
        current_time_utc: datetime.datetime
    ) -> List[str]:
        """Scans pending signals and cancels any that exceed the 90-second TTL."""
        expired_ids = []
        for sig_id, sig in list(self.pending_signals.items()):
            if sig.status == "PENDING" and sig.is_expired(current_time_utc):
                sig.status = "EXPIRED"
                expired_ids.append(sig_id)
                logger.info(f"[TIGER SIGNAL EXPIRED] {sig.symbol} unfilled after 90s. Prey escaped.")
                del self.pending_signals[sig_id]

        if expired_ids:
            self.save_state()
        return expired_ids

    def fill_signal(
        self,
        signal_id: str,
        fill_price: Decimal,
        quantity: Decimal,
        fill_time_utc: datetime.datetime,
        notional_usd: Optional[Decimal] = None
    ) -> Optional[ActiveTigerPosition]:
        """Transition a pending signal to an active open position."""
        sig = self.pending_signals.get(signal_id)
        if not sig or sig.status != "PENDING":
            return None

        pos_id = f"TIGER_POS_{sig.symbol}_{int(fill_time_utc.timestamp())}"
        actual_notional = notional_usd or (fill_price * quantity).quantize(Decimal("0.01"))
        pos = ActiveTigerPosition(
            position_id=pos_id,
            symbol=sig.symbol,
            side=sig.action,
            entry_price=fill_price,
            take_profit=sig.take_profit_price,
            stop_loss=sig.stop_loss_price,
            quantity=quantity,
            entry_time_utc=fill_time_utc,
            is_slow_regime=sig.is_slow_regime,
            leverage=self.cfg.brackets.leverage,
            notional_usd=actual_notional,
            highest_favorable_price=fill_price,
            lowest_adverse_price=fill_price,
            is_breakeven_ratcheted=False
        )

        sig.status = "FILLED"
        del self.pending_signals[signal_id]
        self.active_positions[pos_id] = pos
        self.save_state()
        return pos

    def evaluate_temporal_lifecycle(
        self,
        position_id: str,
        current_price: Decimal,
        current_time_utc: datetime.datetime,
        fee_friction_pct: Decimal = Decimal("0.0010")  # 0.10% roundtrip
    ) -> Tuple[str, Optional[str]]:
        """
        The 8-12-15 Minute Decay Ladder Arbiter:
        Returns:
            (action, reason)
            action in ("HOLD", "RATCHET_BE", "STALL_SCRATCH", "HARD_KILL", "TAKE_PROFIT", "STOP_LOSS")
        """
        pos = self.active_positions.get(position_id)
        if not pos:
            return "HOLD", None

        # Track trajectory extremes
        if pos.side == "BUY":
            pos.highest_favorable_price = max(pos.highest_favorable_price or pos.entry_price, current_price)
            pos.lowest_adverse_price = min(pos.lowest_adverse_price or pos.entry_price, current_price)
        else:
            pos.highest_favorable_price = min(pos.highest_favorable_price or pos.entry_price, current_price)
            pos.lowest_adverse_price = max(pos.lowest_adverse_price or pos.entry_price, current_price)

        pnl_pct = pos.current_pnl_pct(current_price)
        elapsed_m = pos.elapsed_minutes(current_time_utc)
        temp_cfg = self.cfg.temporal

        # 1. Bracket Check: Take-Profit Trigger
        if pos.side == "BUY" and current_price >= pos.take_profit:
            return "TAKE_PROFIT", f"Target Hit: +{pnl_pct*100:.2f}%"
        if pos.side == "SELL" and current_price <= pos.take_profit:
            return "TAKE_PROFIT", f"Target Hit: +{pnl_pct*100:.2f}%"

        # 2. Bracket Check: Stop-Loss Trigger
        if pos.side == "BUY" and current_price <= pos.stop_loss:
            return "STOP_LOSS", f"Stop Hit: {pnl_pct*100:.2f}%"
        if pos.side == "SELL" and current_price >= pos.stop_loss:
            return "STOP_LOSS", f"Stop Hit: {pnl_pct*100:.2f}%"

        # 2.1 The 30-Second Zero-MFE Sanity Circuit Breaker (Anti-Liquidation Flush Shield - Lesson #49)
        # Prevents knife-catch flushes with zero bounce from developing into full stop-loss hits during initial 3m window.
        elapsed_sec = (current_time_utc - pos.entry_time_utc).total_seconds()
        zero_abort_sec = getattr(temp_cfg, "zero_mfe_abort_seconds", 30)
        if zero_abort_sec <= elapsed_sec < 180:
            mfe = Decimal("0")
            if pos.side == "BUY" and pos.highest_favorable_price and pos.highest_favorable_price > pos.entry_price:
                mfe = (pos.highest_favorable_price - pos.entry_price) / pos.entry_price
            elif pos.side == "SELL" and pos.highest_favorable_price and pos.highest_favorable_price < pos.entry_price:
                mfe = (pos.entry_price - pos.highest_favorable_price) / pos.entry_price

            max_fav = getattr(temp_cfg, "zero_mfe_max_favorable_pct", Decimal("0.0005"))
            max_loss = getattr(temp_cfg, "zero_mfe_max_loss_pct", Decimal("-0.0025"))
            if mfe <= max_fav and pnl_pct <= max_loss:
                return "ZERO_MFE_ABORT", f"30s Zero-MFE Circuit Breaker: Favorable movement stalled at {mfe*100:.3f}% and PnL {pnl_pct*100:.2f}% <= {max_loss*100:.2f}%. Immediate market scratch."

        # 3. Minute 8 Velocity Check or Profit Cushion Lock (Breakeven Cushion Ratchet)
        should_ratchet = False
        ratchet_reason = ""
        if not pos.is_breakeven_ratcheted:
            if pnl_pct >= self.cfg.brackets.ratchet_trigger_price_pct:
                should_ratchet = True
                ratchet_reason = f"Profit Cushion Lock: +{pnl_pct*100:.2f}% >= {self.cfg.brackets.ratchet_trigger_price_pct*100:.2f}%. SL moved to Breakeven+Fees"
            elif elapsed_m >= temp_cfg.velocity_check_minutes and pnl_pct >= temp_cfg.velocity_min_gain_pct:
                should_ratchet = True
                ratchet_reason = f"Velocity Check passed at {elapsed_m:.1f}m: SL moved to Breakeven+Fees"

        if should_ratchet:
            if pos.side == "BUY":
                pos.stop_loss = pos.entry_price * (Decimal("1") + fee_friction_pct)
            else:
                pos.stop_loss = pos.entry_price * (Decimal("1") - fee_friction_pct)
            pos.is_breakeven_ratcheted = True
            self.save_state()
            return "RATCHET_BE", ratchet_reason

        # 3.1 Minute 5 Micro-Plateau Breakeven Ratchet (Anti-Chop Capital Preserver)
        # If position bounced >= +0.20% MFE and has floated >= 5 minutes without hitting TP,
        # lock the stop loss to Entry Breakeven (-0.10% buffer for fees).
        if temp_cfg.plateau_ratchet_enabled and not pos.is_breakeven_ratcheted:
            mfe = Decimal("0")
            if pos.side == "BUY" and pos.highest_favorable_price and pos.highest_favorable_price > pos.entry_price:
                mfe = (pos.highest_favorable_price - pos.entry_price) / pos.entry_price
            elif pos.side == "SELL" and pos.highest_favorable_price and pos.highest_favorable_price < pos.entry_price:
                mfe = (pos.entry_price - pos.highest_favorable_price) / pos.entry_price

            if elapsed_m >= temp_cfg.plateau_ratchet_minutes and mfe >= temp_cfg.plateau_min_mfe_pct:
                if pos.side == "BUY":
                    new_sl = pos.entry_price * (Decimal("1") + temp_cfg.plateau_be_buffer_pct)
                    pos.stop_loss = max(pos.stop_loss, new_sl)
                else:
                    new_sl = pos.entry_price * (Decimal("1") - temp_cfg.plateau_be_buffer_pct)
                    pos.stop_loss = min(pos.stop_loss, new_sl)
                pos.is_breakeven_ratcheted = True
                self.save_state()
                if (pos.side == "BUY" and current_price <= pos.stop_loss) or (pos.side == "SELL" and current_price >= pos.stop_loss):
                    return "RATCHET_BE", f"5m Plateau Ratchet Exit: +{mfe*100:.2f}% MFE stalled at {elapsed_m:.1f}m. Scratched at Breakeven."
                return "RATCHET_BE", f"5m Plateau Ratchet: +{mfe*100:.2f}% MFE stalled at {elapsed_m:.1f}m. SL moved to Breakeven."

        # 4. Minute 12: Stall / Chop Scratch Exit
        if elapsed_m >= temp_cfg.stall_scratch_minutes:
            if temp_cfg.stall_band_low_pct <= pnl_pct <= temp_cfg.stall_band_high_pct:
                return "STALL_SCRATCH", f"Momentum dead at 12m ({pnl_pct*100:.2f}%). Scratch exit."

        # 5. Minute 15: Hard Temporal Invalidation Kill
        if elapsed_m >= temp_cfg.hard_temporal_expiry_minutes:
            return "HARD_KILL", f"15m analysis window expired ({pnl_pct*100:.2f}%). Market flatten."

        return "HOLD", None

    def ratchet_to_breakeven(
        self,
        position_id: str,
        new_sl: Optional[Decimal] = None
    ) -> bool:
        """
        Ratchets the stop loss of an active position to breakeven or an explicitly supplied level.
        Enforces zero float math and persists engine state.
        """
        pos = self.active_positions.get(position_id)
        if not pos:
            return False

        if new_sl is not None:
            pos.stop_loss = Decimal(str(new_sl))
        else:
            fee_buffer = Decimal("0.0022")
            if pos.side == "BUY":
                pos.stop_loss = pos.entry_price * (Decimal("1") + fee_buffer)
            else:
                pos.stop_loss = pos.entry_price * (Decimal("1") - fee_buffer)

        pos.is_breakeven_ratcheted = True
        self.save_state()
        return True

    def close_position(
        self,
        position_id: str,
        exit_price: Decimal,
        exit_time_utc: datetime.datetime,
        reason: str,
        fee_friction_pct: Decimal = Decimal("0.0000")
    ) -> Dict[str, Any]:
        """Closes an active position and updates 5-consecutive-loss state using net-of-friction win truth."""
        pos = self.active_positions.get(position_id)
        if not pos:
            raise KeyError(f"Position {position_id} not found.")

        pnl_pct = pos.current_pnl_pct(exit_price)
        net_pnl_pct = pnl_pct - fee_friction_pct
        is_win = net_pnl_pct > Decimal("0")

        self.total_trades_count += 1
        if is_win:
            self.total_wins_count += 1
            self.consecutive_losses = 0
            logger.info(f"[TIGER WIN] {pos.symbol} closed for +{pnl_pct*100:.2f}%. Loss count reset to 0.")
        else:
            self.consecutive_losses += 1
            logger.warning(f"[TIGER LOSS #{self.consecutive_losses}] {pos.symbol} closed for {pnl_pct*100:.2f}%.")
            if self.consecutive_losses >= self.cfg.brackets.consecutive_loss_pause_count:
                cooldown_m = self.cfg.brackets.consecutive_loss_cooldown_minutes
                self.pause_until_utc = exit_time_utc + datetime.timedelta(minutes=cooldown_m)
                logger.error(
                    f"[TIGER 5-LOSS BREAKER] {self.consecutive_losses} consecutive losses reached! "
                    f"Pausing strategy for {cooldown_m} minutes until {self.pause_until_utc.isoformat()}."
                )

        # Enforce post-exit symbol cooldown to prevent churning
        cooldown_m = self.cfg.brackets.symbol_cooldown_minutes
        self.symbol_cooldowns[pos.symbol] = exit_time_utc + datetime.timedelta(minutes=cooldown_m)
        self.last_fleet_action_time_utc = exit_time_utc
        logger.info(f"[TIGER COOLDOWN] {pos.symbol} entered {cooldown_m}m post-exit cooldown until {self.symbol_cooldowns[pos.symbol].isoformat()}.")

        del self.active_positions[position_id]
        self.save_state()

        return {
            "position_id": position_id,
            "symbol": pos.symbol,
            "side": pos.side,
            "entry_price": str(pos.entry_price),
            "exit_price": str(exit_price),
            "notional_usd": str(pos.notional_usd),
            "pnl_pct": str(pnl_pct),
            "is_win": is_win,
            "consecutive_losses": self.consecutive_losses,
            "reason": reason
        }

    def log_counterfactual_veto(
        self,
        signal: PendingTigerSignal,
        reason_codes: List[str],
        fill_price: Decimal,
        timestamp_utc: datetime.datetime,
        log_file: str = "data/tiger_counterfactuals.jsonl",
    ) -> None:
        """
        Records a vetoed signal as a counterfactual 'ghost trade' for statistical audit.
        Allows empirical verification of whether risk vetoes protected capital or blocked winners.
        """
        try:
            os.makedirs(os.path.dirname(log_file), exist_ok=True)
            entry_d = {
                "signal_id": signal.signal_id,
                "symbol": signal.symbol,
                "action": signal.action,
                "entry_trigger_price": str(signal.entry_trigger_price),
                "evaluation_fill_price": str(fill_price),
                "stop_loss_price": str(signal.stop_loss_price),
                "take_profit_price": str(signal.take_profit_price),
                "reason_codes": reason_codes,
                "timestamp_utc": timestamp_utc.isoformat(),
            }
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry_d) + "\n")
        except Exception as e:
            logger.warning(f"[COUNTERFACTUAL-LOG-ERROR] Failed to append ghost trade: {e}")

    def save_state(self) -> None:
        """Persist state to disk."""
        os.makedirs(os.path.dirname(self.state_file), exist_ok=True)
        data = {
            "consecutive_losses": self.consecutive_losses,
            "pause_until_utc": self.pause_until_utc.isoformat() if self.pause_until_utc else None,
            "total_trades_count": self.total_trades_count,
            "total_wins_count": self.total_wins_count,
            "last_fleet_action_time_utc": self.last_fleet_action_time_utc.isoformat() if self.last_fleet_action_time_utc else None,
            "symbol_cooldowns": {k: v.isoformat() for k, v in self.symbol_cooldowns.items()},
            "pending_signals": {
                k: {
                    "signal_id": v.signal_id,
                    "symbol": v.symbol,
                    "action": v.action,
                    "entry_trigger_price": str(v.entry_trigger_price),
                    "stop_loss_price": str(v.stop_loss_price),
                    "take_profit_price": str(v.take_profit_price),
                    "created_at_utc": v.created_at_utc.isoformat(),
                    "expires_at_utc": v.expires_at_utc.isoformat(),
                    "is_slow_regime": v.is_slow_regime,
                    "status": v.status
                }
                for k, v in self.pending_signals.items()
            },
            "active_positions": {
                k: {
                    "position_id": v.position_id,
                    "symbol": v.symbol,
                    "side": v.side,
                    "entry_price": str(v.entry_price),
                    "take_profit": str(v.take_profit),
                    "stop_loss": str(v.stop_loss),
                    "quantity": str(v.quantity),
                    "entry_time_utc": v.entry_time_utc.isoformat(),
                    "is_slow_regime": v.is_slow_regime,
                    "leverage": v.leverage,
                    "notional_usd": str(v.notional_usd),
                    "highest_favorable_price": str(v.highest_favorable_price) if v.highest_favorable_price else None,
                    "lowest_adverse_price": str(v.lowest_adverse_price) if v.lowest_adverse_price else None,
                    "is_breakeven_ratcheted": v.is_breakeven_ratcheted
                }
                for k, v in self.active_positions.items()
            }
        }
        with open(self.state_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    def load_state(self) -> None:
        """Load state from disk."""
        if not os.path.exists(self.state_file):
            return
        try:
            with open(self.state_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.consecutive_losses = int(data.get("consecutive_losses", 0))
            pause_str = data.get("pause_until_utc")
            self.pause_until_utc = datetime.datetime.fromisoformat(pause_str) if pause_str else None
            self.total_trades_count = int(data.get("total_trades_count", 0))
            self.total_wins_count = int(data.get("total_wins_count", 0))
            fleet_act_str = data.get("last_fleet_action_time_utc")
            self.last_fleet_action_time_utc = datetime.datetime.fromisoformat(fleet_act_str) if fleet_act_str else None
            raw_cd = data.get("symbol_cooldowns", {})
            now = datetime.datetime.now(datetime.timezone.utc)
            self.symbol_cooldowns = {}
            for k, v in raw_cd.items():
                try:
                    exp_dt = datetime.datetime.fromisoformat(v)
                    if exp_dt > now:
                        self.symbol_cooldowns[k] = exp_dt
                except Exception:
                    pass

            raw_pending = data.get("pending_signals", {})
            self.pending_signals = {}
            for k, v in raw_pending.items():
                try:
                    exp_dt = datetime.datetime.fromisoformat(v["expires_at_utc"])
                    if exp_dt > now:
                        self.pending_signals[k] = PendingTigerSignal(
                            signal_id=v["signal_id"],
                            symbol=v["symbol"],
                            action=v["action"],
                            entry_trigger_price=Decimal(v["entry_trigger_price"]),
                            stop_loss_price=Decimal(v["stop_loss_price"]),
                            take_profit_price=Decimal(v["take_profit_price"]),
                            created_at_utc=datetime.datetime.fromisoformat(v["created_at_utc"]),
                            expires_at_utc=exp_dt,
                            is_slow_regime=bool(v.get("is_slow_regime", False)),
                            status=v.get("status", "PENDING")
                        )
                except Exception as ex:
                    logger.error(f"[TIGER ENGINE] Failed to restore pending signal {k}: {ex}")

            raw_pos = data.get("active_positions", {})
            self.active_positions = {}
            for k, v in raw_pos.items():
                try:
                    self.active_positions[k] = ActiveTigerPosition(
                        position_id=v["position_id"],
                        symbol=v["symbol"],
                        side=v["side"],
                        entry_price=Decimal(v["entry_price"]),
                        take_profit=Decimal(v["take_profit"]),
                        stop_loss=Decimal(v["stop_loss"]),
                        quantity=Decimal(v["quantity"]),
                        entry_time_utc=datetime.datetime.fromisoformat(v["entry_time_utc"]),
                        is_slow_regime=bool(v.get("is_slow_regime", False)),
                        leverage=int(v.get("leverage", 5)),
                        notional_usd=Decimal(v.get("notional_usd", "100.00")),
                        highest_favorable_price=Decimal(v["highest_favorable_price"]) if v.get("highest_favorable_price") else None,
                        lowest_adverse_price=Decimal(v["lowest_adverse_price"]) if v.get("lowest_adverse_price") else None,
                        is_breakeven_ratcheted=bool(v.get("is_breakeven_ratcheted", False))
                    )
                except Exception as ex:
                    logger.error(f"[TIGER ENGINE] Failed to restore position {k}: {ex}")
        except Exception as e:
            logger.error(f"[TIGER ENGINE] Failed to load state from {self.state_file}: {e}")
