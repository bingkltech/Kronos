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
import datetime
from dataclasses import dataclass
from decimal import Decimal
from typing import Dict, List, Optional, Any
import pandas as pd

from src.quant.config import TOP_10_SYMBOLS, DEFAULT_RISK_CONFIG, FuturesSymbolConfig, GlobalRiskConfig
from src.quant.macro_specialists import NewsCatalystSpecialist, CryptoCarrySpecialist, NewsBlackoutVerdict, CarryVerdict
from src.quant.crypto_index_engine import CryptoIndexEngine, MacroIndexVerdict
from src.quant.kronos_onnx_engine import KronosTrajectoryEngine, TrajectoryVerdict
from src.quant.kev_risk_arbiter import KEVSupremeArbiter, KEVDecision, TradeTicket
from src.quant.learning_governor import LearningGovernor, CalibrationReport, TradeOutcome
from src.quant.binance_execution import BinanceAtomicExecutor, ActiveBracketPosition, PositionState


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
        trajectory_engine: Optional[KronosTrajectoryEngine] = None,
        risk_arbiter: Optional[KEVSupremeArbiter] = None,
        learning_governor: Optional[LearningGovernor] = None,
        executor: Optional[BinanceAtomicExecutor] = None,
        symbols_config: Optional[Dict[str, FuturesSymbolConfig]] = None,
        risk_config: Optional[GlobalRiskConfig] = None
    ):
        self.symbols_config = symbols_config or TOP_10_SYMBOLS
        self.risk_config = risk_config or DEFAULT_RISK_CONFIG

        self.news_specialist = news_specialist or NewsCatalystSpecialist()
        self.index_engine = index_engine or CryptoIndexEngine(symbols_config=self.symbols_config)
        self.carry_specialist = carry_specialist or CryptoCarrySpecialist()
        self.trajectory_engine = trajectory_engine or KronosTrajectoryEngine(symbols_config=self.symbols_config)
        self.risk_arbiter = risk_arbiter or KEVSupremeArbiter(risk_config=self.risk_config, symbols_config=self.symbols_config)
        self.learning_governor = learning_governor or LearningGovernor()
        self.executor = executor or BinanceAtomicExecutor(dry_run=True)

    def run_scan_cycle(
        self,
        account_equity: Decimal,
        lookback_data_map: Optional[Dict[str, pd.DataFrame]] = None,
        current_time_utc: Optional[datetime.datetime] = None,
        mock_preloaded_klines: Optional[Dict[str, List[Dict[str, Decimal]]]] = None,
        mock_trajectories: Optional[Dict[str, TrajectoryVerdict]] = None
    ) -> CycleReport:
        """
        Execute an end-to-end market scan across the Top 10 universe.
        """
        if current_time_utc is None:
            current_time_utc = datetime.datetime.now(datetime.timezone.utc)

        # 1. Macro News Blackout Shield
        news_verdict = self.news_specialist.evaluate_blackout(current_time_utc)

        # 2. Systemic Market Breadth & Macro Regime
        macro_verdict = self.index_engine.evaluate_universe(preloaded_klines=mock_preloaded_klines)

        # 3. Model Calibration & Confidence Multiplier
        calib_report = self.learning_governor.calculate_brier_calibration()
        confidence_multiplier = calib_report.confidence_multiplier

        # 4. Carry & Funding Rates
        funding_map = self.carry_specialist.fetch_funding_rates() if not mock_trajectories else {}

        # 4b. Evaluate active positions for TP/SL hits and temporal expiry
        current_prices = {
            sym: stats.current_price
            for sym, stats in macro_verdict.symbol_stats.items()
        }
        closed_by_price = self.executor.check_bracket_price_triggers(current_prices, current_time_utc=current_time_utc)
        for pos in closed_by_price:
            hit = 1 if pos.close_reason == "TAKE_PROFIT_TRIGGERED" else 0
            self.learning_governor.record_outcome(TradeOutcome(
                trade_id=pos.position_id,
                symbol=pos.symbol,
                side=pos.side,
                forecast_confidence=Decimal("0.70"),
                realized_hit=hit,
                realized_pnl_usd=pos.realized_pnl_usd,
                exit_reason=pos.close_reason or "BRACKET_EXIT",
                timestamp_utc=pos.close_time_utc or current_time_utc
            ))

        self.sweep_temporal_exits(current_time_utc=current_time_utc)

        # 5. Check Active Positions & Capacity
        active_symbols = [
            pos.symbol for pos in self.executor.active_positions.values()
            if pos.state == PositionState.BRACKETS_ACTIVE
        ]

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
        for symbol in self.symbols_config.keys():
            # Skip if already holding a position
            if symbol in active_symbols:
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

            # Carry Verdict
            sym_funding = funding_map.get(symbol, {}).get("funding_rate", Decimal("0.0001"))
            next_funding_time = funding_map.get(symbol, {}).get("next_funding_time")
            carry_verdict = self.carry_specialist.evaluate_carry(
                symbol=symbol,
                side=trajectory.proposed_side,
                funding_rate=sym_funding,
                next_funding_time=next_funding_time
            )

            # 7. KEV.ai Supreme Veto Gate & Kelly Sizing
            decision = self.risk_arbiter.evaluate_candidate(
                trajectory=trajectory,
                news_verdict=news_verdict,
                macro_index=macro_verdict,
                carry_verdict=carry_verdict,
                account_equity=account_equity,
                active_positions=active_symbols,
                confidence_multiplier=confidence_multiplier
            )
            decisions[symbol] = decision

            # 8. Dispatch Approved Trades
            if decision.approved and decision.ticket:
                pos = self.executor.submit_bracket_order(decision.ticket, fill_time_utc=current_time_utc)
                dispatched_trades.append(pos)
                active_symbols.append(symbol)

                # Stop scanning if max concurrent positions reached
                if len(active_symbols) >= self.risk_config.max_concurrent_positions:
                    break

        return CycleReport(
            timestamp_utc=current_time_utc,
            news_verdict=news_verdict,
            macro_verdict=macro_verdict,
            calibration_report=calib_report,
            decisions=decisions,
            dispatched_trades=dispatched_trades
        )

    def sweep_temporal_exits(self, current_time_utc: Optional[datetime.datetime] = None) -> List[str]:
        """Check all active positions for 12h stale expiry and close them."""
        expired_ids = []
        for pos_id, pos in list(self.executor.active_positions.items()):
            if self.executor.evaluate_temporal_exit(pos, current_time_utc=current_time_utc, max_duration_hours=self.risk_config.stale_trade_hours):
                expired_ids.append(pos_id)
        return expired_ids
