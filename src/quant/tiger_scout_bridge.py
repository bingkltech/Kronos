"""
src/quant/tiger_scout_bridge.py — Sub-Second Nano Reconnaissance Bridge for Macro Orchestrator.

Passes real-time microstructural orderflow intelligence from Strategy #3 (Stalking Tiger)
directly into Strategy #1 (Macro Storm Protocol):
1. Ingests sub-second orderflow telemetry (CVD z-score, Stoikov micro-price skew, OFI, ΔOI).
2. Dynamically scouts and feeds high-liquidity Hot Prey candidates (Rank 1-2, >=$50M turnover)
   into Macro's candidate pool for full multi-gate validation.
3. Provides nano-orderflow confluence confirmation (+20% Kelly boost) and adversarial
   conflict detection (-30% Kelly throttle or veto) to avoid buying tops or shorting bottoms.

Strictly adheres to:
- AGENTS.md Invariant 1: Zero Float Financial Math (decimal.Decimal everywhere).
- Full Macro Workflow Preservation: Scouted assets must pass all 6 Supreme KEV Veto Gates.
"""

import os
import json
import time
import datetime
import logging
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, List, Optional, Tuple, Any

logger = logging.getLogger("TigerScoutBridge")


@dataclass(frozen=True)
class PreyNanoTelemetry:
    """Sub-second orderflow and structural intelligence for a scouted prey asset."""
    symbol: str
    rank: int
    last_price: Decimal
    price_change_pct: Decimal
    turnover_24h_usd: Decimal
    volatility_score: Decimal
    dynamic_strength_pct: Decimal
    delta_oi_pct: Decimal
    cvd_zscore: Decimal = Decimal("0.0")
    micro_skew_bps: Decimal = Decimal("0.0")
    ofi_score: Decimal = Decimal("0.0")
    spread_bps: Decimal = Decimal("0.0")
    absorption_signal: str = "NONE"       # "BUY", "SELL", or "NONE"
    stagnation_status: str = "ACTIVE"
    is_quarantined: bool = False


@dataclass
class TigerScoutReport:
    """Unified nano-reconnaissance report from Stalking Tiger to Macro Orchestrator."""
    updated_at_utc: Optional[datetime.datetime]
    ws_ticks: int
    btc_1m_return_pct: Decimal
    btc_cvd_zscore: Decimal
    quarantined_symbols: List[str]
    active_prey: Dict[str, PreyNanoTelemetry]


