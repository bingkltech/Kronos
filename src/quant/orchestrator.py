"""
src/quant/orchestrator.py — Master Quantitative Multi-Agent Orchestrator.

Ties together all specialized quant agents into a cohesive asynchronous trading loop:
1. NewsCatalystSpecialist (Qualitative Event Shield)
2. CryptoIndexEngine (Top-10 Screener & Market Breadth)
3. CryptoCarrySpecialist (8h Funding Rate & Carry Monitor)
4. LearningGovernor (Brier Calibration & Lessons DB Memory)
5. KronosTrajectoryEngine (Autoregressive 12h Trajectory & Dynamic ATR Brackets)
6. KEVSupremeArbiter (6-Point Supreme Veto Gate & Fractional Kelly Sizing)
7. BinanceAtomicExecutor (Zero-Float Atomic Bracket Gateway & 12h Temporal Exit)

Strictly adheres to:
- AGENTS.md Invariant 1: Zero Float Financial Math (decimal.Decimal everywhere).
- AGENTS.md Invariant 2: Context Slicing Contract (df.iloc[-512:].copy()).
- AGENTS.md Invariant 3: Base Checkpoint Immutability.
"""

import os
import sys
import time
import datetime
import logging
from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Dict, List, Optional, Any
import pandas as pd

logger = logging.getLogger("QuantBotOrchestrator")

from src.quant.config import TOP_10_SYMBOLS, DEFAULT_RISK_CONFIG, FuturesSymbolConfig, GlobalRiskConfig, LIVE_EXCLUDED_SYMBOLS
from src.quant.macro_specialists import (
    NewsCatalystSpecialist,
    CryptoCarrySpecialist,
    NewsBlackoutVerdict,
    CarryVerdict,
    SessionLiquiditySpecialist,
    SessionLiquidityVerdict
)
from src.quant.crypto_index_engine import CryptoIndexEngine, MacroIndexVerdict
from src.quant.kronos_onnx_engine import KronosTrajectoryEngine, TrajectoryVerdict
from src.quant.kev_risk_arbiter import KEVSupremeArbiter, KEVDecision, TradeTicket
from src.quant.learning_governor import LearningGovernor, CalibrationReport, TradeOutcome
from src.quant.binance_execution import BinanceAtomicExecutor, ActiveBracketPosition, PositionState
from src.quant.volume_profile import (
    DailyVolumeProfileCache,
    VolumeProfileEngine,
    VolumeProfileSnapshot,
)
from src.quant.tiger_scout_bridge import TigerScoutBridge, PreyNanoTelemetry, TigerScoutReport


@dataclass(frozen=True)
class CycleReport:
    """Summary record of an hourly scan cycle."""
    timestamp_utc: datetime.datetime
    news_verdict: NewsBlackoutVerdict
    macro_verdict: MacroIndexVerdict
    calibration_report: CalibrationReport
    decisions: Dict[str, KEVDecision]
    dispatched_trades: List[ActiveBracketPosition]


