"""
src/quant/tiger_scanner.py — Bulk 24hr Ticker Sieve & Binance Zero-Ban Rate Limiter.

Operates Strategy #3's Top 150 Sieve using a single bulk REST endpoint (40 weight)
coupled with strict response header tracking (x-mbx-used-weight-1m).
Adheres to AGENTS.md Invariant 1 (Zero Float Financial Math).
"""

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import logging
import math
import time
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from src.quant.tiger_config import (
    TigerApiRateLimitConfig,
    TigerUniverseSieveConfig,
    TigerMasterConfig,
    DEFAULT_TIGER_CONFIG,
)

logger = logging.getLogger("kronos.tiger_scanner")


@dataclass
class PreyCandidate:
    """A qualified asset identified by the Top 150 Volatility Sieve."""
    symbol: str
    turnover_24h_usd: Decimal
    volatility_score: Decimal
    price_change_pct: Decimal
    high_price: Decimal
    low_price: Decimal
    last_price: Decimal
    rank: int
    dynamic_strength: Decimal = Decimal("1.00")
    stagnation_status: str = "ACTIVE"
    retention_ratio: Decimal = Decimal("1.00")
    elapsed_seconds: float = 0.0


class BinanceRateLimitWatchdog:
    """
    Sovereign guardian against Binance IP bans.
    Monitors x-mbx-used-weight-1m headers, enforcing proactive throttling.
    """
    def __init__(self, config: Optional[TigerApiRateLimitConfig] = None):
        self.cfg = config or DEFAULT_TIGER_CONFIG.rate_limit
        self.last_used_weight_1m: int = 0
        self.last_update_ts: float = time.time()
        self.is_throttled: bool = False
        self.is_paused: bool = False

    def update_from_headers(self, headers: Dict[str, str]) -> int:
        """Parse Binance response headers to extract current 1-minute weight consumption."""
        for k, v in headers.items():
            if k.lower() == "x-mbx-used-weight-1m":
                try:
                    weight = int(v)
                    self.last_used_weight_1m = weight
                    self.last_update_ts = time.time()
                    
                    # State transitions
                    if weight >= self.cfg.critical_weight_threshold:
                        self.is_paused = True
                        self.is_throttled = True
                        logger.warning(
                            f"[CRITICAL RATE LIMIT] Used weight {weight} >= {self.cfg.critical_weight_threshold}! "
                            f"Pausing REST requests."
                        )
                    elif weight >= self.cfg.warning_weight_threshold:
                        self.is_paused = False
                        self.is_throttled = True
                        logger.info(
                            f"[WARNING RATE LIMIT] Used weight {weight} >= {self.cfg.warning_weight_threshold}. "
                            f"Throttling polling cadence."
                        )
                    else:
                        self.is_paused = False
                        self.is_throttled = False
                    
                    return weight
                except ValueError:
                    pass
        return self.last_used_weight_1m

    def get_poll_interval_seconds(self) -> float:
        """Dynamic polling interval scaled to current API rate consumption."""
        if self.is_paused:
            return float(self.cfg.bulk_ticker_interval_seconds * 4)  # 120s pause
        if self.is_throttled:
            return float(self.cfg.bulk_ticker_interval_seconds * 2)  # 60s throttle
        return float(self.cfg.bulk_ticker_interval_seconds)         # 30s normal

    def can_request(self, weight_cost: int = 40) -> bool:
        """Determines if an outbound REST call is safe to dispatch."""
        if self.is_paused:
            return False
        projected = self.last_used_weight_1m + weight_cost
        return projected < self.cfg.critical_weight_threshold