class TigerScoutBridge:
    """
    Sub-second Nano Reconnaissance Bridge connecting Stalking Tiger with Macro Orchestrator.
    Thread-safe, read-only consumer of tiger_radar.json telemetry.
    """
    def __init__(
        self,
        radar_paths: Optional[List[str]] = None,
        cache_ttl_seconds: float = 15.0
    ):
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        self.radar_paths = radar_paths or [
            os.path.join(project_root, "data", "tiger_radar.json"),
            "data/tiger_radar.json",
            "/home/ec2-user/kronos-bot/data/tiger_radar.json",
            "/home/ec2-user/data/tiger_radar.json"
        ]
        self.cache_ttl_seconds = cache_ttl_seconds
        self._cached_report: Optional[TigerScoutReport] = None
        self._last_read_ts: float = 0.0

    def load_report(self, force_refresh: bool = False) -> Optional[TigerScoutReport]:
        """
        Load and parse the latest tiger_radar.json report with Zero Float Math.
        Caches in memory for up to cache_ttl_seconds to eliminate redundant disk I/O.
        """
        now = time.time()
        if not force_refresh and self._cached_report is not None and (now - self._last_read_ts < self.cache_ttl_seconds):
            return self._cached_report

        radar_file = None
        for p in self.radar_paths:
            if os.path.exists(p):
                radar_file = p
                break

        if not radar_file:
            return None

        try:
            with open(radar_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            updated_str = data.get("updated_at_utc")
            updated_dt = datetime.datetime.fromisoformat(updated_str) if updated_str else None
            if updated_dt and updated_dt.tzinfo is None:
                updated_dt = updated_dt.replace(tzinfo=datetime.timezone.utc)

            prey_map: Dict[str, PreyNanoTelemetry] = {}
            for item in data.get("active_prey", []):
                sym = item.get("symbol")
                if not sym:
                    continue
                telemetry = PreyNanoTelemetry(
                    symbol=sym,
                    rank=int(item.get("rank", 99)),
                    last_price=Decimal(str(item.get("last_price", "0.0"))),
                    price_change_pct=Decimal(str(item.get("price_change_pct", "0.0"))),
                    turnover_24h_usd=Decimal(str(item.get("turnover_24h_usd", "0.0"))),
                    volatility_score=Decimal(str(item.get("volatility_score", "0.0"))),
                    dynamic_strength_pct=Decimal(str(item.get("dynamic_strength_pct", "0.0"))),
                    delta_oi_pct=Decimal(str(item.get("delta_oi_pct", "0.0"))),
                    cvd_zscore=Decimal(str(item.get("cvd_zscore", "0.0"))),
                    micro_skew_bps=Decimal(str(item.get("micro_skew_bps", item.get("micro_price_skew_bps", "0.0")))),
                    ofi_score=Decimal(str(item.get("ofi_score", "0.0"))),
                    spread_bps=Decimal(str(item.get("spread_bps", "0.0"))),
                    absorption_signal=str(item.get("absorption_signal", "NONE")).upper(),
                    stagnation_status=str(item.get("stagnation_status", "ACTIVE")).upper(),
                    is_quarantined=bool(item.get("is_quarantined", False))
                )
                prey_map[sym] = telemetry

            report = TigerScoutReport(
                updated_at_utc=updated_dt,
                ws_ticks=int(data.get("ws_ticks", 0)),
                btc_1m_return_pct=Decimal(str(data.get("btc_1m_return_pct", "0.0"))),
                btc_cvd_zscore=Decimal(str(data.get("btc_cvd_zscore", "0.0"))),
                quarantined_symbols=list(data.get("quarantined_symbols", [])),
                active_prey=prey_map
            )
            self._cached_report = report
            self._last_read_ts = now
            return report

        except Exception as e:
            logger.debug("Failed to load tiger radar report: %s", e)
            return self._cached_report

    def get_scouted_prey_candidates(
        self,
        existing_universe: List[str],
        max_candidates: int = 2,
        min_turnover_usd: Decimal = Decimal("50000000.00")
    ) -> List[PreyNanoTelemetry]:
        """
        Extracts top unquarantined Hot Prey candidates that meet institutional turnover floors.
        Filters out any coins already present in the macro universe.
        """
        report = self.load_report()
        if not report or not report.active_prey:
            return []

        candidates: List[PreyNanoTelemetry] = []
        # Sort by rank ascending (Rank 1 is highest priority)
        sorted_prey = sorted(report.active_prey.values(), key=lambda p: p.rank)

        for p in sorted_prey:
            if p.symbol in existing_universe:
                continue
            if p.is_quarantined or p.symbol in report.quarantined_symbols:
                continue
            if p.stagnation_status != "ACTIVE":
                continue
            if p.turnover_24h_usd < min_turnover_usd:
                continue

            candidates.append(p)
            if len(candidates) >= max_candidates:
                break

        return candidates

    def evaluate_nano_confluence(
        self,
        symbol: str,
        proposed_side: str
    ) -> Tuple[bool, Decimal, str]:
        """
        Evaluates whether Tiger's sub-second orderflow confirms or conflicts with Macro's trajectory.
        
        Returns:
            (is_confirmed, multiplier_boost, reason_note)
            
            - Positive Confluence: Multiplier boosted to 1.20x (+20% Kelly sizing & conviction).
            - Severe Conflict: Multiplier throttled to 0.70x (-30% Kelly sizing, anti-exhaustion guard).
            - Neutral / Untracked: Multiplier remains 1.00x.
        """
        report = self.load_report()
        if not report or symbol not in report.active_prey:
            return True, Decimal("1.00"), "NANO_NEUTRAL: Symbol not actively tracked in Tiger Hot Prey pool."

        prey = report.active_prey[symbol]
        side = proposed_side.upper()

        if side in ("LONG", "BUY"):
            # 1. Trapped Bears Spring Confluence (Confirmation)
            is_spring = (
                prey.absorption_signal == "BUY" or
                (prey.cvd_zscore <= Decimal("-1.2") and prey.delta_oi_pct >= Decimal("0")) or
                (prey.micro_skew_bps >= Decimal("0.15") and prey.ofi_score >= Decimal("0.20"))
            )
            if is_spring:
                return (
                    True,
                    Decimal("1.20"),
                    f"NANO_CONFLUENCE_CONFIRMED: Trapped bears spring (CVD z={prey.cvd_zscore:+.1f}, skew={prey.micro_skew_bps:+.2f}bps, ΔOI={prey.delta_oi_pct:+.2f}%). Multiplier: +20%."
                )

            # 2. Trapped Bulls Climax Conflict (Exhaustion at Resistance)
            is_climax_conflict = (
                prey.absorption_signal == "SELL" or
                (prey.cvd_zscore >= Decimal("2.0") and prey.micro_skew_bps <= Decimal("-0.20"))
            )
            if is_climax_conflict:
                return (
                    False,
                    Decimal("0.70"),
                    f"NANO_CONFLICT_WARNING: Trapped bulls climax rejected at high (CVD z={prey.cvd_zscore:+.1f}, skew={prey.micro_skew_bps:+.2f}bps). Multiplier: -30%."
                )

            return True, Decimal("1.00"), "NANO_NEUTRAL: Orderflow metrics within normal variance."

        elif side in ("SHORT", "SELL"):
            # 1. Trapped Bulls Climax Confluence (Confirmation)
            is_climax = (
                prey.absorption_signal == "SELL" or
                (prey.cvd_zscore >= Decimal("1.2") and prey.delta_oi_pct >= Decimal("0")) or
                (prey.micro_skew_bps <= Decimal("-0.15") and prey.ofi_score <= Decimal("-0.20"))
            )
            if is_climax:
                return (
                    True,
                    Decimal("1.20"),
                    f"NANO_CONFLUENCE_CONFIRMED: Trapped bulls climax (CVD z={prey.cvd_zscore:+.1f}, skew={prey.micro_skew_bps:+.2f}bps, ΔOI={prey.delta_oi_pct:+.2f}%). Multiplier: +20%."
                )

            # 2. Trapped Bears Spring Conflict (Exhaustion at Support)
            is_spring_conflict = (
                prey.absorption_signal == "BUY" or
                (prey.cvd_zscore <= Decimal("-2.0") and prey.micro_skew_bps >= Decimal("0.20"))
            )
            if is_spring_conflict:
                return (
                    False,
                    Decimal("0.70"),
                    f"NANO_CONFLICT_WARNING: Trapped bears spring bouncing at low (CVD z={prey.cvd_zscore:+.1f}, skew={prey.micro_skew_bps:+.2f}bps). Multiplier: -30%."
                )

            return True, Decimal("1.00"), "NANO_NEUTRAL: Orderflow metrics within normal variance."

        return True, Decimal("1.00"), "NANO_NEUTRAL: Neutral trajectory."
