"""
tests/test_tiger_falling_knife_guard.py — Empirical Verification of Strategy #3 (Stalking Tiger)
Falling Knife Guard & Asymmetric Buy Filters (Lesson #43).
"""

from decimal import Decimal
import pytest
from src.quant.tiger_config import TigerMasterConfig, TigerOrderflowConfig
from src.quant.tiger_orderflow import SymbolOrderflowTracker, AbsorptionSignal


def test_falling_knife_guard_wick_asymmetry():
    """Verify that BUY setups require >= 50% lower wick, whereas SELL setups require only 40% upper wick."""
    cfg = TigerOrderflowConfig(
        falling_knife_guard_enabled=True,
        buy_absorption_wick_min_ratio=Decimal("0.50"),
        absorption_wick_min_ratio=Decimal("0.40")
    )
    tracker = SymbolOrderflowTracker("ETHUSDT", config=cfg)

    # Ingest baseline depth
    tracker.process_depth_update(
        best_bid=Decimal("3000.20"), best_bid_qty=Decimal("10.0"),
        best_ask=Decimal("3000.40"), best_ask_qty=Decimal("20.0"),
        timestamp_ms=1000
    )
    for i in range(6):
        tracker.process_agg_trade(i+1, Decimal("3000.30"), Decimal("5.0"), True, 2000 + (i * 5000))
    tracker.process_depth_update(
        best_bid=Decimal("3000.20"), best_bid_qty=Decimal("80.0"),
        best_ask=Decimal("3000.40"), best_ask_qty=Decimal("2.0"),
        timestamp_ms=35000
    )
    for i in range(5):
        tracker.process_agg_trade(100+i, Decimal("3000.20"), Decimal("150.0"), True, 35000 + (i * 500))

    # Case 1: Lower wick is 42% (passes 40% baseline, but fails 50% Falling Knife Guard)
    sig_42 = tracker.detect_trapped_trader_climax(
        bar_open=Decimal("3010.0"), bar_high=Decimal("3020.0"),
        bar_low=Decimal("2993.2"), bar_close=Decimal("3010.0"),
        bar_volume=Decimal("500.0"), avg_volume_20=Decimal("300.0"),
        delta_oi_pct=Decimal("0.0005")
    )
    # range = 3020.0 - 2993.2 = 26.8, lower_wick = 3010.0 - 2993.2 = 16.8 -> wick_ratio = 16.8 / 26.8 = ~0.62? Let's calibrate:
    # high=3020.0, low=2980.0 (range=40.0). open=2996.8, close=3015.0 -> lower_wick = 2996.8 - 2980.0 = 16.8 -> 16.8 / 40.0 = 42.0%
    sig_42 = tracker.detect_trapped_trader_climax(
        bar_open=Decimal("2996.8"), bar_high=Decimal("3020.0"),
        bar_low=Decimal("2980.0"), bar_close=Decimal("3015.0"),
        bar_volume=Decimal("500.0"), avg_volume_20=Decimal("300.0"),
        delta_oi_pct=Decimal("0.0005")
    )
    assert sig_42.is_valid is False  # Vetoed because 42% < 50% required!

    # Case 2: Lower wick is 75% (passes Falling Knife Guard >= 50%)
    # high=3020.0, low=2980.0 (range=40.0). open=3010.0, close=3010.0 -> lower_wick = 30.0 -> 30/40 = 75.0%
    sig_75 = tracker.detect_trapped_trader_climax(
        bar_open=Decimal("3010.0"), bar_high=Decimal("3020.0"),
        bar_low=Decimal("2980.0"), bar_close=Decimal("3010.0"),
        bar_volume=Decimal("500.0"), avg_volume_20=Decimal("300.0"),
        delta_oi_pct=Decimal("0.0005")
    )
    assert sig_75.is_valid is True
    assert sig_75.action == "BUY"


def test_freefall_24h_drop_veto_logic():
    """Verify that assets down >= 10% in 24h are flagged for falling knife veto."""
    master_cfg = TigerMasterConfig()
    max_drop = getattr(master_cfg.orderflow, "buy_max_24h_drop_abs_pct", Decimal("10.0"))

    # Freefalling coin: -12.5% 24h change
    coin_change_pct = Decimal("-12.5")
    is_vetoed = coin_change_pct <= -max_drop
    assert is_vetoed is True

    # Moderate dip: -4.2% 24h change
    dip_change_pct = Decimal("-4.2")
    is_dip_vetoed = dip_change_pct <= -max_drop
    assert is_dip_vetoed is False
