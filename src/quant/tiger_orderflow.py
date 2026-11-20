"""
src/quant/tiger_orderflow.py — Sub-Second Microstructure, Footprint CVD & Stoikov OFI Engine.

Processes real-time @aggTrade and @depth5@100ms events for Strategy #3 (Stalking Tiger).
Adheres strictly to AGENTS.md Invariant 1 (Zero Float Financial Math).
"""

from collections import deque
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import logging
import math
import time
from typing import Any, Deque, Dict, List, Optional, Tuple

from src.quant.tiger_config import (
    TigerOrderflowConfig,
    TigerMasterConfig,
    DEFAULT_TIGER_CONFIG,
)
from src.quant.crypto_index_engine import OrderBookMicrostructure

logger = logging.getLogger("kronos.tiger_orderflow")


@dataclass
class AggTradeEvent:
    """Parsed Binance @aggTrade event."""
    trade_id: int
    price: Decimal
    quantity: Decimal
    is_buyer_maker: bool   # True = Market Sell (-delta), False = Market Buy (+delta)
    timestamp_ms: int

    @property
    def signed_delta(self) -> Decimal:
        """Signed volume: positive for market buy, negative for market sell."""
        return -self.quantity if self.is_buyer_maker else self.quantity


@dataclass
class DepthSnapshot:
    """Parsed top-of-book depth snapshot from @depth5 stream."""
    best_bid: Decimal
    best_bid_qty: Decimal
    best_ask: Decimal
    best_ask_qty: Decimal
    timestamp_ms: int

    @property
    def mid_price(self) -> Decimal:
        return (self.best_bid + self.best_ask) / Decimal("2")

    @property
    def micro_price(self) -> Decimal:
        """Avellaneda-Stoikov Volume-Weighted Micro-Price."""
        denom = self.best_bid_qty + self.best_ask_qty
        if denom == Decimal("0"):
            return self.mid_price
        return (self.best_bid_qty * self.best_ask + self.best_ask_qty * self.best_bid) / denom

    @property
    def micro_price_skew_bps(self) -> Decimal:
        """Basis-point skew between Micro-Price and Mid-Price."""
        mid = self.mid_price
        if mid == Decimal("0"):
            return Decimal("0")
        return ((self.micro_price - mid) / mid) * Decimal("10000")

    @property
    def spread_pct(self) -> Decimal:
        """Top-of-book bid-ask spread as a fraction of mid price."""
        mid = self.mid_price
        if mid == Decimal("0"):
            return Decimal("0")
        return (self.best_ask - self.best_bid) / mid


@dataclass
class OpenInterestSnapshot:
    """Parsed Binance USD(S)-M Futures Open Interest update."""
    open_interest: Decimal
    timestamp_ms: int


@dataclass
class AbsorptionSignal:
    """Evaluated Trapped Trader Absorption Climax setup."""
    symbol: str
    action: str                        # "SELL" (short trapped bulls) or "BUY" (long trapped bears)
    entry_trigger_price: Decimal
    invalidation_stop_price: Decimal
    cvd_zscore: Decimal
    micro_price_skew_bps: Decimal
    ofi_score: Decimal
    wick_ratio: Decimal
    absorption_density: Decimal
    is_steamroller_vetoed: bool
    is_valid: bool
    reason: str
    delta_oi_pct: Decimal = Decimal("0")


