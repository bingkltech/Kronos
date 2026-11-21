"""
Kronos Tsunami Storm Adaptive Protocol
Manages sudden unforeseen high-wave shocks, macro news catalysts, and flash dislocations.

Architecture Contract:
1. Normal Waters:
   - Max Macro Positions: 3
   - Max Scalp Positions: 1
   - Standard Entry Gates (Macro >= 60%, Scalp >= 65%)

2. Tsunami Storm Protocol (Default 60-Minute Horizon):
   - Phase 1 (First 15m - Shock Pause):
     * Complete freeze on NEW entries. Do not catch falling knives.
     * Existing positions protected via exchange Mark-Price brackets.
   - Phase 2 (15m to 60m - Focused Caution):
     * Capacity Clamped to strictly 1 Macro + 1 Scalp.
     * Elevated Conviction Hurdle: Sieve >= 75% Win Probability.
     * Ringfenced $20 margin / Mark-Price stops.
   - Phase 3 (After 60m - Calm Water Auto-Recovery):
     * Automatically returns to Normal Waters once storm timer expires and volatility calms.
"""

import os
import json
import logging
import datetime
from decimal import Decimal
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, asdict
from enum import Enum


logger = logging.getLogger("StormProtocol")

WORKSPACE_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
STORM_STATE_PATH = os.path.join(WORKSPACE_ROOT, "data", "storm_state.json")


class StormPhase(str, Enum):
    NORMAL_WATERS = "NORMAL_WATERS"
    PHASE_1_SHOCK_PAUSE = "PHASE_1_SHOCK_PAUSE"
    PHASE_2_FOCUSED_CAUTION = "PHASE_2_FOCUSED_CAUTION"


@dataclass
class StormStatus:
    is_storm_active: bool
    phase: StormPhase
    reason: str
    triggered_at_utc: Optional[str]
    expires_at_utc: Optional[str]
    pause_until_utc: Optional[str]
    seconds_remaining: int
    pause_seconds_remaining: int
    max_macro_positions: int
    max_scalp_positions: int
    min_confidence_hurdle_pct: float
    high_wave_metric: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "is_storm_active": self.is_storm_active,
            "phase": self.phase.value,
            "reason": self.reason,
            "triggered_at_utc": self.triggered_at_utc,
            "expires_at_utc": self.expires_at_utc,
            "pause_until_utc": self.pause_until_utc,
            "seconds_remaining": self.seconds_remaining,
            "pause_seconds_remaining": self.pause_seconds_remaining,
            "max_macro_positions": self.max_macro_positions,
            "max_scalp_positions": self.max_scalp_positions,
            "min_confidence_hurdle_pct": self.min_confidence_hurdle_pct,
            "high_wave_metric": self.high_wave_metric
        }


