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

    def run_sieve(self, excluded_symbols: Optional[Set[str]] = None) -> Tuple[List[PreyCandidate], List[PreyCandidate]]:
        """
        Executes the Top 150 Sieve.
        Optionally excludes symbols that already have active positions, pending orders,
        cooldowns, or quarantines so that all 5 sniper slots remain 100% dedicated to viable hunting.
        Returns:
            (top_150_universe, top_5_active_prey)
        """
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
        
        # Isolate Top 5 "Hot Prey" excluding active trades, orders, cooldowns, or quarantines
        if excluded_symbols:
            eligible_universe = [c for c in universe_150 if c.symbol not in excluded_symbols]
            top_5_prey = eligible_universe[:self.cfg.sieve.active_sniper_slots]
        else:
            top_5_prey = universe_150[:self.cfg.sieve.active_sniper_slots]

        self.cached_universe = universe_150
        self.cached_top_prey = top_5_prey
        self.last_scan_ts = time.time()

        return universe_150, top_5_prey