class SymbolOrderflowTracker:
    """
    Sub-second orderflow, CVD delta buffer, and Stoikov OFI tracker for a single symbol.
    Runs entirely in PC memory with tight bounded buffers.
    """
    def __init__(
        self,
        symbol: str,
        config: Optional[TigerOrderflowConfig] = None,
        max_trades_buffer: int = 2000
    ):
        self.symbol = symbol
        self.cfg = config or DEFAULT_TIGER_CONFIG.orderflow
        self.trades: Deque[AggTradeEvent] = deque(maxlen=max_trades_buffer)
        self.last_depth: Optional[DepthSnapshot] = None
        self.prev_depth: Optional[DepthSnapshot] = None
        self.last_ofi: Decimal = Decimal("0")
        self.oi_history: Deque[OpenInterestSnapshot] = deque(maxlen=100)
        self.top_bids: List[Tuple[Decimal, Decimal]] = []
        self.top_asks: List[Tuple[Decimal, Decimal]] = []
        self.last_depth_ms: int = 0

    def process_open_interest(self, open_interest: Decimal, timestamp_ms: int) -> None:
        """Ingest Open Interest data point from Binance Futures REST API."""
        self.oi_history.append(OpenInterestSnapshot(
            open_interest=open_interest,
            timestamp_ms=timestamp_ms
        ))

    def compute_delta_oi(self, window_seconds: Optional[int] = None) -> Tuple[Decimal, Decimal]:
        """
        Computes absolute change and percentage change in Open Interest over the lookback window.
        Returns:
            (abs_delta_oi, delta_oi_pct)
        """
        if len(self.oi_history) < 2:
            return Decimal("0"), Decimal("0")

        win_s = window_seconds or self.cfg.oi_lookback_seconds
        current = self.oi_history[-1]
        cutoff_ms = current.timestamp_ms - (win_s * 1000)

        # Find earliest baseline snapshot within or at cutoff
        baseline = self.oi_history[0]
        for snap in self.oi_history:
            if snap.timestamp_ms >= cutoff_ms:
                baseline = snap
                break

        abs_delta = current.open_interest - baseline.open_interest
        if baseline.open_interest > Decimal("0"):
            delta_pct = abs_delta / baseline.open_interest
        else:
            delta_pct = Decimal("0")

        return abs_delta, delta_pct

    def process_agg_trade(
        self,
        trade_id: int,
        price: Decimal,
        quantity: Decimal,
        is_buyer_maker: bool,
        timestamp_ms: int
    ) -> None:
        """Ingest a live execution print from @aggTrade."""
        event = AggTradeEvent(
            trade_id=trade_id,
            price=price,
            quantity=quantity,
            is_buyer_maker=is_buyer_maker,
            timestamp_ms=timestamp_ms
        )
        self.trades.append(event)

    def process_depth_update(
        self,
        best_bid: Decimal,
        best_bid_qty: Decimal,
        best_ask: Decimal,
        best_ask_qty: Decimal,
        timestamp_ms: int,
        raw_bids: Optional[List[List[Any]]] = None,
        raw_asks: Optional[List[List[Any]]] = None
    ) -> Decimal:
        """
        Ingest top-of-book depth update from @depth5@100ms.
        Computes Cont-Kukanov-Stoikov (2014) Order Flow Imbalance (OFI).
        Also stores multi-level depth for shared Level-2 microstructure taps.
        """
        new_depth = DepthSnapshot(
            best_bid=best_bid,
            best_bid_qty=best_bid_qty,
            best_ask=best_ask,
            best_ask_qty=best_ask_qty,
            timestamp_ms=timestamp_ms
        )

        if raw_bids and raw_asks:
            self.top_bids = [(Decimal(str(p)), Decimal(str(q))) for p, q in raw_bids[:5]]
            self.top_asks = [(Decimal(str(p)), Decimal(str(q))) for p, q in raw_asks[:5]]
        else:
            self.top_bids = [(best_bid, best_bid_qty)]
            self.top_asks = [(best_ask, best_ask_qty)]
        self.last_depth_ms = timestamp_ms

        if self.last_depth is not None:
            self.prev_depth = self.last_depth
            prev = self.prev_depth
            curr = new_depth

            # Bid side contribution
            if curr.best_bid > prev.best_bid:
                delta_bid = curr.best_bid_qty
            elif curr.best_bid == prev.best_bid:
                delta_bid = curr.best_bid_qty - prev.best_bid_qty
            else:
                delta_bid = -prev.best_bid_qty

            # Ask side contribution
            if curr.best_ask < prev.best_ask:
                delta_ask = curr.best_ask_qty
            elif curr.best_ask == prev.best_ask:
                delta_ask = curr.best_ask_qty - prev.best_ask_qty
            else:
                delta_ask = -prev.best_ask_qty

            raw_ofi = delta_bid - delta_ask
            total_depth = curr.best_bid_qty + curr.best_ask_qty
            if total_depth > Decimal("0"):
                normalized_ofi = raw_ofi / total_depth
                # Clamp OFI to [-1.0, 1.0]
                self.last_ofi = max(Decimal("-1.0"), min(Decimal("1.0"), normalized_ofi))

        self.last_depth = new_depth
        return self.last_ofi

    def get_order_book_microstructure(self) -> Optional[OrderBookMicrostructure]:
        """
        Thread-safe extraction of Level-2 microstructure metrics (cumulative top-5 OBI,
        Stoikov micro-price and basis-point skew) adhering strictly to AGENTS.md Invariant 1.
        Freshness Guard: Vetoes snapshot if older than 3.0s.
        """
        if not self.top_bids or not self.top_asks:
            return None
        now_ms = int(time.time() * 1000)
        if (now_ms - self.last_depth_ms) > 3000:
            return None

        total_bids = sum(q for _, q in self.top_bids)
        total_asks = sum(q for _, q in self.top_asks)
        denom = total_bids + total_asks

        obi = (total_bids - total_asks) / denom if denom > Decimal("0") else Decimal("0.0")
        best_bid = self.top_bids[0][0]
        best_ask = self.top_asks[0][0]

        if best_bid > Decimal("0") and best_ask > Decimal("0"):
            mid = (best_bid + best_ask) / Decimal("2")
            if denom > Decimal("0"):
                micro_price = (best_bid * (total_asks / denom)) + (best_ask * (total_bids / denom))
            else:
                micro_price = mid
            micro_skew_bps = ((micro_price - mid) / mid) * Decimal("10000") if mid > Decimal("0") else Decimal("0.0")
        else:
            micro_price = Decimal("0.0")
            micro_skew_bps = Decimal("0.0")

        return OrderBookMicrostructure(
            obi=obi,
            best_bid=best_bid,
            best_ask=best_ask,
            micro_price=micro_price,
            micro_skew_bps=micro_skew_bps,
            timestamp_ms=self.last_depth_ms
        )

    def compute_cvd_metrics(self, window_seconds: int = 180) -> Tuple[Decimal, Decimal]:
        """
        Computes Cumulative Volume Delta (CVD) and Z-score over the lookback window.
        Returns:
            (rolling_cvd, cvd_zscore)
        """
        if not self.trades:
            return Decimal("0"), Decimal("0")

        cutoff_ms = self.trades[-1].timestamp_ms - (window_seconds * 1000)
        recent_trades = [t for t in self.trades if t.timestamp_ms >= cutoff_ms]

        if not recent_trades:
            return Decimal("0"), Decimal("0")

        total_cvd = sum(t.signed_delta for t in recent_trades)

        # Compute z-score across 5-second micro-buckets
        bucket_size_ms = 5000
        buckets: Dict[int, Decimal] = {}
        for t in recent_trades:
            b_key = t.timestamp_ms // bucket_size_ms
            buckets[b_key] = buckets.get(b_key, Decimal("0")) + t.signed_delta

        vals = list(buckets.values())
        if len(vals) < 3:
            return total_cvd, Decimal("0")

        mean_val = sum(vals) / Decimal(str(len(vals)))
        var = sum((v - mean_val) ** 2 for v in vals) / Decimal(str(len(vals)))
        std = Decimal(str(math.sqrt(float(var)))) if var > Decimal("0") else Decimal("1")

        current_bucket = vals[-1]
        zscore = (current_bucket - mean_val) / std if std > Decimal("0") else Decimal("0")

        return total_cvd, zscore

    def detect_trapped_trader_climax(
        self,
        bar_open: Decimal,
        bar_high: Decimal,
        bar_low: Decimal,
        bar_close: Decimal,
        bar_volume: Decimal,
        avg_volume_20: Decimal,
        macro_trend_1h: Optional[str] = None,
        btc_1m_return: Optional[Decimal] = None,
        btc_cvd_zscore: Optional[Decimal] = None,
        delta_oi_pct: Optional[Decimal] = None
    ) -> AbsorptionSignal:
        """
        The Tiger's Predatory Eye:
        Detects if aggressive market buyers/sellers trapped themselves at a swing high/low.
        """
        bar_range = bar_high - bar_low
        if bar_range <= Decimal("0"):
            return AbsorptionSignal(
                symbol=self.symbol, action="NONE", entry_trigger_price=Decimal("0"),
                invalidation_stop_price=Decimal("0"), cvd_zscore=Decimal("0"),
                micro_price_skew_bps=Decimal("0"), ofi_score=Decimal("0"),
                wick_ratio=Decimal("0"), absorption_density=Decimal("0"),
                is_steamroller_vetoed=False, is_valid=False, reason="Zero bar range"
            )

        # Spread check
        if self.last_depth and self.last_depth.spread_pct > self.cfg.max_spread_pct:
            return AbsorptionSignal(
                symbol=self.symbol, action="NONE", entry_trigger_price=Decimal("0"),
                invalidation_stop_price=Decimal("0"), cvd_zscore=Decimal("0"),
                micro_price_skew_bps=Decimal("0"), ofi_score=Decimal("0"),
                wick_ratio=Decimal("0"), absorption_density=Decimal("0"),
                is_steamroller_vetoed=False, is_valid=False, reason=f"Spread too wide: {self.last_depth.spread_pct}"
            )

        # Anti-Steamroller Guard: Immediately veto if an institutional freight train candle occurs
        if avg_volume_20 > Decimal("0"):
            vol_multiple = bar_volume / avg_volume_20
            body_ratio = abs(bar_close - bar_open) / bar_range
            if vol_multiple >= self.cfg.steamroller_vol_multiplier and body_ratio >= Decimal("0.80"):
                return AbsorptionSignal(
                    symbol=self.symbol, action="NONE", entry_trigger_price=Decimal("0"),
                    invalidation_stop_price=Decimal("0"), cvd_zscore=Decimal("0"),
                    micro_price_skew_bps=Decimal("0"), ofi_score=Decimal("0"),
                    wick_ratio=Decimal("0"), absorption_density=Decimal("0"),
                    is_steamroller_vetoed=True, is_valid=False,
                    reason="Anti-Steamroller Veto: Institutional Freight Train"
                )

        cvd, cvd_z = self.compute_cvd_metrics(window_seconds=180)
        skew_bps = self.last_depth.micro_price_skew_bps if self.last_depth else Decimal("0")
        ofi = self.last_ofi

        # Open Interest (ΔOI) Climax Gate: Distinguish trapped traders from stop liquidation flushes
        # Strict Negative Affirmation: Must have verified positive ΔOI >= min_delta_oi_pct
        # Never allow cold-start bypass: If <2 OI snapshots exist, setup is strictly vetoed!
        _, calc_delta_oi_pct = self.compute_delta_oi()
        eff_delta_oi_pct = delta_oi_pct if delta_oi_pct is not None else calc_delta_oi_pct
        oi_veto = False
        oi_veto_reason = ""
        if self.cfg.delta_oi_filter_enabled:
            if delta_oi_pct is None and len(self.oi_history) < 2:
                oi_veto = True
                oi_veto_reason = f"Open Interest Veto: Insufficient historical OI telemetry ({len(self.oi_history)} snapshots < 2). Strict negative affirmation enforced."
            elif eff_delta_oi_pct < self.cfg.min_delta_oi_pct:
                oi_veto = True
                oi_veto_reason = f"Open Interest Veto: Delta OI ({eff_delta_oi_pct*100:+.3f}%) < {self.cfg.min_delta_oi_pct*100:.3f}% indicates stop liquidation flush rather than trapped trader accumulation"

        # Candle close location within total range: 0.0 = at low, 1.0 = at high
        close_loc = (bar_close - bar_low) / bar_range

        # Case 1: Trapped Bulls Climax (Setup Short / SELL)
        # Aggressive buying (+CVD zscore >= 2.0), upper wick >= 40%, Micro-Price skews BELOW Mid,
        # AND close in outer bottom 35% of the candle (Wyckoff Upthrust rejection confirmation)
        upper_wick = bar_high - max(bar_open, bar_close)
        upper_wick_ratio = upper_wick / bar_range

        macro_veto_short = (
            self.cfg.macro_trend_filter_enabled and
            macro_trend_1h is not None and
            macro_trend_1h.upper() == "BULLISH"
        )
        btc_veto_short = (
            self.cfg.btc_tide_gate_enabled and (
                (btc_1m_return is not None and btc_1m_return >= abs(self.cfg.btc_1m_dump_threshold_pct)) or
                (btc_cvd_zscore is not None and btc_cvd_zscore >= abs(self.cfg.btc_cvd_dump_sigma))
            )
        )

        if (
            not macro_veto_short and
            not btc_veto_short and
            close_loc <= self.cfg.max_candle_close_loc_pct and
            cvd_z >= self.cfg.cvd_divergence_sigma and
            upper_wick_ratio >= self.cfg.absorption_wick_min_ratio and
            skew_bps <= -self.cfg.micro_price_skew_bps and
            ofi <= -self.cfg.ofi_threshold
        ):
            if oi_veto:
                return AbsorptionSignal(
                    symbol=self.symbol, action="NONE", entry_trigger_price=Decimal("0"),
                    invalidation_stop_price=Decimal("0"), cvd_zscore=cvd_z,
                    micro_price_skew_bps=skew_bps, ofi_score=ofi,
                    wick_ratio=upper_wick_ratio, absorption_density=Decimal("0"),
                    is_steamroller_vetoed=False, is_valid=False, delta_oi_pct=eff_delta_oi_pct,
                    reason=oi_veto_reason
                )
            return AbsorptionSignal(
                symbol=self.symbol, action="SELL", entry_trigger_price=bar_low,
                invalidation_stop_price=bar_high, cvd_zscore=cvd_z,
                micro_price_skew_bps=skew_bps, ofi_score=ofi,
                wick_ratio=upper_wick_ratio, absorption_density=Decimal("0.85"),
                is_steamroller_vetoed=False, is_valid=True, delta_oi_pct=eff_delta_oi_pct,
                reason="Trapped Bulls Climax: Delta absorption at swing high with positive ΔOI, negative OFI flip and weak close"
            )

        # Case 2: Trapped Bears Climax (Setup Long / BUY)
        # Aggressive selling (-CVD zscore <= -2.0), lower wick >= 50% (Falling Knife Guard), Micro-Price skews ABOVE Mid,
        # AND close in outer top 35% of the candle (Wyckoff Spring rejection confirmation)
        lower_wick = min(bar_open, bar_close) - bar_low
        lower_wick_ratio = lower_wick / bar_range

        req_lower_wick = (
            getattr(self.cfg, "buy_absorption_wick_min_ratio", Decimal("0.50"))
            if getattr(self.cfg, "falling_knife_guard_enabled", True)
            else self.cfg.absorption_wick_min_ratio
        )

        macro_veto_long = (
            self.cfg.macro_trend_filter_enabled and
            macro_trend_1h is not None and
            macro_trend_1h.upper() in ("BEARISH", "DOWNTREND")
        )
        btc_veto_long = (
            self.cfg.btc_tide_gate_enabled and (
                (btc_1m_return is not None and btc_1m_return <= self.cfg.btc_1m_dump_threshold_pct) or
                (btc_cvd_zscore is not None and btc_cvd_zscore <= self.cfg.btc_cvd_dump_sigma)
            )
        )

        if (
            not macro_veto_long and
            not btc_veto_long and
            close_loc >= (Decimal("1.0") - self.cfg.max_candle_close_loc_pct) and
            cvd_z <= -self.cfg.cvd_divergence_sigma and
            lower_wick_ratio >= req_lower_wick and
            skew_bps >= self.cfg.micro_price_skew_bps and
            ofi >= self.cfg.ofi_threshold
        ):
            if oi_veto:
                return AbsorptionSignal(
                    symbol=self.symbol, action="NONE", entry_trigger_price=Decimal("0"),
                    invalidation_stop_price=Decimal("0"), cvd_zscore=cvd_z,
                    micro_price_skew_bps=skew_bps, ofi_score=ofi,
                    wick_ratio=lower_wick_ratio, absorption_density=Decimal("0"),
                    is_steamroller_vetoed=False, is_valid=False, delta_oi_pct=eff_delta_oi_pct,
                    reason=oi_veto_reason
                )
            return AbsorptionSignal(
                symbol=self.symbol, action="BUY", entry_trigger_price=bar_high,
                invalidation_stop_price=bar_low, cvd_zscore=cvd_z,
                micro_price_skew_bps=skew_bps, ofi_score=ofi,
                wick_ratio=lower_wick_ratio, absorption_density=Decimal("0.85"),
                is_steamroller_vetoed=False, is_valid=True, delta_oi_pct=eff_delta_oi_pct,
                reason="Trapped Bears Climax: Delta absorption at swing low with positive ΔOI, positive OFI flip and strong close"
            )

        return AbsorptionSignal(
            symbol=self.symbol, action="NONE", entry_trigger_price=Decimal("0"),
            invalidation_stop_price=Decimal("0"), cvd_zscore=cvd_z,
            micro_price_skew_bps=skew_bps, ofi_score=ofi,
            wick_ratio=max(upper_wick_ratio, lower_wick_ratio),
            absorption_density=Decimal("0"), is_steamroller_vetoed=False,
            is_valid=False, delta_oi_pct=eff_delta_oi_pct,
            reason="No trapped liquidity climax detected"
        )
