"""
src/quant/volume_profile.py — Pure-Decimal Fixed-Range Volume Profile Engine (Auction Market Theory).

Computes immutable previous-UTC-day spatial liquidity levels (pPOC, pVAH, pVAL, HVN/LVN density,
and prior-session close balance regime) from completed intraday OHLCV candles with ZERO lookahead bias.

Adheres strictly to AGENTS.md Invariant 1 (Zero Float Financial Math).
"""

import datetime
import logging
import threading
import time
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import requests

logger = logging.getLogger("kronos.volume_profile")


ZERO = Decimal("0")
ONE = Decimal("1")
TWO = Decimal("2")
HUNDRED = Decimal("100")


@dataclass(frozen=True)
class VolumeProfileSnapshot:
    """Immutable spatial liquidity profile for a completed prior UTC session."""
    symbol: str
    session_date_utc: str            # YYYY-MM-DD of the completed session
    row_size: int
    value_area_pct: Decimal
    session_high: Decimal
    session_low: Decimal
    prior_close: Decimal
    total_volume: Decimal
    poc: Decimal                     # Point of Control (bin midpoint of max volume)
    vah: Decimal                     # Value Area High (upper edge of 70% volume zone)
    val: Decimal                     # Value Area Low (lower edge of 70% volume zone)
    poc_volume: Decimal
    avg_bin_volume: Decimal
    prior_close_regime: str          # "ABOVE_VA", "INSIDE_VA", "BELOW_VA"
    bin_size: Decimal
    bin_volumes: tuple               # Tuple[Decimal, ...] length == row_size

    @property
    def is_balanced_prior_day(self) -> bool:
        return self.prior_close_regime == "INSIDE_VA"

    @property
    def va_width_pct(self) -> Decimal:
        if self.poc <= ZERO:
            return ZERO
        return ((self.vah - self.val) / self.poc) * HUNDRED

    def local_volume_ratio(self, price: Decimal) -> Decimal:
        """
        Ratio of traded volume at `price`'s bin to the session average bin volume.
        > 1.50 => High-Volume Node (HVN, consolidation/chop magnet)
        < 0.50 => Low-Volume Node (LVN, fast-travel air pocket)
        0.00   => Outside prior day's entire price range (price discovery)
        """
        if self.avg_bin_volume <= ZERO or self.bin_size <= ZERO:
            return ZERO
        if price < self.session_low or price > self.session_high:
            return ZERO
        idx = int((price - self.session_low) / self.bin_size)
        idx = max(0, min(self.row_size - 1, idx))
        return self.bin_volumes[idx] / self.avg_bin_volume

    def price_zone(self, price: Decimal, poc_band_pct: Decimal = Decimal("0.0015")) -> str:
        """
        Classifies where `price` sits relative to yesterday's Volume Profile.
        """
        if self.poc > ZERO and abs(price - self.poc) / self.poc <= poc_band_pct:
            return "AT_POC"
        if price > self.vah:
            return "ABOVE_VAH"
        if price < self.val:
            return "BELOW_VAL"
        if price >= self.poc:
            return "UPPER_VA"
        return "LOWER_VA"


@dataclass(frozen=True)
class SpatialTradeContext:
    """Spatial relationship between a proposed/historical trade entry and prior-day Volume Profile."""
    zone: str                        # ABOVE_VAH, UPPER_VA, AT_POC, LOWER_VA, BELOW_VAL
    prior_close_regime: str          # ABOVE_VA, INSIDE_VA, BELOW_VA
    dist_to_poc_pct: Decimal         # Signed: (poc - entry) / entry * 100
    dist_to_vah_pct: Decimal         # Signed: (vah - entry) / entry * 100
    dist_to_val_pct: Decimal         # Signed: (val - entry) / entry * 100
    local_vol_ratio: Decimal         # bin_vol / avg_bin_vol (HVN vs LVN)
    firing_into_poc: bool            # Trade aimed directly into opposing pPOC within hazard distance
    firing_into_va_edge: bool        # BUY directly under pVAH or SELL directly above pVAL
    is_hvn_entry: bool               # local_vol_ratio >= 1.5
    is_lvn_entry: bool               # 0 < local_vol_ratio <= 0.5
    is_outside_range: bool           # Entry outside entire prior-day high/low (price discovery)
    direction_vs_poc: str            # "TOWARD_POC", "AWAY_FROM_POC", "AT_POC"
    va_alignment: str                # "BREAKOUT_WITH_TREND", "MEAN_REVERSION_TO_POC", "FADING_BREAKOUT", "INSIDE_CHOP"


