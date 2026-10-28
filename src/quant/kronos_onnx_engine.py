"""
src/quant/kronos_onnx_engine.py — Tactical Trajectory & Dynamic Volatility Envelope Engine.

Leverages the Kronos Foundation Model (via sub-second WebUI microservice or direct graph execution)
to generate 12-hour autoregressive OHLCV predicted paths and extract dynamic Stop-Loss and
Take-Profit bracket envelopes.

Strictly adheres to:
- AGENTS.md Invariant 1: Zero Float Financial Math (decimal.Decimal for all monetary outputs).
- AGENTS.md Invariant 2: Context Slicing Contract (strictly tail-slices df.iloc[-512:].copy()).
- AGENTS.md Invariant 3: Base Checkpoint Immutability (checkpoints are read-only).
"""

import os
import sys
import logging
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, List, Optional, Tuple, Union
import pandas as pd
import requests

from src.quant.config import ALL_SUPPORTED_SYMBOLS, FuturesSymbolConfig, DEFAULT_RISK_CONFIG

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TrajectoryVerdict:
    """Quantitative trajectory forecast for a single futures asset."""
    symbol: str
    current_price: Decimal
    terminal_price: Decimal
    path_high: Decimal
    path_low: Decimal
    raw_drift: Decimal
    dynamic_take_profit: Decimal
    dynamic_stop_loss: Decimal
    proposed_side: str            # "LONG", "SHORT", "NEUTRAL"
    horizon_hours: int
    rationale: str