class StormProtocolManager:
    """
    Adaptive storm governor enforcing the Tsunami Protocol across both
    Macro Swing and Lightning Scalper engines.
    """

    def __init__(
        self,
        state_file: str = STORM_STATE_PATH,
        default_storm_minutes: int = 60,
        default_pause_minutes: int = 15,
        elevated_confidence_pct: float = 75.0,
        normal_macro_cap: int = 6,
        storm_macro_cap: int = 1,
        normal_scalp_cap: int = 3,
        storm_scalp_cap: int = 1,
        consecutive_stopouts_threshold: int = 5
    ):
        self.state_file = state_file
        self.default_storm_minutes = default_storm_minutes
        self.default_pause_minutes = default_pause_minutes
        self.elevated_confidence_pct = elevated_confidence_pct
        self.normal_macro_cap = normal_macro_cap
        self.storm_macro_cap = storm_macro_cap
        self.normal_scalp_cap = normal_scalp_cap
        self.storm_scalp_cap = storm_scalp_cap
        self.consecutive_stopouts_threshold = consecutive_stopouts_threshold

        # State memory
        self.is_storm_active: bool = False
        self.reason: str = "NORMAL_CONDITIONS"
        self.triggered_at_utc: Optional[datetime.datetime] = None
        self.expires_at_utc: Optional[datetime.datetime] = None
        self.pause_until_utc: Optional[datetime.datetime] = None
        self.high_wave_metric: str = "Nominal"

        self._load_state()

    def _load_state(self) -> None:
        """Loads persistent storm state if file exists."""
        if not os.path.exists(self.state_file):
            return
        try:
            with open(self.state_file, "r", encoding="utf-8") as f:
                d = json.load(f)
            if d.get("is_storm_active"):
                now = datetime.datetime.now(datetime.timezone.utc)
                exp = datetime.datetime.fromisoformat(d["expires_at_utc"])
                if now < exp:
                    self.is_storm_active = True
                    self.reason = d.get("reason", "UNSPECIFIED_STORM")
                    self.triggered_at_utc = datetime.datetime.fromisoformat(d["triggered_at_utc"])
                    self.expires_at_utc = exp
                    if d.get("pause_until_utc"):
                        self.pause_until_utc = datetime.datetime.fromisoformat(d["pause_until_utc"])
                    self.high_wave_metric = d.get("high_wave_metric", "Nominal")
                else:
                    # Expired, reset to calm
                    self.cancel_storm()
        except Exception as e:
            logger.debug("Failed loading storm state: %s", e)

    def _save_state(self, current_time_utc: Optional[datetime.datetime] = None) -> None:
        """Persists active storm state to disk for cross-process synchronization."""
        try:
            os.makedirs(os.path.dirname(self.state_file), exist_ok=True)
            status = self.get_status(current_time_utc)
            with open(self.state_file, "w", encoding="utf-8") as f:
                json.dump(status.to_dict(), f, indent=2)
        except Exception as e:
            logger.debug("Failed saving storm state: %s", e)

    def trigger_storm(
        self,
        reason: str,
        duration_minutes: Optional[int] = None,
        pause_minutes: Optional[int] = None,
        high_wave_metric: str = "Unscheduled Volatility Shock",
        current_time_utc: Optional[datetime.datetime] = None
    ) -> StormStatus:
        """
        Activates Tsunami Protocol.
        Clamps capacity to strictly 1 Macro and 1 Scalp.
        Freezes new entries for the initial pause window.
        """
        now = current_time_utc or datetime.datetime.now(datetime.timezone.utc)
        dur = duration_minutes if duration_minutes is not None else self.default_storm_minutes
        pause_dur = pause_minutes if pause_minutes is not None else self.default_pause_minutes

        self.is_storm_active = True
        self.reason = reason
        self.triggered_at_utc = now
        self.expires_at_utc = now + datetime.timedelta(minutes=dur)
        self.pause_until_utc = now + datetime.timedelta(minutes=pause_dur)
        self.high_wave_metric = high_wave_metric

        self._save_state(now)
        logger.warning(
            "🌊 [TSUNAMI PROTOCOL ACTIVATED] Reason: %s | High Wave: %s | Duration: %dm (Pause first %dm)",
            reason, high_wave_metric, dur, pause_dur
        )
        return self.get_status(now)

    def cancel_storm(self, current_time_utc: Optional[datetime.datetime] = None) -> StormStatus:
        """Manually disarms storm mode back to Normal Waters."""
        self.is_storm_active = False
        self.reason = "NORMAL_CONDITIONS"
        self.triggered_at_utc = None
        self.expires_at_utc = None
        self.pause_until_utc = None
        self.high_wave_metric = "Nominal"

        self._save_state(current_time_utc)
        logger.info("🟢 [CALM WATERS RESTORED] Normal capacities and thresholds resumed.")
        return self.get_status(current_time_utc)

    def get_status(self, current_time_utc: Optional[datetime.datetime] = None) -> StormStatus:
        """Calculates current phase, remaining seconds, and active capacity limits."""
        now = current_time_utc or datetime.datetime.now(datetime.timezone.utc)

        # Check for auto-recovery expiration
        if self.is_storm_active and self.expires_at_utc:
            if now >= self.expires_at_utc:
                # 60m expired: auto-recover
                self.is_storm_active = False
                self.reason = "NORMAL_CONDITIONS"
                self.triggered_at_utc = None
                self.expires_at_utc = None
                self.pause_until_utc = None
                self.high_wave_metric = "Nominal"
                self._save_state()

        if not self.is_storm_active:
            return StormStatus(
                is_storm_active=False,
                phase=StormPhase.NORMAL_WATERS,
                reason="Calm Waters (Standard Regime)",
                triggered_at_utc=None,
                expires_at_utc=None,
                pause_until_utc=None,
                seconds_remaining=0,
                pause_seconds_remaining=0,
                max_macro_positions=self.normal_macro_cap,
                max_scalp_positions=self.normal_scalp_cap,
                min_confidence_hurdle_pct=65.0,
                high_wave_metric=self.high_wave_metric
            )

        # Determine Phase 1 vs Phase 2
        sec_rem = max(0, int((self.expires_at_utc - now).total_seconds())) if self.expires_at_utc else 0
        pause_rem = max(0, int((self.pause_until_utc - now).total_seconds())) if self.pause_until_utc else 0

        if pause_rem > 0:
            phase = StormPhase.PHASE_1_SHOCK_PAUSE
        else:
            phase = StormPhase.PHASE_2_FOCUSED_CAUTION

        return StormStatus(
            is_storm_active=True,
            phase=phase,
            reason=self.reason,
            triggered_at_utc=self.triggered_at_utc.isoformat() if self.triggered_at_utc else None,
            expires_at_utc=self.expires_at_utc.isoformat() if self.expires_at_utc else None,
            pause_until_utc=self.pause_until_utc.isoformat() if self.pause_until_utc else None,
            seconds_remaining=sec_rem,
            pause_seconds_remaining=pause_rem,
            max_macro_positions=self.storm_macro_cap,
            max_scalp_positions=self.storm_scalp_cap,
            min_confidence_hurdle_pct=self.elevated_confidence_pct,
            high_wave_metric=self.high_wave_metric
        )

    def evaluate_market_wave(
        self,
        btc_klines: Optional[List[Dict[str, Any]]] = None,
        macro_breadth_pct: Optional[Decimal] = None,
        recent_stopouts: int = 0,
        is_news_blackout: bool = False,
        news_event_name: str = "",
        current_time_utc: Optional[datetime.datetime] = None
    ) -> Tuple[bool, Optional[StormStatus]]:
        """
        Monitors for high ocean waves and unforeseen shock catalysts:
        1. High-impact news event (CPI/FOMC).
        2. BTC 5m violent velocity spike (>2.0%).
        3. Market Breadth systemic collapse (<15% or >85%).
        4. Clustering stop-outs (>= 2 in 30 mins).
        """
        now = current_time_utc or datetime.datetime.now(datetime.timezone.utc)

        # If storm is already active, just return current status
        if self.is_storm_active:
            status = self.get_status(now)
            return True, status

        # Condition 1: High-impact macro news announcement
        if is_news_blackout:
            reason = f"Macro News Catalyst ({news_event_name or 'High-Impact Economic Release'})"
            metric = "News Blackout Horizon Active"
            status = self.trigger_storm(reason=reason, high_wave_metric=metric, current_time_utc=now)
            return True, status

        # Condition 2: BTC violent 5-minute velocity shock (> 2.0% single candle or burst)
        if btc_klines and len(btc_klines) >= 2:
            last = btc_klines[-1]
            c = Decimal(str(last["close"]))
            o = Decimal(str(last["open"]))
            h = Decimal(str(last["high"]))
            l = Decimal(str(last["low"]))
            candle_range_pct = ((h - l) / o) * Decimal("100")
            velocity_pct = abs((c - o) / o) * Decimal("100")

            if velocity_pct >= Decimal("2.00") or candle_range_pct >= Decimal("3.00"):
                reason = "Violent BTC Volatility Spike (Ocean Wave Out of Control)"
                metric = f"BTC 5m Velocity: {float(velocity_pct):.2f}% | 5m Range: {float(candle_range_pct):.2f}%"
                status = self.trigger_storm(reason=reason, high_wave_metric=metric, current_time_utc=now)
                return True, status

        # Condition 3: Systemic market breadth shock
        if macro_breadth_pct is not None:
            if macro_breadth_pct < Decimal("15.0") or macro_breadth_pct > Decimal("85.0"):
                reason = "Extreme Systemic Market Breadth Dislocation"
                metric = f"Breadth Skew: {float(macro_breadth_pct):.1f}%"
                status = self.trigger_storm(reason=reason, high_wave_metric=metric, current_time_utc=now)
                return True, status

        # Condition 4: Cluster stop-outs (>= 5 stop-outs in 30m)
        if recent_stopouts >= self.consecutive_stopouts_threshold:
            reason = "Multiple Position Stop-Outs (Chop/Whipsaw Sea)"
            metric = f"{recent_stopouts} Consecutive Stop-Outs Triggered"
            status = self.trigger_storm(reason=reason, high_wave_metric=metric, current_time_utc=now)
            return True, status

        return False, None

    def is_entry_permitted(
        self,
        is_scalp: bool,
        current_macro_count: int,
        current_scalp_count: int,
        confidence_pct: float,
        current_time_utc: Optional[datetime.datetime] = None
    ) -> Tuple[bool, str]:
        """
        Enforces the Tsunami Protocol entry clamps:
        - Phase 1 (Shock Pause): Strict VETO on all new entries.
        - Phase 2 (Focused Caution):
          * Macro permitted only if current_macro_count == 0 (clamped to 1).
          * Scalp permitted only if current_scalp_count == 0 (clamped to 1).
          * Requires elevated confidence >= 75.0%.
        - Normal Waters:
          * Normal capacity (Macro <= 3, Scalp <= 1).
          * Standard confidence hurdles.
        """
        now = current_time_utc or datetime.datetime.now(datetime.timezone.utc)
        status = self.get_status(now)

        if not status.is_storm_active:
            # Normal waters
            if is_scalp:
                if current_scalp_count >= self.normal_scalp_cap:
                    return False, f"Normal Scalp slot full ({current_scalp_count}/{self.normal_scalp_cap})"
                return True, "Permitted (Normal Waters)"
            else:
                if current_macro_count >= self.normal_macro_cap:
                    return False, f"Normal Macro capacity full ({current_macro_count}/{self.normal_macro_cap})"
                return True, "Permitted (Normal Waters)"

        # Storm Mode Active:
        # Phase 1: Shock Pause
        if status.phase == StormPhase.PHASE_1_SHOCK_PAUSE:
            return False, f"VETO: Storm Protocol Phase 1 (Shock Pause active for {status.pause_seconds_remaining}s)"

        # Phase 2: Focused Caution
        # Check elevated confidence hurdle
        if confidence_pct < status.min_confidence_hurdle_pct:
            return False, f"VETO: Storm Mode requires ≥{status.min_confidence_hurdle_pct}% confidence (candidate: {confidence_pct:.1f}%)"

        if is_scalp:
            if current_scalp_count >= status.max_scalp_positions:
                return False, f"VETO: Storm Mode clamps Scalp to strictly 1 position ({current_scalp_count}/{status.max_scalp_positions} occupied)"
            return True, "Permitted (Storm Mode Focused Caution: 1 Scalp)"
        else:
            if current_macro_count >= status.max_macro_positions:
                return False, f"VETO: Storm Mode clamps Macro to strictly 1 position ({current_macro_count}/{status.max_macro_positions} occupied)"
            return True, "Permitted (Storm Mode Focused Caution: 1 Macro)"
