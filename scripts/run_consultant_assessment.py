#!/usr/bin/env python3
"""
scripts/run_consultant_assessment.py — Run Advisory Consultant & Mathematical Audit.

Usage:
    python scripts/run_consultant_assessment.py [symbols...]
"""

import os
import sys
from decimal import Decimal
from datetime import datetime, timezone

WORKSPACE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if WORKSPACE_ROOT not in sys.path:
    sys.path.insert(0, WORKSPACE_ROOT)

from src.quant.config import ALL_SUPPORTED_SYMBOLS, DEFAULT_RISK_CONFIG
from src.quant.orchestrator import QuantBotOrchestrator
from src.quant.advisory_consultant import AdvisoryConsultantEngine


def main():
    symbols = sys.argv[1:] if len(sys.argv) > 1 else ["BTCUSDT", "ETHUSDT", "SOLUSDT", "1000PEPEUSDT"]

    print("==========================================================================================")
    print(" [Kronos] Sovereign Advisory Consultant & Mathematical Audit Engine")
    print(f" Timestamp: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print(" Formulation: Tri-Perspective Adversarial Conviction Ratio (ACR)")
    print(" Formula    : ACR = (C_bull * (1 - P_bear)) / (1 + R_drag)")
    print("==========================================================================================")

    # Initialize live index engine from QuantBotOrchestrator
    bot = QuantBotOrchestrator(
        symbols_config=ALL_SUPPORTED_SYMBOLS,
        risk_config=DEFAULT_RISK_CONFIG
    )
    consultant = AdvisoryConsultantEngine()

    results = []
    for sym in symbols:
        try:
            klines = bot.index_engine.fetch_recent_klines(sym, interval="5m", limit=24)
            if not klines:
                continue
            curr_price = klines[-1]["close"]
            micro = bot.index_engine.fetch_order_book_microstructure(sym, depth_limit=15)
            vp = bot.volume_profile_cache.get_previous_day_profile(sym, datetime.now(timezone.utc))
            poc = vp.poc if vp else None

            assessment = consultant.assess_instrument(
                symbol=sym,
                current_price=curr_price,
                order_book_imbalance=micro.obi,
                micro_skew_bps=micro.micro_skew_bps,
                recent_klines=klines,
                volume_profile_poc=poc,
                funding_rate_bps=Decimal("0.5")
            )
            results.append(assessment)
        except Exception as e:
            print(f"[-] Error assessing {sym}: {e}")

    # Display Institutional Assessment Table
    fmt_hdr = "{:<12} {:<12} {:<14} {:<8} {:<8} {:<8} {:<8} {:<16}"
    fmt_row = "{:<12} ${:<11.4f} {:<14} {:<8.2f} {:<8.2f} {:<8.2f} {:<8.4f} {:<16}"
    print(fmt_hdr.format("SYMBOL", "PRICE", "RATING", "C_BULL", "P_BEAR", "R_DRAG", "ACR", "VERDICT"))
    print("-" * 90)

    for r in results:
        a = r.audit
        print(fmt_row.format(
            r.symbol,
            float(r.current_price),
            r.rating,
            float(a.bull_conviction),
            float(a.bear_trap_risk),
            float(a.friction_drag_ratio),
            float(a.acr_score),
            a.risk_verdict
        ))

    print("==========================================================================================")
    print(" Detailed Consultant Intelligence Briefs:")
    print("-" * 90)
    for r in results:
        a = r.audit
        print(f"\n>> [{r.symbol}] Rating: {r.rating} | ACR: {a.acr_score} | Bias: {r.direction_bias}")
        print(f"   * Bull Thesis      : {a.bull_thesis}")
        print(f"   * Bear Trap Risk   : {a.bear_antithesis}")
        print(f"   * Technical Micro  : OBI={r.technical_indicators['order_book_imbalance']*100:+.1f}%, Skew={r.technical_indicators['micro_skew_bps']:+.1f}bps, POC Aligned={r.volume_profile_poc_aligned}")
        print(f"   * Strategic Action : {r.recommended_action}")
    print("\n==========================================================================================")


if __name__ == "__main__":
    main()