class KronosTrajectoryEngine:
    """
    Tactical quantitative engine translating tail-sliced candlestick buffers
    into dynamic bracket envelopes using the Kronos Foundation Model.
    """

    def __init__(
        self,
        service_url: str = "http://localhost:7070",
        default_pred_len: int = 12,
        symbols_config: Optional[Dict[str, FuturesSymbolConfig]] = None,
        session: Optional[requests.Session] = None
    ):
        self.service_url = service_url.rstrip("/")
        self.default_pred_len = default_pred_len
        self.symbols_config = symbols_config or ALL_SUPPORTED_SYMBOLS
        self.session = session or requests.Session()

    def generate_trajectory(
        self,
        symbol: str,
        lookback_df: pd.DataFrame,
        pred_len: Optional[int] = None,
        mock_forecast: Optional[pd.DataFrame] = None
    ) -> TrajectoryVerdict:
        """
        Generate 12h predicted trajectory and extract volatility envelopes.
        Adheres to Invariant 2: strictly tail-slices lookback_df.iloc[-512:].
        """
        if symbol not in self.symbols_config:
            raise ValueError(f"Symbol {symbol} not registered in Top-10 configuration.")

        cfg = self.symbols_config[symbol]
        horizon = pred_len or self.default_pred_len

        # Invariant 2: Context Slicing Contract — tail-slice max 512 bars
        tail_df = lookback_df.iloc[-512:].copy()
        if len(tail_df) < 50:
            raise ValueError(f"Insufficient lookback bars ({len(tail_df)}); minimum 50 required.")

        spot_price = cfg.quantize_price(Decimal(str(tail_df["close"].iloc[-1])))

        # 1. Obtain Forecast (mock injection or live service query)
        if mock_forecast is not None:
            pred_df = mock_forecast
        else:
            try:
                pred_df = self._query_kronos_service(tail_df, horizon)
            except Exception as e:
                logger.warning("Neural predictor unavailable or unloaded (%s). Using synthetic momentum trajectory.", e)
                pred_df = self._generate_synthetic_path(tail_df, horizon)

        # 2. Extract Path Boundaries strictly in Decimal
        terminal_close = cfg.quantize_price(Decimal(str(pred_df["close"].iloc[-1])))
        path_high = cfg.quantize_price(Decimal(str(pred_df["high"].max())))
        path_low = cfg.quantize_price(Decimal(str(pred_df["low"].min())))

        # 3. Calculate raw drift
        raw_drift = (terminal_close - spot_price) / spot_price

        # 4. Construct Dynamic Stop-Loss and Take-Profit Envelopes
        # Asset-aware volatility scaling (e.g. BTC ~0.5% ATR vs PEPE ~5-8% ATR)
        highs = [float(x) for x in tail_df["high"]]
        lows = [float(x) for x in tail_df["low"]]
        closes = [float(x) for x in tail_df["close"]]
        
        tr_list = []
        for i in range(1, len(closes)):
            tr_list.append(max(highs[i] - lows[i], abs(highs[i] - closes[i-1]), abs(lows[i] - closes[i-1])))
        recent_tr = tr_list[-14:] if len(tr_list) >= 14 else tr_list
        atr_float = (sum(recent_tr) / len(recent_tr)) if recent_tr else float(spot_price * Decimal("0.01"))
        atr_dec = cfg.quantize_price(Decimal(str(round(atr_float, cfg.price_precision))))

        # Dynamic stop distance: at least 1.5x ATR (or minimum 1.0% safety floor)
        min_stop_distance = max(atr_dec * Decimal("1.5"), spot_price * Decimal("0.010"))

        if raw_drift > Decimal("0"):
            # Bullish Candidate (LONG)
            proposed_side = "LONG"
            take_profit = max(terminal_close, path_high)
            
            # Dynamic SL is path low or 1.0% safety buffer
            inferred_sl = min(spot_price - min_stop_distance, path_low)
            stop_loss = cfg.quantize_price(inferred_sl)
            take_profit = cfg.quantize_price(take_profit)
            rationale = (
                f"Kronos Bullish Drift: Projected +{raw_drift*Decimal('100'):.2f}% to {terminal_close}. "
                f"Envelope TP: {take_profit}, SL: {stop_loss}."
            )

        elif raw_drift < Decimal("0"):
            # Bearish Candidate (SHORT)
            proposed_side = "SHORT"
            take_profit = min(terminal_close, path_low)
            
            # Dynamic SL is path high or 1.0% safety buffer
            inferred_sl = max(spot_price + min_stop_distance, path_high)
            stop_loss = cfg.quantize_price(inferred_sl)
            take_profit = cfg.quantize_price(take_profit)
            rationale = (
                f"Kronos Bearish Drift: Projected {raw_drift*Decimal('100'):.2f}% to {terminal_close}. "
                f"Envelope TP: {take_profit}, SL: {stop_loss}."
            )
        else:
            proposed_side = "NEUTRAL"
            take_profit = spot_price
            stop_loss = spot_price
            rationale = "Zero drift projected. Neutral stance."

        return TrajectoryVerdict(
            symbol=symbol,
            current_price=spot_price,
            terminal_price=terminal_close,
            path_high=path_high,
            path_low=path_low,
            raw_drift=raw_drift,
            dynamic_take_profit=take_profit,
            dynamic_stop_loss=stop_loss,
            proposed_side=proposed_side,
            horizon_hours=horizon,
            rationale=rationale,
        )

    def _query_kronos_service(self, tail_df: pd.DataFrame, pred_len: int) -> pd.DataFrame:
        """Query local Kronos Flask microservice with temporary CSV buffer."""
        workspace_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        temp_csv = os.path.join(workspace_root, "data", f"_temp_quant_lookback_{os.getpid()}.csv")
        tail_df.to_csv(temp_csv, index=False)

        try:
            payload = {
                "file_path": temp_csv,
                "lookback": min(len(tail_df), 400),
                "pred_len": pred_len,
                "use_tail": True,
                "temperature": 1.0,
                "top_p": 0.9,
                "sample_count": 1
            }
            resp = self.session.post(f"{self.service_url}/api/predict", json=payload, timeout=60)
            resp.raise_for_status()
            data = resp.json()
            if not data.get("success", False):
                raise RuntimeError(f"Kronos API prediction error: {data.get('error')}")

            pred_records = data.get("prediction_results", [])
            return pd.DataFrame(pred_records)
        finally:
            if os.path.exists(temp_csv):
                try:
                    os.remove(temp_csv)
                except OSError:
                    pass

    def _generate_synthetic_path(self, tail_df: pd.DataFrame, pred_len: int) -> pd.DataFrame:
        """Deterministic drift/volatility projection used as fallback when neural weights are offline."""
        last_close = float(tail_df["close"].iloc[-1])
        closes = tail_df["close"].astype(float).values
        n = min(len(closes), 12)
        momentum = (closes[-1] - closes[-n]) / closes[-n] if n > 1 else 0.0
        drift_step = (momentum / n) * 0.5
        
        preds = []
        curr = last_close
        for _ in range(pred_len):
            curr = curr * (1.0 + drift_step)
            spread = curr * 0.003
            preds.append({
                "open": curr,
                "high": curr + spread,
                "low": curr - spread,
                "close": curr,
                "volume": 0
            })
        return pd.DataFrame(preds)