class VolumeProfileEngine:
    """
    Pure-Decimal Fixed-Range Volume Profile calculator.
    """

    def __init__(
        self,
        row_size: int = 60,
        value_area_pct: Decimal = Decimal("0.70"),
    ):
        if row_size < 5:
            raise ValueError("row_size must be >= 5")
        if not (ZERO < value_area_pct <= ONE):
            raise ValueError("value_area_pct must be in (0, 1]")
        self.row_size = row_size
        self.value_area_pct = value_area_pct

    def build_profile(
        self,
        symbol: str,
        session_date_utc: str,
        candles: Sequence[Dict[str, Any]],
    ) -> Optional[VolumeProfileSnapshot]:
        """
        Builds a Fixed-Range Volume Profile from a completed session's OHLCV candles.

        Each candle dict must contain keys: 'high', 'low', 'close', 'volume'
        (values may be Decimal, str, or int; converted safely via Decimal(str(...))).
        """
        if not candles:
            return None

        parsed: List[tuple] = []
        session_high: Optional[Decimal] = None
        session_low: Optional[Decimal] = None
        total_volume = ZERO

        for c in candles:
            h = c["high"] if isinstance(c["high"], Decimal) else Decimal(str(c["high"]))
            l = c["low"] if isinstance(c["low"], Decimal) else Decimal(str(c["low"]))
            cl = c["close"] if isinstance(c["close"], Decimal) else Decimal(str(c["close"]))
            v = c["volume"] if isinstance(c["volume"], Decimal) else Decimal(str(c["volume"]))
            if v < ZERO:
                continue
            if h < l:
                h, l = l, h
            parsed.append((h, l, cl, v))
            session_high = h if session_high is None else max(session_high, h)
            session_low = l if session_low is None else min(session_low, l)
            total_volume += v

        if not parsed or session_high is None or session_low is None or total_volume <= ZERO:
            return None

        prior_close = parsed[-1][2]
        price_span = session_high - session_low

        # Flat-session edge case
        if price_span <= ZERO:
            bins = [ZERO] * self.row_size
            bins[0] = total_volume
            return VolumeProfileSnapshot(
                symbol=symbol,
                session_date_utc=session_date_utc,
                row_size=self.row_size,
                value_area_pct=self.value_area_pct,
                session_high=session_high,
                session_low=session_low,
                prior_close=prior_close,
                total_volume=total_volume,
                poc=session_low,
                vah=session_high,
                val=session_low,
                poc_volume=total_volume,
                avg_bin_volume=total_volume / Decimal(str(self.row_size)),
                prior_close_regime="INSIDE_VA",
                bin_size=ZERO,
                bin_volumes=tuple(bins),
            )

        n = self.row_size
        bin_size = price_span / Decimal(str(n))
        bins: List[Decimal] = [ZERO] * n

        # Distribute each candle's volume across overlapping price bins proportionally
        for h, l, _cl, v in parsed:
            if v == ZERO:
                continue
            candle_span = h - l
            if candle_span == ZERO:
                idx = int((l - session_low) / bin_size)
                idx = max(0, min(n - 1, idx))
                bins[idx] += v
                continue

            start_idx = max(0, min(n - 1, int((l - session_low) / bin_size)))
            end_idx = max(0, min(n - 1, int((h - session_low) / bin_size)))

            for i in range(start_idx, end_idx + 1):
                b_lo = session_low + bin_size * Decimal(str(i))
                b_hi = session_high if i == n - 1 else (b_lo + bin_size)
                overlap_lo = max(l, b_lo)
                overlap_hi = min(h, b_hi)
                if overlap_hi > overlap_lo:
                    frac = (overlap_hi - overlap_lo) / candle_span
                    bins[i] += v * frac

        # Point of Control (POC): highest volume bin (tie-breaker: closest to center)
        mid_idx = n // 2
        poc_idx = max(range(n), key=lambda i: (bins[i], -abs(i - mid_idx)))
        poc = session_low + bin_size * (Decimal(str(poc_idx)) + Decimal("0.5"))
        poc_volume = bins[poc_idx]

        # 70% Value Area: expand outward from POC, adding the higher-volume adjacent bin
        va_target = total_volume * self.value_area_pct
        va_vol = bins[poc_idx]
        lo_idx = poc_idx
        hi_idx = poc_idx

        while va_vol < va_target and (lo_idx > 0 or hi_idx < n - 1):
            up_vol = bins[hi_idx + 1] if hi_idx < n - 1 else Decimal("-1")
            dn_vol = bins[lo_idx - 1] if lo_idx > 0 else Decimal("-1")

            if up_vol >= dn_vol and hi_idx < n - 1:
                hi_idx += 1
                va_vol += bins[hi_idx]
            elif lo_idx > 0:
                lo_idx -= 1
                va_vol += bins[lo_idx]
            else:
                break

        val = session_low + bin_size * Decimal(str(lo_idx))
        vah = session_high if hi_idx == n - 1 else (session_low + bin_size * Decimal(str(hi_idx + 1)))

        if prior_close > vah:
            prior_close_regime = "ABOVE_VA"
        elif prior_close < val:
            prior_close_regime = "BELOW_VA"
        else:
            prior_close_regime = "INSIDE_VA"

        avg_bin_volume = total_volume / Decimal(str(n))

        return VolumeProfileSnapshot(
            symbol=symbol,
            session_date_utc=session_date_utc,
            row_size=n,
            value_area_pct=self.value_area_pct,
            session_high=session_high,
            session_low=session_low,
            prior_close=prior_close,
            total_volume=total_volume,
            poc=poc,
            vah=vah,
            val=val,
            poc_volume=poc_volume,
            avg_bin_volume=avg_bin_volume,
            prior_close_regime=prior_close_regime,
            bin_size=bin_size,
            bin_volumes=tuple(bins),
        )

    @staticmethod
    def evaluate_entry_context(
        profile: VolumeProfileSnapshot,
        entry_price: Decimal,
        side: str,
        poc_hazard_pct: Decimal = Decimal("0.80"),
        va_edge_hazard_pct: Decimal = Decimal("0.50"),
    ) -> SpatialTradeContext:
        """
        Evaluates how an entry price & side interact with yesterday's Volume Profile.

        Args:
            profile: Completed previous UTC day's VolumeProfileSnapshot.
            entry_price: Proposed or historical entry price (Decimal).
            side: "BUY" (LONG) or "SELL" (SHORT).
            poc_hazard_pct: Distance (%) within which an opposing pPOC acts as a brick-wall obstacle.
            va_edge_hazard_pct: Distance (%) within which an opposing pVAH/pVAL acts as resistance/support.
        """
        s = side.upper()
        zone = profile.price_zone(entry_price)
        local_vol = profile.local_volume_ratio(entry_price)

        dist_poc = ((profile.poc - entry_price) / entry_price) * HUNDRED if entry_price > ZERO else ZERO
        dist_vah = ((profile.vah - entry_price) / entry_price) * HUNDRED if entry_price > ZERO else ZERO
        dist_val = ((profile.val - entry_price) / entry_price) * HUNDRED if entry_price > ZERO else ZERO

        # Firing directly INTO pPOC (pPOC sits in front of the trade within hazard distance)
        if s == "BUY":
            firing_into_poc = Decimal("0.05") <= dist_poc <= poc_hazard_pct
            firing_into_va_edge = Decimal("0.00") <= dist_vah <= va_edge_hazard_pct
        else:
            firing_into_poc = Decimal("0.05") <= (-dist_poc) <= poc_hazard_pct
            firing_into_va_edge = Decimal("0.00") <= (-dist_val) <= va_edge_hazard_pct

        # Direction relative to pPOC
        if zone == "AT_POC":
            dir_vs_poc = "AT_POC"
        elif (s == "BUY" and dist_poc > ZERO) or (s == "SELL" and dist_poc < ZERO):
            dir_vs_poc = "TOWARD_POC"
        else:
            dir_vs_poc = "AWAY_FROM_POC"

        # Alignment classification
        if (s == "BUY" and zone == "ABOVE_VAH") or (s == "SELL" and zone == "BELOW_VAL"):
            va_alignment = "BREAKOUT_WITH_TREND"
        elif (s == "SELL" and zone == "ABOVE_VAH") or (s == "BUY" and zone == "BELOW_VAL"):
            va_alignment = "FADING_BREAKOUT"
        elif dir_vs_poc == "TOWARD_POC":
            va_alignment = "MEAN_REVERSION_TO_POC"
        else:
            va_alignment = "INSIDE_CHOP"

        is_outside_range = entry_price > profile.session_high or entry_price < profile.session_low

        return SpatialTradeContext(
            zone=zone,
            prior_close_regime=profile.prior_close_regime,
            dist_to_poc_pct=dist_poc.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP),
            dist_to_vah_pct=dist_vah.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP),
            dist_to_val_pct=dist_val.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP),
            local_vol_ratio=local_vol.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
            firing_into_poc=firing_into_poc,
            firing_into_va_edge=firing_into_va_edge,
            is_hvn_entry=local_vol >= Decimal("1.50"),
            is_lvn_entry=(ZERO < local_vol <= Decimal("0.50")),
            is_outside_range=is_outside_range,
            direction_vs_poc=dir_vs_poc,
            va_alignment=va_alignment,
        )

    @staticmethod
    def evaluate_spatial_veto(
        profile: Optional[VolumeProfileSnapshot],
        entry_price: Decimal,
        side: str,
        veto_firing_into_poc: bool = True,
        veto_hvn_chop: bool = True,
        veto_fading_breakout: bool = False,
        poc_hazard_pct: Decimal = Decimal("0.80"),
    ) -> "VolumeProfileVetoResult":
        """
        Empirically validated spatial liquidity veto gate (zero lookahead):
          - H1 (`VP_FIRING_INTO_POC`): Blocks entries aimed directly into opposing prior-day pPOC (0.05%-0.80% ahead).
          - H4 (`VP_HVN_CHOP`): Blocks entries inside High-Volume Node chop zones (local bin vol >= 1.5x session avg).
          - Optional Tiger guard (`VP_FADING_BREAKOUT`): Blocks counter-trend fading outside prior-day Value Area.
        Fail-open if `profile` is None (preserves liveness during network blips).
        """
        if profile is None or entry_price <= ZERO:
            return VolumeProfileVetoResult(
                approved=True,
                veto_code=None,
                reason="Volume Profile unavailable (fail-open).",
                context=None,
            )

        s = side.upper()
        if s == "LONG":
            s = "BUY"
        elif s == "SHORT":
            s = "SELL"

        ctx = VolumeProfileEngine.evaluate_entry_context(
            profile=profile,
            entry_price=entry_price,
            side=s,
            poc_hazard_pct=poc_hazard_pct,
        )

        if veto_firing_into_poc and ctx.firing_into_poc:
            return VolumeProfileVetoResult(
                approved=False,
                veto_code="VP_FIRING_INTO_POC",
                reason=(
                    f"VETO [VP_FIRING_INTO_POC]: {s} @ {entry_price} fires directly into prior-day "
                    f"pPOC {profile.poc:.6g} ({ctx.dist_to_poc_pct:+.2f}% away)."
                ),
                context=ctx,
            )

        if veto_hvn_chop and ctx.is_hvn_entry:
            return VolumeProfileVetoResult(
                approved=False,
                veto_code="VP_HVN_CHOP",
                reason=(
                    f"VETO [VP_HVN_CHOP]: {s} @ {entry_price} inside High-Volume Node chop zone "
                    f"(density {ctx.local_vol_ratio:.2f}x >= 1.50x avg, pPOC={profile.poc:.6g})."
                ),
                context=ctx,
            )

        if veto_fading_breakout and ctx.va_alignment == "FADING_BREAKOUT":
            edge_lbl = f"pVAH {profile.vah:.6g}" if ctx.zone == "ABOVE_VAH" else f"pVAL {profile.val:.6g}"
            return VolumeProfileVetoResult(
                approved=False,
                veto_code="VP_FADING_BREAKOUT",
                reason=(
                    f"VETO [VP_FADING_BREAKOUT]: {s} @ {entry_price} fades breakout outside prior-day "
                    f"Value Area ({ctx.zone}, {edge_lbl})."
                ),
                context=ctx,
            )

        return VolumeProfileVetoResult(
            approved=True,
            veto_code=None,
            reason=(
                f"VP_PASS: {s} in {ctx.zone} (density={ctx.local_vol_ratio:.2f}x, "
                f"dPOC={ctx.dist_to_poc_pct:+.2f}%, align={ctx.va_alignment})."
            ),
            context=ctx,
        )


