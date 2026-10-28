"""
src/quant/macro_specialists.py — Asynchronous Macro Event Risk & Carry Specialists.

Inspired by the specialized multi-agent architecture of TradingAgents (arXiv:2412.20138),
this module houses two dedicated asynchronous surveillance specialists:
1. NewsCatalystSpecialist: Guards against macroeconomic shockwaves (FOMC, CPI, NFP, SEC).
2. CryptoCarrySpecialist: Monitors 8-hour perpetual funding rates & cost-of-carry drag.

Strictly adheres to AGENTS.md Invariant 1 (Zero Float Financial Math).
"""

import datetime
from dataclasses import dataclass
from decimal import Decimal
from typing import Dict, List, Optional, Tuple, Union
import requests

from src.quant.config import DEFAULT_RISK_CONFIG, TOP_10_SYMBOLS


# ==============================================================================
# Domain Verdicts & Dataclasses
# ==============================================================================

@dataclass(frozen=True)
class NewsBlackoutVerdict:
    """Evaluation output from the News & Macro Catalyst Specialist."""
    is_blackout: bool
    event_name: str
    minutes_to_event: Optional[int]
    reason: str


@dataclass(frozen=True)
class CarryVerdict:
    """Evaluation output from the Crypto Carry Specialist."""
    symbol: str
    verdict: str  # "FAVORABLE", "NEUTRAL", "PROHIBITIVE"
    funding_rate: Decimal
    annualized_rate: Decimal
    next_funding_time_utc: Optional[datetime.datetime]
    reason: str


# ==============================================================================
# 1. News & Macro Catalyst Specialist
# ==============================================================================

class NewsCatalystSpecialist:
    """
    Asynchronous event risk specialist.
    Tracks high-volatility economic announcements (FOMC, CPI, NFP) and exchange notices.
    Enforces a strict trading blackout window (default: +/- 30 minutes).
    """

    def __init__(self, blackout_window_minutes: int = 30):
        self.blackout_window_minutes = blackout_window_minutes
        # Scheduled high-impact macro events (ISO formatted UTC timestamps: YYYY-MM-DD HH:MM)
        self.scheduled_events: List[Tuple[datetime.datetime, str]] = []

    def register_event(self, event_time_utc: datetime.datetime, event_name: str) -> None:
        """Register a known macroeconomic announcement."""
        self.scheduled_events.append((event_time_utc, event_name))

    def evaluate_blackout(self, current_time_utc: Optional[datetime.datetime] = None) -> NewsBlackoutVerdict:
        """
        Evaluate if current timestamp is within the blackout window of any high-impact event.
        """
        if current_time_utc is None:
            current_time_utc = datetime.datetime.now(datetime.timezone.utc)
        elif current_time_utc.tzinfo is None:
            current_time_utc = current_time_utc.replace(tzinfo=datetime.timezone.utc)

        for event_time, name in self.scheduled_events:
            if event_time.tzinfo is None:
                event_time = event_time.replace(tzinfo=datetime.timezone.utc)

            delta = event_time - current_time_utc
            delta_minutes = int(delta.total_seconds() / 60)

            # Inside [-blackout_window, +blackout_window]
            if abs(delta_minutes) <= self.blackout_window_minutes:
                action = "Approaching" if delta_minutes >= 0 else "Just Released"
                return NewsBlackoutVerdict(
                    is_blackout=True,
                    event_name=name,
                    minutes_to_event=delta_minutes,
                    reason=f"Blackout Active: {name} is {action} ({abs(delta_minutes)} min difference). New entries suspended."
                )

        return NewsBlackoutVerdict(
            is_blackout=False,
            event_name="",
            minutes_to_event=None,
            reason="Macro calendar clear. No high-impact events within blackout window."
        )


# ==============================================================================
# 2. Crypto Carry & Funding Rate Specialist
# ==============================================================================