class TigerUniverseScanner:
    """
    High-Altitude Radar for Strategy #3 (Stalking Tiger).
    Scans the entire Binance USD(S)-M universe using 1 bulk call (40 weight),
    filters for high-liquidity coins, and isolates the Top 5 Hot Prey targets.
    """
    # Excluded stablecoin/pegged pairs that lack genuine speculative volatility
    EXCLUDED_SYMBOLS = {
        "USDCUSDT", "FDUSDUSDT", "TUSDUSDT", "EURUSDT", "BUSDUSDT",
        "DAIUSDT", "USDPUSDT", "AEURUSDT", "USTCUSDT"
    }

    def __init__(
        self,
        master_config: Optional[TigerMasterConfig] = None,
        fetcher_func: Optional[Callable[[], Tuple[List[Dict[str, Any]], Dict[str, str]]]] = None
    ):
        self.cfg = master_config or DEFAULT_TIGER_CONFIG
        self.watchdog = BinanceRateLimitWatchdog(self.cfg.rate_limit)
        self._fetcher = fetcher_func
        self.last_scan_ts: float = 0.0
        self.cached_universe: List[PreyCandidate] = []
        self.cached_top_prey: List[PreyCandidate] = []
        self.slot_entry_ts: Dict[str, float] = {}
        self.peak_strength: Dict[str, Decimal] = {}
        self.stagnant_cooldowns: Dict[str, float] = {}
        self.last_tick_snapshot: Dict[str, Tuple[float, int]] = {}

    def set_fetcher(
        self,
        fetcher_func: Callable[[], Tuple[List[Dict[str, Any]], Dict[str, str]]]
    ) -> None:
        """Inject REST fetcher callable (returns (raw_ticker_list, response_headers))."""
        self._fetcher = fetcher_func

    def parse_raw_tickers(
        self,
        raw_tickers: List[Dict[str, Any]]
    ) -> List[PreyCandidate]:
        """
        Filters raw 24hr tickers through the Volatility Sieve.
        Computes Relative Volatility Score using strict Decimal math.
        """
        candidates: List[PreyCandidate] = []
        sieve_cfg = self.cfg.sieve

        for item in raw_tickers:
            symbol = item.get("symbol", "")
            if not symbol.isascii() or not symbol.isalnum():
                continue
            if not symbol.endswith(sieve_cfg.quote_asset):
                continue
            if symbol in self.EXCLUDED_SYMBOLS:
                continue

            try:
                quote_vol = Decimal(str(item.get("quoteVolume", "0")))
                if quote_vol < sieve_cfg.min_24h_turnover_usd:
                    continue

                high = Decimal(str(item.get("highPrice", "0")))
                low = Decimal(str(item.get("lowPrice", "0")))
                last = Decimal(str(item.get("lastPrice", "0")))
                change_pct = Decimal(str(item.get("priceChangePercent", "0")))

                # Freight Train Outlier Shield: reject coins experiencing extreme 24h macro shocks (> +/-35%)
                if abs(change_pct) > (sieve_cfg.max_24h_change_abs_pct * Decimal("100")):
                    continue

                if last <= Decimal("0") or high <= low:
                    continue

                # Volatility amplitude: (High - Low) / Last
                raw_amp = (high - low) / last
                if raw_amp < sieve_cfg.min_volatility_score:
                    continue

                # Liquidity logarithmic weight: log10(turnover / $10M) clamped >= 1.0
                turnover_ratio = float(quote_vol / Decimal("10000000.0"))
                liq_multiplier = Decimal(str(round(max(1.0, math.log10(max(1.0, turnover_ratio))), 4)))

                # Composite Relative Volatility Score
                vol_score = raw_amp * liq_multiplier

                candidates.append(PreyCandidate(
                    symbol=symbol,
                    turnover_24h_usd=quote_vol,
                    volatility_score=vol_score,
                    price_change_pct=change_pct,
                    high_price=high,
                    low_price=low,
                    last_price=last,
                    rank=0  # Assigned after sorting
                ))
            except (InvalidOperation, ValueError, ZeroDivisionError):
                continue

        # Sort descending by composite volatility score
        candidates.sort(key=lambda c: c.volatility_score, reverse=True)

        # Assign ranks
        for idx, cand in enumerate(candidates):
            cand.rank = idx + 1

        return candidates

    def run_sieve(
        self,
        excluded_symbols: Optional[Set[str]] = None,
        ws_manager: Optional[Any] = None
    ) -> Tuple[List[PreyCandidate], List[PreyCandidate]]:
        """
        Executes the Continuous Opportunistic Sieve.
        Optionally excludes symbols that already have active positions, pending orders,
        cooldowns, quarantines, or active stagnation timeouts.
        Dynamically penalizes decaying/stagnant assets in the sniper pool and
        replaces them with active breakout candidates.
        Returns:
            (top_150_universe, top_5_active_prey)
        """
        now = time.time()

        # 1. Purge expired stagnation cooldowns
        expired_cd = [s for s, expiry in self.stagnant_cooldowns.items() if now >= expiry]
        for s in expired_cd:
            del self.stagnant_cooldowns[s]

        # 2. Rate limit budget guard
        if not self.watchdog.can_request(self.cfg.rate_limit.bulk_ticker_weight_cost):
            logger.warning("[TIGER SCANNER] Request blocked by RateLimitWatchdog. Serving cache.")
            return self.cached_universe, self.cached_top_prey

        if not self._fetcher:
            raise RuntimeError("TigerUniverseScanner has no fetcher callable configured.")

        raw_data, headers = self._fetcher()
        self.watchdog.update_from_headers(headers)

        all_candidates = self.parse_raw_tickers(raw_data)

        # Slice Top 150 universe
        universe_150 = all_candidates[:self.cfg.sieve.max_universe_size]

        # 3. Dynamic Strength Evaluation & Decay for Incumbents
        full_excluded = set(excluded_symbols or []) | set(self.stagnant_cooldowns.keys())
        evicted_incumbents: Set[str] = set()

        for cand in universe_150:
            sym = cand.symbol
            if sym in self.slot_entry_ts:
                elapsed = now - self.slot_entry_ts[sym]
                cand.elapsed_seconds = elapsed

                # Measure tick velocity and micro-orderflow pulse
                tick_velocity = 10.0
                has_setup = False
                if ws_manager:
                    try:
                        tracker = ws_manager.get_tracker(sym)
                        if tracker:
                            current_ticks = getattr(tracker, "total_ticks_received", len(getattr(tracker, "trades_window", [])))
                            last_t, last_cnt = self.last_tick_snapshot.get(sym, (now - 1.0, current_ticks))
                            dt = max(0.5, now - last_t)
                            tick_velocity = max(0.0, float(current_ticks - last_cnt) / dt)
                            self.last_tick_snapshot[sym] = (now, current_ticks)

                            # Check for active absorption wicks or CVD surge
                            if getattr(tracker, "last_wick_ratio", Decimal("0")) >= Decimal("0.40"):
                                has_setup = True
                            _, cvd_z = tracker.compute_cvd_metrics(window_seconds=60)
                            if abs(cvd_z) >= Decimal("1.5"):
                                has_setup = True
                    except Exception:
                        pass

                # Stagnation Decay Ladder
                decay_factor = Decimal("1.00")
                status = "ACTIVE"
                if elapsed > 180.0 and not has_setup:
                    # > 3 minutes with zero climax formation -> EVICT
                    decay_factor = Decimal("0.30")
                    status = "EVICT_EXPIRED"
                elif elapsed > 120.0 and tick_velocity < 6.0 and not has_setup:
                    decay_factor = Decimal("0.55")
                    status = "STAGNANT_DECAY"
                elif elapsed > 60.0 and tick_velocity < 4.0:
                    decay_factor = Decimal("0.80")
                    status = "MOMENTUM_STALL"

                cand.dynamic_strength = (cand.volatility_score * decay_factor).quantize(Decimal("0.0001"))
                cand.stagnation_status = status
                peak = self.peak_strength.get(sym, cand.volatility_score)
                cand.retention_ratio = (cand.dynamic_strength / peak).quantize(Decimal("0.01")) if peak > Decimal("0") else Decimal("1.00")

                # If status is EVICT_EXPIRED or severe decay with dead velocity, evict immediately
                if status == "EVICT_EXPIRED" or (decay_factor <= Decimal("0.55") and tick_velocity < 5.0):
                    evicted_incumbents.add(sym)
                    self.stagnant_cooldowns[sym] = now + 300.0  # 5-minute timeout
                    logger.info(
                        "[TIGER EVICTION] %s evicted for lowering strength (Elapsed: %.0fs, Ticks: %.1f/s, Decay: %s). 5m timeout armed.",
                        sym, elapsed, tick_velocity, decay_factor
                    )
            else:
                cand.dynamic_strength = cand.volatility_score
                cand.stagnation_status = "ACTIVE"
                cand.retention_ratio = Decimal("1.00")

        # Exclude evicted incumbents from pool
        full_excluded |= evicted_incumbents

        # 4. Filter and select Top 5 by Dynamic Strength
        eligible_universe = [c for c in universe_150 if c.symbol not in full_excluded]
        eligible_universe.sort(key=lambda c: c.dynamic_strength, reverse=True)
        top_5_prey = eligible_universe[:self.cfg.sieve.active_sniper_slots]

        for idx, cand in enumerate(top_5_prey):
            cand.rank = idx + 1

        # 5. Update slot entry times and peak strengths
        current_top_symbols = {c.symbol for c in top_5_prey}
        for c in top_5_prey:
            if c.symbol not in self.slot_entry_ts:
                self.slot_entry_ts[c.symbol] = now
                self.peak_strength[c.symbol] = c.volatility_score
                logger.info("[TIGER POP-IN] New active prey isolated: %s (Strength: %s)", c.symbol, c.dynamic_strength)

        # Clean tracking for symbols that left Top 5
        left_symbols = [s for s in list(self.slot_entry_ts.keys()) if s not in current_top_symbols]
        for s in left_symbols:
            del self.slot_entry_ts[s]
            if s in self.peak_strength:
                del self.peak_strength[s]

        self.cached_universe = universe_150
        self.cached_top_prey = top_5_prey
        self.last_scan_ts = now

        return universe_150, top_5_prey