@dataclass(frozen=True)
class VolumeProfileVetoResult:
    """Outcome of VolumeProfileEngine.evaluate_spatial_veto."""
    approved: bool
    veto_code: Optional[str]
    reason: str
    context: Optional[SpatialTradeContext]


class DailyVolumeProfileCache:
    """
    Ultra-lean daily cache for previous-UTC-day Binance Futures Volume Profiles.
    Fetches 96 x 15m completed UTC candles at most ONCE per (symbol, prev_utc_day).
    Bounded memory (<10 KB on t3.micro) with automatic stale-day eviction and fail-open backoff.
    """

    BINANCE_FAPI_KLINES = "https://fapi.binance.com/fapi/v1/klines"

    def __init__(
        self,
        engine: Optional[VolumeProfileEngine] = None,
        session: Optional[requests.Session] = None,
        fetcher: Optional[Callable[[str, str], List[Dict[str, Any]]]] = None,
        retry_cooldown_seconds: int = 300,
    ):
        self.engine = engine or VolumeProfileEngine(row_size=60, value_area_pct=Decimal("0.70"))
        self._session = session or requests.Session()
        self._fetcher = fetcher
        self._retry_cooldown_seconds = retry_cooldown_seconds
        self._lock = threading.Lock()
        self._cache: Dict[Tuple[str, str], VolumeProfileSnapshot] = {}
        self._failed_at: Dict[Tuple[str, str], float] = {}

    def _fetch_prev_day_candles(self, symbol: str, prev_date_str: str) -> List[Dict[str, Any]]:
        if self._fetcher is not None:
            return self._fetcher(symbol, prev_date_str)

        dt = datetime.datetime.strptime(prev_date_str, "%Y-%m-%d").replace(tzinfo=datetime.timezone.utc)
        start_ms = int(dt.timestamp() * 1000)
        end_ms = int((dt + datetime.timedelta(days=1)).timestamp() * 1000) - 1

        resp = self._session.get(
            self.BINANCE_FAPI_KLINES,
            params={
                "symbol": symbol,
                "interval": "15m",
                "startTime": start_ms,
                "endTime": end_ms,
                "limit": 100,
            },
            timeout=5,
        )
        if resp.status_code != 200:
            return []
        raw = resp.json()
        if not isinstance(raw, list):
            return []
        return [
            {
                "high": c[2],
                "low": c[3],
                "close": c[4],
                "volume": c[5],
            }
            for c in raw
            if isinstance(c, (list, tuple)) and len(c) >= 6
        ]

    def get_previous_day_profile(
        self,
        symbol: str,
        current_time_utc: Optional[datetime.datetime] = None,
    ) -> Optional[VolumeProfileSnapshot]:
        """
        Returns the immutable VolumeProfileSnapshot for the completed UTC day strictly before
        `current_time_utc`. Cached for the entire UTC day. Fail-open (returns None) on API failure.
        """
        now_u = current_time_utc or datetime.datetime.now(datetime.timezone.utc)
        if now_u.tzinfo is None:
            now_u = now_u.replace(tzinfo=datetime.timezone.utc)
        else:
            now_u = now_u.astimezone(datetime.timezone.utc)

        prev_date_str = (now_u.date() - datetime.timedelta(days=1)).isoformat()
        key = (symbol, prev_date_str)

        with self._lock:
            if key in self._cache:
                return self._cache[key]
            last_fail = self._failed_at.get(key)
            if last_fail is not None and (time.time() - last_fail) < self._retry_cooldown_seconds:
                return None

        try:
            candles = self._fetch_prev_day_candles(symbol, prev_date_str)
            snapshot = self.engine.build_profile(symbol, prev_date_str, candles) if candles else None
        except Exception as e:
            logger.debug("DailyVolumeProfileCache fetch failed for %s (%s): %s", symbol, prev_date_str, e)
            snapshot = None

        with self._lock:
            if snapshot is not None:
                # Evict any entries from older UTC dates to guarantee strictly bounded RAM
                stale_keys = [k for k in self._cache if k[1] != prev_date_str]
                for sk in stale_keys:
                    del self._cache[sk]
                self._cache[key] = snapshot
                self._failed_at.pop(key, None)
                return snapshot
            self._failed_at[key] = time.time()
            return None