class CryptoCarrySpecialist:
    """
    Evaluates 8-hour perpetual funding rates and cost-of-carry economics.
    Prevents holding positions with prohibitive negative yield drag.
    """

    BASE_URL = "https://fapi.binance.com"

    def __init__(self, session: Optional[requests.Session] = None):
        self.session = session or requests.Session()

    def fetch_funding_rates(self, symbol: Optional[str] = None) -> Dict[str, Dict[str, Union[Decimal, datetime.datetime]]]:
        """
        Fetch real-time 8-hour funding rates from Binance Futures public API.
        Enforces Zero Float Financial Math: all numeric fields converted via string to Decimal.
        """
        endpoint = f"{self.BASE_URL}/fapi/v1/premiumIndex"
        params = {}
        if symbol:
            params["symbol"] = symbol

        resp = self.session.get(endpoint, params=params, timeout=5)
        resp.raise_for_status()
        data = resp.json()

        if isinstance(data, dict):
            data = [data]

        results: Dict[str, Dict[str, Union[Decimal, datetime.datetime]]] = {}
        for item in data:
            sym = item.get("symbol")
            if not sym:
                continue
            
            raw_rate = item.get("lastFundingRate", "0.0")
            rate_dec = Decimal(str(raw_rate))
            
            next_time_ms = item.get("nextFundingTime", 0)
            next_time = (
                datetime.datetime.fromtimestamp(next_time_ms / 1000.0, tz=datetime.timezone.utc)
                if next_time_ms else None
            )

            results[sym] = {
                "funding_rate": rate_dec,
                "next_funding_time": next_time,
            }

        return results

    def evaluate_carry(
        self,
        symbol: str,
        side: str,
        funding_rate: Decimal,
        next_funding_time: Optional[datetime.datetime] = None
    ) -> CarryVerdict:
        """
        Evaluate carry viability for a prospective Long or Short trade.
        Annualized rate = funding_rate * 3 * 365.
        """
        side = side.upper()
        annualized = funding_rate * Decimal("3") * Decimal("365")
        prohibitive_ceiling = DEFAULT_RISK_CONFIG.max_prohibitive_funding_rate

        if side == "LONG":
            # For longs, paying high positive funding is prohibitive
            if funding_rate >= prohibitive_ceiling:
                return CarryVerdict(
                    symbol=symbol,
                    verdict="PROHIBITIVE",
                    funding_rate=funding_rate,
                    annualized_rate=annualized,
                    next_funding_time_utc=next_funding_time,
                    reason=f"Prohibitive funding cost ({funding_rate*Decimal('100'):.4f}% 8h / {annualized*Decimal('100'):.1f}% APR). Veto Long."
                )
            elif funding_rate <= Decimal("-0.0001"):
                return CarryVerdict(
                    symbol=symbol,
                    verdict="FAVORABLE",
                    funding_rate=funding_rate,
                    annualized_rate=annualized,
                    next_funding_time_utc=next_funding_time,
                    reason=f"Favorable negative funding ({funding_rate*Decimal('100'):.4f}% 8h). Longs receive carry yield."
                )
            else:
                return CarryVerdict(
                    symbol=symbol,
                    verdict="NEUTRAL",
                    funding_rate=funding_rate,
                    annualized_rate=annualized,
                    next_funding_time_utc=next_funding_time,
                    reason=f"Normal funding environment ({funding_rate*Decimal('100'):.4f}% 8h)."
                )

        elif side == "SHORT":
            # For shorts, paying high negative funding is prohibitive
            if funding_rate <= -prohibitive_ceiling:
                return CarryVerdict(
                    symbol=symbol,
                    verdict="PROHIBITIVE",
                    funding_rate=funding_rate,
                    annualized_rate=annualized,
                    next_funding_time_utc=next_funding_time,
                    reason=f"Prohibitive funding cost for shorts ({funding_rate*Decimal('100'):.4f}% 8h). Veto Short."
                )
            elif funding_rate >= Decimal("0.0001"):
                return CarryVerdict(
                    symbol=symbol,
                    verdict="FAVORABLE",
                    funding_rate=funding_rate,
                    annualized_rate=annualized,
                    next_funding_time_utc=next_funding_time,
                    reason=f"Favorable positive funding ({funding_rate*Decimal('100'):.4f}% 8h). Shorts receive carry yield."
                )
            else:
                return CarryVerdict(
                    symbol=symbol,
                    verdict="NEUTRAL",
                    funding_rate=funding_rate,
                    annualized_rate=annualized,
                    next_funding_time_utc=next_funding_time,
                    reason=f"Normal funding environment ({funding_rate*Decimal('100'):.4f}% 8h)."
                )
        else:
            raise ValueError(f"Unknown side {side}; expected 'LONG' or 'SHORT'")