class QuantBotOrchestrator:
    """
    Master pipeline orchestrator coordinating the multi-agent trading loop.
    """

    def __init__(
        self,
        news_specialist: Optional[NewsCatalystSpecialist] = None,
        index_engine: Optional[CryptoIndexEngine] = None,
        carry_specialist: Optional[CryptoCarrySpecialist] = None,
        session_specialist: Optional[SessionLiquiditySpecialist] = None,
        trajectory_engine: Optional[KronosTrajectoryEngine] = None,
        risk_arbiter: Optional[KEVSupremeArbiter] = None,
        learning_governor: Optional[LearningGovernor] = None,
        executor: Optional[BinanceAtomicExecutor] = None,
        symbols_config: Optional[Dict[str, FuturesSymbolConfig]] = None,
        risk_config: Optional[GlobalRiskConfig] = None,
        cooldown_seconds: int = 900,
        volume_profile_cache: Optional[DailyVolumeProfileCache] = None,
        enable_volume_profile_veto: bool = True,
        require_neural_model: bool = True,
        tiger_scout_bridge: Optional[TigerScoutBridge] = None,
        enable_tiger_scout: bool = True
    ):
        self.symbols_config = symbols_config or TOP_10_SYMBOLS
        self.risk_config = risk_config or DEFAULT_RISK_CONFIG
        self.cooldown_seconds = cooldown_seconds
        self.volume_profile_cache = volume_profile_cache or DailyVolumeProfileCache()
        self.enable_volume_profile_veto = enable_volume_profile_veto
        self.require_neural_model = require_neural_model
        self.enable_tiger_scout = enable_tiger_scout
        self.tiger_scout_bridge = tiger_scout_bridge or (TigerScoutBridge() if enable_tiger_scout else None)

        # Post-Exit Quarantine / Cooldown tracker (symbol -> {expires_utc, reason, ...})
        self.symbol_cooldowns: Dict[str, Dict[str, Any]] = {}
        self._previous_active_symbols: set = set()
        # Directional Flip Hysteresis tracker (symbol -> {side, timestamp_utc})
        self.recent_directional_exits: Dict[str, Dict[str, Any]] = {}

        self.news_specialist = news_specialist or NewsCatalystSpecialist()
        self.session_specialist = session_specialist or SessionLiquiditySpecialist()
        self.index_engine = index_engine or CryptoIndexEngine(symbols_config=self.symbols_config)
        self.carry_specialist = carry_specialist or CryptoCarrySpecialist()
        self.trajectory_engine = trajectory_engine or KronosTrajectoryEngine(symbols_config=self.symbols_config)
        self.risk_arbiter = risk_arbiter or KEVSupremeArbiter(risk_config=self.risk_config, symbols_config=self.symbols_config)
        self.learning_governor = learning_governor or LearningGovernor()
        self.executor = executor or BinanceAtomicExecutor(dry_run=True, realistic_friction=True, symbols_config=self.symbols_config)
        self.contra_mode: bool = False

    def set_contra_mode(self, enabled: bool) -> None:
        """Set Contra Trading Mode across orchestrator and executor."""
        self.contra_mode = bool(enabled)
        if self.executor:
            self.executor.contra_mode = bool(enabled)

    def register_symbol_cooldown(
        self,
        symbol: str,
        current_time_utc: datetime.datetime,
        duration_seconds: Optional[int] = None,
        reason: str = "POST_EXIT_COOLDOWN"
    ) -> None:
        """
        Quarantines a symbol for a cooldown window after exit (manual, take-profit, or stop-loss).
        Prevents rapid churn, double-fee bleeding, and shorting the local mean-reversion bottom.
        """
        dur = duration_seconds if duration_seconds is not None else self.cooldown_seconds
        expires_utc = current_time_utc + datetime.timedelta(seconds=dur)
        self.symbol_cooldowns[symbol] = {
            "expires_utc": expires_utc,
            "duration_seconds": dur,
            "reason": reason,
            "registered_at_utc": current_time_utc
        }

    def is_symbol_in_cooldown(self, symbol: str, current_time_utc: datetime.datetime) -> bool:
        """Returns True if the symbol is actively quarantined under post-exit cooldown."""
        if symbol not in self.symbol_cooldowns:
            return False
        info = self.symbol_cooldowns[symbol]
        if current_time_utc < info["expires_utc"]:
            return True
        # Cooldown expired, clean up entry
        del self.symbol_cooldowns[symbol]
        return False

    def get_cooldown_status(self, current_time_utc: Optional[datetime.datetime] = None) -> Dict[str, Any]:
        """Returns map of actively quarantined symbols and remaining seconds."""
        now_u = current_time_utc or datetime.datetime.now(datetime.timezone.utc)
        active = {}
        for sym, info in list(self.symbol_cooldowns.items()):
            if now_u < info["expires_utc"]:
                remaining = int((info["expires_utc"] - now_u).total_seconds())
                active[sym] = {
                    "remaining_seconds": remaining,
                    "expires_utc": info["expires_utc"].isoformat(),
                    "reason": info["reason"]
                }
            else:
                del self.symbol_cooldowns[sym]
        return active

    def record_directional_loss(self, symbol: str, side: str, timestamp_utc: datetime.datetime) -> None:
        """Records a loss exit to enforce 30-minute directional flip hysteresis."""
        self.recent_directional_exits[symbol] = {
            "side": side.upper(),
            "timestamp_utc": timestamp_utc
        }

    @property
    def kev_arbiter(self) -> KEVSupremeArbiter:
        """Alias for risk_arbiter (KEVSupremeArbiter instance)."""
        return self.risk_arbiter

    def run_scan_cycle(
        self,
        account_equity: Optional[Decimal] = None,
        lookback_data_map: Optional[Dict[str, pd.DataFrame]] = None,
        current_time_utc: Optional[datetime.datetime] = None,
        mock_preloaded_klines: Optional[Dict[str, List[Dict[str, Decimal]]]] = None,
        mock_trajectories: Optional[Dict[str, TrajectoryVerdict]] = None,
        mock_volume_profiles: Optional[Dict[str, VolumeProfileSnapshot]] = None,
        execution_mode: str = "PAPER",
        max_new_entries: Optional[int] = None
    ) -> CycleReport:
        """
        Execute an end-to-end market scan across the Top 10 universe.
        Supports both PAPER simulation and real LIVE execution.
        """
        if current_time_utc is None:
            current_time_utc = datetime.datetime.now(datetime.timezone.utc)

        if execution_mode == "LIVE":
            live_summary = self.executor.get_live_account_summary()
            if account_equity is None:
                account_equity = live_summary.get("total_wallet_balance_usd", Decimal("0.00"))
                if account_equity <= Decimal("0"):
                    account_equity = self.risk_config.small_account_threshold
            active_symbols = [p["symbol"] for p in live_summary.get("positions", [])]
            free_margin = live_summary.get("available_balance_usd", account_equity)
            self.kev_arbiter.use_bnb_fee_discount = live_summary.get("bnb_fee_discount_active", False)
        else:
            if account_equity is None:
                account_equity = self.executor.get_current_equity()
            active_symbols = [
                pos.symbol for pos in self.executor.active_positions.values()
                if pos.state == PositionState.BRACKETS_ACTIVE
            ]
            free_margin = self.executor.get_free_margin()

        # 1. Macro News Blackout & Session Liquidity Shields
        news_verdict = self.news_specialist.evaluate_blackout(current_time_utc)
        session_verdict = self.session_specialist.evaluate_session(current_time_utc)

        # 2. Systemic Market Breadth & Macro Regime
        macro_verdict = self.index_engine.evaluate_universe(preloaded_klines=mock_preloaded_klines)

        # 3. Model Calibration & Confidence Multiplier
        calib_report = self.learning_governor.calculate_brier_calibration()
        confidence_multiplier = calib_report.confidence_multiplier

        # 4. Carry & Funding Rates
        funding_map = self.carry_specialist.fetch_funding_rates() if not mock_trajectories else {}

        # 4b. Evaluate active positions for TP/SL hits and temporal expiry
        if execution_mode == "PAPER":
            current_prices = {
                sym: stats.current_price
                for sym, stats in macro_verdict.symbol_stats.items()
            }
            closed_by_price = self.executor.check_bracket_price_triggers(current_prices, current_time_utc=current_time_utc)
            for pos in closed_by_price:
                hit = 1 if pos.close_reason == "TAKE_PROFIT_TRIGGERED" else 0
                is_loss = (hit == 0 and pos.realized_pnl_usd < Decimal("0"))
                cd_dur = 1800 if is_loss else self.cooldown_seconds
                self.register_symbol_cooldown(
                    pos.symbol,
                    pos.close_time_utc or current_time_utc,
                    duration_seconds=cd_dur,
                    reason=f"POST_{pos.close_reason or 'EXIT'}_COOLDOWN"
                )
                if is_loss:
                    self.record_directional_loss(pos.symbol, pos.side, pos.close_time_utc or current_time_utc)
                conf = getattr(pos, "forecast_confidence", Decimal("0.65"))
                self.learning_governor.record_outcome(TradeOutcome(
                    trade_id=pos.position_id,
                    symbol=pos.symbol,
                    side=pos.side,
                    forecast_confidence=conf,
                    realized_hit=hit,
                    realized_pnl_usd=pos.realized_pnl_usd,
                    exit_reason=pos.close_reason or "BRACKET_EXIT",
                    timestamp_utc=pos.close_time_utc or current_time_utc,
                    execution_mode="PAPER"
                ))

            self.sweep_temporal_exits(current_time_utc=current_time_utc, current_prices=current_prices, execution_mode="PAPER")
        elif execution_mode == "LIVE":
            # Active Live Temporal Sweeper (Lesson #17: Hard 12-Hour Stale Expiry)
            self.sweep_temporal_exits(current_time_utc=current_time_utc, execution_mode="LIVE")

            # Post-Exit Quarantine Reflex: Detect positions that exited on exchange
            current_sym_set = set(active_symbols)
            if self._previous_active_symbols:
                exited_symbols = self._previous_active_symbols - current_sym_set
                for ex_sym in exited_symbols:
                    self.register_symbol_cooldown(
                        symbol=ex_sym,
                        current_time_utc=current_time_utc,
                        duration_seconds=self.cooldown_seconds,
                        reason="POST_BRACKET_EXIT_COOLDOWN"
                    )
                    logger.info(
                        "[POST-EXIT COOLDOWN] Exchange position closed on %s. %ds quarantine activated.",
                        ex_sym, self.cooldown_seconds
                    )
            self._previous_active_symbols = current_sym_set

            # Ingest recent live closed trades for directional flip hysteresis and cooldown
            try:
                for ct in getattr(self.executor, "closed_trades", [])[-15:]:
                    c_sym = ct.get("symbol")
                    c_side = ct.get("side")
                    c_time_str = ct.get("close_time") or ct.get("timestamp_utc")
                    pnl_dec = Decimal(str(ct.get("realized_pnl_usd", 0)))
                    is_loss = ct.get("result") == "LOSS" or pnl_dec < Decimal("0")
                    if c_sym and c_time_str:
                        c_dt = datetime.datetime.fromisoformat(str(c_time_str))
                        if c_dt.tzinfo is None:
                            c_dt = c_dt.replace(tzinfo=datetime.timezone.utc)
                        cd_duration = 1800 if is_loss else self.cooldown_seconds
                        elapsed = (current_time_utc - c_dt).total_seconds()
                        if 0.0 <= elapsed < float(cd_duration):
                            if not self.is_symbol_in_cooldown(c_sym, current_time_utc):
                                self.register_symbol_cooldown(
                                    c_sym,
                                    c_dt,
                                    duration_seconds=cd_duration,
                                    reason="POST_STOP_LOSS_COOLDOWN" if is_loss else "POST_TAKE_PROFIT_COOLDOWN"
                                )
                        if is_loss and c_side:
                            self.record_directional_loss(c_sym, c_side, c_dt)
            except Exception as e:
                logger.debug("Error ingesting recent live losses: %s", e)

        # 5. Check Active Positions & Capacity
        decisions: Dict[str, KEVDecision] = {}
        dispatched_trades: List[ActiveBracketPosition] = []

        # If news blackout or circuit breaker halt is active, skip all new entries
        if news_verdict.is_blackout or calib_report.status == "HALTED":
            return CycleReport(
                timestamp_utc=current_time_utc,
                news_verdict=news_verdict,
                macro_verdict=macro_verdict,
                calibration_report=calib_report,
                decisions=decisions,
                dispatched_trades=dispatched_trades
            )

        # 6. Evaluate Candidates in Universe
        candidate_symbols = list(self.symbols_config.keys())

        # 6a. Stalking Tiger Dynamic Hot Prey Scouting Injection
        if self.enable_tiger_scout and self.tiger_scout_bridge:
            try:
                scouted_prey = self.tiger_scout_bridge.get_scouted_prey_candidates(
                    existing_universe=candidate_symbols,
                    max_candidates=2,
                    min_turnover_usd=Decimal("50000000.00")
                )
                for prey in scouted_prey:
                    sym = prey.symbol
                    if sym not in candidate_symbols:
                        # Dynamically resolve precision and register symbol config
                        p_prec, q_prec = self.executor._resolve_symbol_precision(sym)
                        dyn_cfg = FuturesSymbolConfig(
                            symbol=sym,
                            price_precision=p_prec,
                            quantity_precision=q_prec,
                            min_quantity=Decimal("10") ** -q_prec,
                            min_notional=Decimal("5.0"),
                            taker_fee_rate=Decimal("0.0005"),
                            maker_fee_rate=Decimal("0.0002"),
                            est_slippage_rate=Decimal("0.0003")
                        )
                        self.symbols_config[sym] = dyn_cfg
                        if self.risk_arbiter and hasattr(self.risk_arbiter, "symbols_config"):
                            self.risk_arbiter.symbols_config[sym] = dyn_cfg
                        if self.executor and hasattr(self.executor, "symbols_config"):
                            self.executor.symbols_config[sym] = dyn_cfg
                        if self.trajectory_engine and hasattr(self.trajectory_engine, "symbols_config"):
                            self.trajectory_engine.symbols_config[sym] = dyn_cfg

                        candidate_symbols.append(sym)
                        logger.info(
                            f"[TIGER-SCOUT] Dynamically injected Hot Prey candidate: {sym} "
                            f"(Rank #{prey.rank}, 24h Vol: ${prey.turnover_24h_usd:,.0f}, Dynamic Strength: {prey.dynamic_strength_pct}%)"
                        )
            except Exception as e:
                logger.debug("Failed to ingest Tiger scouted prey: %s", e)

        for symbol in candidate_symbols:
            # Skip if already holding a position
            if symbol in active_symbols:
                continue

            # Live fleet pruning (Lesson #40): Veto toxic meme coins in live mode
            if execution_mode == "LIVE" and symbol in LIVE_EXCLUDED_SYMBOLS:
                decisions[symbol] = KEVDecision(
                    approved=False,
                    symbol=symbol,
                    side="NEUTRAL",
                    veto_gate_failed="FLEET_PRUNING",
                    veto_reason=f"{symbol} is excluded from live execution to prevent meme whipsaw (Lesson #40).",
                    ticket=None,
                    adversarial_notes="Excluded asset to preserve capital for high-alpha fleet."
                )
                continue

            # Session Timing Gate (Lesson #38 & #40): Protects against US Cash Open & Late Night funding whipsaws
            if not session_verdict.is_entry_permitted:
                decisions[symbol] = KEVDecision(
                    approved=False,
                    symbol=symbol,
                    side="NEUTRAL",
                    veto_gate_failed="SESSION_LIQUIDITY_GUARD",
                    veto_reason=session_verdict.reason,
                    ticket=None,
                    adversarial_notes="Session timing guard active."
                )
                continue

            # Post-Exit Quarantine Check: Veto if symbol is cooling down after recent exit
            if self.is_symbol_in_cooldown(symbol, current_time_utc):
                expires_str = self.symbol_cooldowns[symbol]["expires_utc"].strftime("%H:%M:%S UTC")
                decisions[symbol] = KEVDecision(
                    approved=False,
                    symbol=symbol,
                    side="NEUTRAL",
                    veto_gate_failed="POST_EXIT_COOLDOWN",
                    veto_reason=f"Symbol in post-exit quarantine cooldown until {expires_str} (prevents churn & mean-reversion whipsaw).",
                    ticket=None,
                    adversarial_notes="Cooldown active to protect banked profits."
                )
                continue

            # Fail-Safe Neural Model Gate (Lesson #41): Prohibit unverified linear fallback in LIVE mode
            if self.require_neural_model and execution_mode == "LIVE" and not mock_trajectories and not self.trajectory_engine.is_neural_model_loaded():
                decisions[symbol] = KEVDecision(
                    approved=False,
                    symbol=symbol,
                    side="NEUTRAL",
                    veto_gate_failed="NEURAL_MODEL_OFFLINE",
                    veto_reason="VETO: Kronos Foundation Neural Model is offline/unloaded in WebUI. Fallback linear momentum extrapolation strictly prohibited in LIVE mode.",
                    ticket=None,
                    adversarial_notes="Fail-safe safety gate: Real neural model must be loaded into memory."
                )
                continue

            # Obtain or compute Trajectory
            if mock_trajectories and symbol in mock_trajectories:
                trajectory = mock_trajectories[symbol]
            elif lookback_data_map and symbol in lookback_data_map:
                df = lookback_data_map[symbol]
                trajectory = self.trajectory_engine.generate_trajectory(symbol, df)
            elif not mock_trajectories:
                df = self.index_engine.fetch_lookback_dataframe(symbol)
                if df is not None and len(df) >= 15:
                    trajectory = self.trajectory_engine.generate_trajectory(symbol, df)
                else:
                    continue
            else:
                continue

            if trajectory.proposed_side == "NEUTRAL":
                continue

            # Directional Flip Hysteresis (Lesson #41): Veto opposite-direction entries within 30m of a loss
            # Exception: Systemic regime surge (breadth >= 70% in BULL_EXPANSION for BUY, or <= 20% in BEAR_DISTRIBUTION for SELL)
            if symbol in self.recent_directional_exits:
                exit_info = self.recent_directional_exits[symbol]
                last_side = exit_info["side"]
                last_time = exit_info["timestamp_utc"]
                prop_side = "BUY" if trajectory.proposed_side == "LONG" else "SELL"
                if prop_side != last_side:
                    diff_m = (current_time_utc - last_time).total_seconds() / 60.0
                    if 0.0 <= diff_m < 30.0:
                        regime_override = False
                        if prop_side == "BUY" and macro_verdict.macro_regime == "BULL_EXPANSION" and macro_verdict.breadth_ratio >= Decimal("0.70"):
                            regime_override = True
                            logger.info(
                                "[REGIME_OVERRIDE] Directional flip lockout overridden for %s BUY: Breadth=%.1f%% in BULL_EXPANSION",
                                symbol, float(macro_verdict.breadth_ratio * Decimal("100"))
                            )
                        elif prop_side == "SELL" and macro_verdict.macro_regime == "BEAR_DISTRIBUTION" and macro_verdict.breadth_ratio <= Decimal("0.20"):
                            regime_override = True
                            logger.info(
                                "[REGIME_OVERRIDE] Directional flip lockout overridden for %s SELL: Breadth=%.1f%% in BEAR_DISTRIBUTION",
                                symbol, float(macro_verdict.breadth_ratio * Decimal("100"))
                            )

                        if not regime_override:
                            decisions[symbol] = KEVDecision(
                                approved=False,
                                symbol=symbol,
                                side="NEUTRAL",
                                veto_gate_failed="DIRECTIONAL_FLIP_HYSTERESIS",
                                veto_reason=f"VETO: Directional flip ({last_side} -> {prop_side}) blocked for 30m after loss (elapsed: {diff_m:.1f}m). Prevents whipsaw.",
                                ticket=None,
                                adversarial_notes="Anti-whipsaw directional hysteresis active."
                            )
                            continue
                        else:
                            del self.recent_directional_exits[symbol]
                    else:
                        del self.recent_directional_exits[symbol]

            # Spatial Liquidity Veto Gate (Previous-UTC-Day Volume Profile H1+H4):
            # Veto entries firing directly into opposing pPOC (0.05-0.80%) or inside HVN chop (>=1.5x avg).
            # In offline mock tests without mock_volume_profiles, skip live HTTP fetch for determinism.
            if self.enable_volume_profile_veto:
                vp_snapshot: Optional[VolumeProfileSnapshot] = None
                if mock_volume_profiles is not None:
                    vp_snapshot = mock_volume_profiles.get(symbol)
                elif not mock_trajectories:
                    vp_snapshot = self.volume_profile_cache.get_previous_day_profile(symbol, current_time_utc)

                if vp_snapshot is not None:
                    prop_side_vp = "BUY" if trajectory.proposed_side == "LONG" else "SELL"
                    vp_res = VolumeProfileEngine.evaluate_spatial_veto(
                        profile=vp_snapshot,
                        entry_price=trajectory.current_price,
                        side=prop_side_vp,
                        veto_firing_into_poc=True,
                        veto_hvn_chop=True,
                        veto_fading_breakout=False,
                    )
                    if not vp_res.approved:
                        decisions[symbol] = KEVDecision(
                            approved=False,
                            symbol=symbol,
                            side="NEUTRAL",
                            veto_gate_failed=vp_res.veto_code or "VP_SPATIAL_VETO",
                            veto_reason=vp_res.reason,
                            ticket=None,
                            adversarial_notes="Empirically validated prior-UTC-day Volume Profile spatial liquidity guard (p=0.0034)."
                        )
                        continue

            # Carry Verdict
            if symbol not in funding_map and not mock_trajectories:
                try:
                    dyn_funding = self.carry_specialist.fetch_funding_rates(symbol=symbol)
                    if dyn_funding and symbol in dyn_funding:
                        funding_map[symbol] = dyn_funding[symbol]
                except Exception as e:
                    logger.debug("Dynamic funding fetch failed for %s: %s", symbol, e)

            sym_funding = funding_map.get(symbol, {}).get("funding_rate", Decimal("0.0001"))
            next_funding_time = funding_map.get(symbol, {}).get("next_funding_time")
            carry_verdict = self.carry_specialist.evaluate_carry(
                symbol=symbol,
                side=trajectory.proposed_side,
                funding_rate=sym_funding,
                next_funding_time=next_funding_time
            )

            # Candidate Confidence Multiplier & Nano-Orderflow Confluence Evaluation
            candidate_confidence_multiplier = confidence_multiplier
            nano_adv_note = ""
            if self.enable_tiger_scout and self.tiger_scout_bridge:
                try:
                    _, nano_mult, nano_note = self.tiger_scout_bridge.evaluate_nano_confluence(
                        symbol=symbol,
                        proposed_side=trajectory.proposed_side
                    )
                    if nano_mult != Decimal("1.00"):
                        candidate_confidence_multiplier = (candidate_confidence_multiplier * nano_mult).quantize(Decimal("0.0001"))
                        nano_adv_note = nano_note
                        logger.info(
                            f"[NANO-CONFLUENCE] {symbol} {trajectory.proposed_side}: {nano_note} "
                            f"(Confidence Multiplier: {confidence_multiplier} -> {candidate_confidence_multiplier}x)"
                        )
                except Exception as e:
                    logger.debug("Nano confluence check warning for %s: %s", symbol, e)

            # 7. KEV.ai Supreme Veto Gate & Kelly Sizing
            if execution_mode != "LIVE":
                free_margin = self.executor.get_free_margin()
            decision = self.risk_arbiter.evaluate_candidate(
                trajectory=trajectory,
                news_verdict=news_verdict,
                macro_index=macro_verdict,
                carry_verdict=carry_verdict,
                account_equity=account_equity,
                active_positions=active_symbols,
                confidence_multiplier=candidate_confidence_multiplier,
                free_margin=free_margin
            )
            if nano_adv_note:
                existing_notes = decision.adversarial_notes or ""
                updated_notes = f"{existing_notes} | {nano_adv_note}" if existing_notes else nano_adv_note
                decision = replace(decision, adversarial_notes=updated_notes)
            decisions[symbol] = decision

            # 8. Dispatch Approved Trades
            if decision.approved and decision.ticket:
                # Tsunami Storm Protocol Gate
                try:
                    from src.quant.storm_protocol import StormProtocolManager
                    storm_mgr = StormProtocolManager()
                    btc_cand_klines = mock_preloaded_klines.get("BTCUSDT") if mock_preloaded_klines else None
                    storm_mgr.evaluate_market_wave(
                        btc_klines=btc_cand_klines,
                        macro_breadth_pct=macro_verdict.advance_decline_ratio * Decimal("100") if macro_verdict.advance_decline_ratio else None,
                        is_news_blackout=news_verdict.is_blackout,
                        news_event_name=news_verdict.event_name,
                        current_time_utc=current_time_utc
                    )
                    conf_pct = float(getattr(decision.ticket, "forecast_confidence", Decimal("0.65")) * Decimal("100"))
                    scalp_cnt = len(getattr(self.executor, "scalp_active_symbols", set()))
                    permitted, storm_reason = storm_mgr.is_entry_permitted(
                        is_scalp=False,
                        current_macro_count=len(active_symbols),
                        current_scalp_count=scalp_cnt,
                        confidence_pct=conf_pct,
                        current_time_utc=current_time_utc
                    )
                    if not permitted:
                        decisions[symbol] = replace(
                            decision,
                            approved=False,
                            veto_gate_failed="STORM_PROTOCOL",
                            veto_reason=storm_reason,
                        )
                        continue
                except Exception as storm_err:
                    logger.debug("Storm protocol check warning: %s", storm_err)

                if execution_mode == "LIVE":
                    p_state, m_snap = (None, None)
                    if getattr(self.executor, "risk_engine", None) is not None and hasattr(self.executor, "fetch_live_risk_snapshots"):
                        p_state, m_snap = self.executor.fetch_live_risk_snapshots(
                            symbol=decision.ticket.symbol,
                            fallback_price=decision.ticket.entry_price,
                            live_summary=live_summary,
                        )
                    pos = self.executor.submit_live_bracket_order(
                        decision.ticket,
                        portfolio_state=p_state,
                        market_snapshot=m_snap,
                    )
                else:
                    pos = self.executor.submit_bracket_order(decision.ticket, fill_time_utc=current_time_utc)
                if pos.state != PositionState.REJECTED:
                    dispatched_trades.append(pos)
                    active_symbols.append(symbol)
                    if execution_mode == "LIVE" and decision.ticket:
                        lev = Decimal(str(decision.ticket.effective_leverage or 2))
                        used = (pos.quantity * pos.entry_price) / lev
                        free_margin = max(Decimal("0.00"), free_margin - used)
                else:
                    decisions[symbol] = replace(
                        decision,
                        approved=False,
                        veto_gate_failed="ORDER_REJECTED",
                        veto_reason=f"ORDER_REJECTED: {pos.close_reason}",
                    )

                # Stop scanning if max concurrent positions or session trade quota reached
                if len(active_symbols) >= self.risk_config.max_concurrent_positions:
                    break
                if max_new_entries is not None and len(dispatched_trades) >= max_new_entries:
                    break

        return CycleReport(
            timestamp_utc=current_time_utc,
            news_verdict=news_verdict,
            macro_verdict=macro_verdict,
            calibration_report=calib_report,
            decisions=decisions,
            dispatched_trades=dispatched_trades
        )

    def sweep_temporal_exits(
        self,
        current_time_utc: Optional[datetime.datetime] = None,
        current_prices: Optional[Dict[str, Decimal]] = None,
        execution_mode: str = "PAPER"
    ) -> List[str]:
        """Check all active positions for 12h stale expiry, close them at market, and record learning outcome."""
        expired_ids = []
        now_u = current_time_utc or datetime.datetime.now(datetime.timezone.utc)

        if execution_mode == "LIVE":
            live_expired = self.executor.sweep_live_temporal_exits(
                current_time_utc=now_u,
                max_duration_hours=self.risk_config.stale_trade_hours
            )
            for item in live_expired:
                sym = item["symbol"]
                expired_ids.append(f"LIVE_{sym}")
                self.register_symbol_cooldown(sym, now_u, reason="TEMPORAL_EXIT_12H_STALE")
                self.learning_governor.record_outcome(TradeOutcome(
                    trade_id=f"LIVE_EXPIRED_{sym}_{int(time.time())}",
                    symbol=sym,
                    side=item["side"],
                    forecast_confidence=Decimal("0.70"),
                    realized_hit=1 if item["unrealized_pnl_usd"] > Decimal("0") else 0,
                    realized_pnl_usd=item["unrealized_pnl_usd"],
                    exit_reason="TEMPORAL_EXIT_12H_STALE",
                    timestamp_utc=now_u,
                    execution_mode="LIVE"
                ))
            return expired_ids

        # PAPER execution mode
        prices = current_prices or {}
        for pos_id, pos in list(self.executor.active_positions.items()):
            px = prices.get(pos.symbol)
            if self.executor.evaluate_temporal_exit(pos, current_time_utc=now_u, max_duration_hours=self.risk_config.stale_trade_hours, current_price=px):
                expired_ids.append(pos_id)
                self.register_symbol_cooldown(pos.symbol, now_u, reason="TEMPORAL_EXIT_12H_STALE")
                self.learning_governor.record_outcome(TradeOutcome(
                    trade_id=pos.position_id,
                    symbol=pos.symbol,
                    side=pos.side,
                    forecast_confidence=Decimal("0.70"),
                    realized_hit=1 if pos.realized_pnl_usd > Decimal("0") else 0,
                    realized_pnl_usd=pos.realized_pnl_usd,
                    exit_reason="TEMPORAL_EXIT_12H_STALE",
                    timestamp_utc=pos.close_time_utc or now_u,
                    execution_mode="PAPER"
                ))
        return expired_ids
