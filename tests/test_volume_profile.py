import datetime
from decimal import Decimal
import pytest

from src.quant.volume_profile import (
    DailyVolumeProfileCache,
    VolumeProfileEngine,
)
from src.quant.orchestrator import QuantBotOrchestrator
from src.quant.kronos_onnx_engine import TrajectoryVerdict
from src.quant.apex_scalper import ApexScalperEngine
from src.quant.tiger_scalper import TigerExecutionEngine
from src.quant.tiger_orderflow import AbsorptionSignal


def _sample_profile(symbol: str = "ETHUSDT"):
    engine = VolumeProfileEngine(row_size=20, value_area_pct=Decimal("0.70"))
    # Dense HVN cluster at 100-102 (pPOC ~ 101.0), thin tail up to 110
    candles = [
        {"high": "102.0", "low": "100.0", "close": "101.0", "volume": "900"},
        {"high": "110.0", "low": "102.0", "close": "109.5", "volume": "100"},
    ]
    return engine.build_profile(symbol, "2026-11-15", candles)


def test_volume_conservation_and_poc_localization():
    engine = VolumeProfileEngine(row_size=20, value_area_pct=Decimal("0.70"))
    candles = [
        {"high": "110.0", "low": "100.0", "close": "105.0", "volume": "100"},
        {"high": "106.0", "low": "104.0", "close": "105.2", "volume": "800"},
        {"high": "105.5", "low": "104.5", "close": "105.0", "volume": "1100"},
    ]
    prof = engine.build_profile("BTCUSDT", "2026-11-15", candles)
    assert prof is not None
    assert prof.total_volume == Decimal("2000")
    bin_sum = sum(prof.bin_volumes, Decimal("0"))
    assert abs(bin_sum - prof.total_volume) < Decimal("0.0001")
    assert Decimal("104.5") <= prof.poc <= Decimal("105.5")
    assert prof.session_low <= prof.val <= prof.poc <= prof.vah <= prof.session_high
    assert prof.prior_close_regime == "INSIDE_VA"
    assert prof.is_balanced_prior_day is True


def test_spatial_veto_poc_hvn_and_fading_breakout():
    prof = _sample_profile("ETHUSDT")
    assert prof is not None
    assert prof.prior_close_regime == "ABOVE_VA"

    # 1. Fail-open when profile is None
    res_none = VolumeProfileEngine.evaluate_spatial_veto(None, Decimal("105"), "BUY")
    assert res_none.approved is True

    # 2. H1: BUY just below pPOC => VP_FIRING_INTO_POC
    res_poc = VolumeProfileEngine.evaluate_spatial_veto(
        prof, entry_price=prof.poc * Decimal("0.996"), side="BUY", veto_firing_into_poc=True, veto_hvn_chop=False
    )
    assert res_poc.approved is False
    assert res_poc.veto_code == "VP_FIRING_INTO_POC"

    # 3. H4: Entry right inside dense HVN (100-102) moving away from POC => VP_HVN_CHOP
    res_hvn = VolumeProfileEngine.evaluate_spatial_veto(
        prof, entry_price=Decimal("101.80"), side="BUY", veto_firing_into_poc=True, veto_hvn_chop=True
    )
    assert res_hvn.approved is False
    assert res_hvn.veto_code == "VP_HVN_CHOP"

    # 4. Breakout above pVAH (price discovery): BUY passes everywhere
    res_breakout_buy = VolumeProfileEngine.evaluate_spatial_veto(
        prof, entry_price=Decimal("112.00"), side="BUY",
        veto_firing_into_poc=True, veto_hvn_chop=True, veto_fading_breakout=True
    )
    assert res_breakout_buy.approved is True

    # 5. Tiger FADING_BREAKOUT: SELL above pVAH blocked when veto_fading_breakout=True, allowed when False
    res_fade_tiger = VolumeProfileEngine.evaluate_spatial_veto(
        prof, entry_price=Decimal("112.00"), side="SELL",
        veto_firing_into_poc=True, veto_hvn_chop=True, veto_fading_breakout=True
    )
    assert res_fade_tiger.approved is False
    assert res_fade_tiger.veto_code == "VP_FADING_BREAKOUT"

    res_fade_macro = VolumeProfileEngine.evaluate_spatial_veto(
        prof, entry_price=Decimal("112.00"), side="SELL",
        veto_firing_into_poc=True, veto_hvn_chop=True, veto_fading_breakout=False
    )
    assert res_fade_macro.approved is True


def test_daily_volume_profile_cache_eviction_and_dedup():
    calls = []

    def fake_fetcher(sym: str, date_str: str):
        calls.append((sym, date_str))
        return [
            {"high": "102.0", "low": "100.0", "close": "101.0", "volume": "900"},
            {"high": "106.0", "low": "102.0", "close": "105.0", "volume": "100"},
        ]

    cache = DailyVolumeProfileCache(fetcher=fake_fetcher)
    day1 = datetime.datetime(2026, 11, 16, 10, 0, tzinfo=datetime.timezone.utc)
    day1_later = datetime.datetime(2026, 11, 16, 22, 0, tzinfo=datetime.timezone.utc)
    day2 = datetime.datetime(2026, 11, 17, 1, 0, tzinfo=datetime.timezone.utc)

    p1 = cache.get_previous_day_profile("BTCUSDT", day1)
    p1_cached = cache.get_previous_day_profile("BTCUSDT", day1_later)
    assert p1 is not None
    assert p1 is p1_cached
    assert len(calls) == 1
    assert calls[0] == ("BTCUSDT", "2026-11-15")

    # Next UTC day fetches new prior day and evicts old date
    p2 = cache.get_previous_day_profile("BTCUSDT", day2)
    assert p2 is not None
    assert p2.session_date_utc == "2026-11-16"
    assert len(calls) == 2
    assert len(cache._cache) == 1


def test_orchestrator_macro_vp_veto_integration():
    prof = _sample_profile("ETHUSDT")
    assert prof is not None

    orch = QuantBotOrchestrator(enable_volume_profile_veto=True)
    # Build mock trajectory firing directly into pPOC / HVN at 100.60 BUY
    traj_blocked = TrajectoryVerdict(
        symbol="ETHUSDT",
        current_price=Decimal("100.60"),
        terminal_price=Decimal("105.00"),
        path_high=Decimal("106.00"),
        path_low=Decimal("99.50"),
        raw_drift=Decimal("0.0437"),
        dynamic_take_profit=Decimal("104.00"),
        dynamic_stop_loss=Decimal("99.00"),
        proposed_side="LONG",
        horizon_hours=12,
        rationale="Mock trajectory into pPOC/HVN",
    )
    now_utc = datetime.datetime(2026, 11, 16, 10, 0, tzinfo=datetime.timezone.utc)
    report = orch.run_scan_cycle(
        account_equity=Decimal("200.00"),
        current_time_utc=now_utc,
        mock_trajectories={"ETHUSDT": traj_blocked},
        mock_volume_profiles={"ETHUSDT": prof},
        execution_mode="PAPER",
    )
    dec = report.decisions.get("ETHUSDT")
    assert dec is not None
    assert dec.approved is False
    assert dec.veto_gate_failed in ("VP_FIRING_INTO_POC", "VP_HVN_CHOP")


def test_apex_scalper_vp_veto_integration():
    prof = _sample_profile("ETHUSDT")
    assert prof is not None
    scalper = ApexScalperEngine()

    # Construct a valid bullish liquidation flush wick at 101.50 (inside HVN!)
    klines = []
    for i in range(14):
        if i == 12:  # confirmed [-2] absorption hammer
            klines.append({
                "open": Decimal("101.60"),
                "high": Decimal("101.70"),
                "low": Decimal("100.20"),
                "close": Decimal("101.50"),
                "volume": Decimal("500"),
                "quote_volume": Decimal("50000"),
            })
        else:
            klines.append({
                "open": Decimal("101.40"),
                "high": Decimal("101.80"),
                "low": Decimal("101.10"),
                "close": Decimal("101.50"),
                "volume": Decimal("100"),
                "quote_volume": Decimal("10000"),
            })

    cand_no_vp = scalper.evaluate_microstructure_candidate(
        symbol="ETHUSDT",
        current_price=Decimal("101.50"),
        best_bid=Decimal("101.49"),
        best_ask=Decimal("101.51"),
        order_book_imbalance=Decimal("0.75"),
        recent_klines=klines,
        bnb_discount=True,
        micro_skew_bps=Decimal("2.0"),
        volume_profile=None,
    )
    assert cand_no_vp is not None

    # Same exact setup vetoed when HVN Volume Profile is attached
    cand_with_vp = scalper.evaluate_microstructure_candidate(
        symbol="ETHUSDT",
        current_price=Decimal("101.50"),
        best_bid=Decimal("101.49"),
        best_ask=Decimal("101.51"),
        order_book_imbalance=Decimal("0.75"),
        recent_klines=klines,
        bnb_discount=True,
        micro_skew_bps=Decimal("2.0"),
        volume_profile=prof,
    )
    assert cand_with_vp is None


def test_tiger_scalper_fading_breakout_veto_integration(tmp_path):
    prof = _sample_profile("ETHUSDT")
    assert prof is not None
    engine = TigerExecutionEngine(state_file=str(tmp_path / "tiger_state.json"))
    now_utc = datetime.datetime(2026, 11, 16, 12, 0, tzinfo=datetime.timezone.utc)

    # SELL above pVAH (112.00) => FADING_BREAKOUT => Vetoed by Tiger!
    fade_sig = AbsorptionSignal(
        symbol="ETHUSDT",
        action="SELL",
        entry_trigger_price=Decimal("112.00"),
        invalidation_stop_price=Decimal("113.00"),
        cvd_zscore=Decimal("2.8"),
        micro_price_skew_bps=Decimal("-1.5"),
        ofi_score=Decimal("-0.6"),
        wick_ratio=Decimal("0.55"),
        absorption_density=Decimal("0.85"),
        is_steamroller_vetoed=False,
        is_valid=True,
        reason="Test trapped bulls",
    )
    res_vetoed = engine.create_signal_from_absorption(
        fade_sig, atr_pct=Decimal("0.01"), current_time_utc=now_utc, volume_profile=prof
    )
    assert res_vetoed is None

    # BUY above pVAH (112.00) => BREAKOUT_WITH_TREND => Approved!
    trend_sig = AbsorptionSignal(
        symbol="ETHUSDT",
        action="BUY",
        entry_trigger_price=Decimal("112.00"),
        invalidation_stop_price=Decimal("111.00"),
        cvd_zscore=Decimal("-2.8"),
        micro_price_skew_bps=Decimal("1.5"),
        ofi_score=Decimal("0.6"),
        wick_ratio=Decimal("0.55"),
        absorption_density=Decimal("0.85"),
        is_steamroller_vetoed=False,
        is_valid=True,
        reason="Test trapped bears",
    )
    res_ok = engine.create_signal_from_absorption(
        trend_sig, atr_pct=Decimal("0.01"), current_time_utc=now_utc, volume_profile=prof
    )
    assert res_ok is not None
    assert res_ok.action == "BUY"


def test_empty_and_flat_session_handling():
    engine = VolumeProfileEngine(row_size=60)
    assert engine.build_profile("SOLUSDT", "2026-11-15", []) is None

    flat = engine.build_profile("SOLUSDT", "2026-11-15", [{"high": "100", "low": "100", "close": "100", "volume": "50"}])
    assert flat is not None
    assert flat.poc == Decimal("100")
    assert flat.vah == Decimal("100")
    assert flat.val == Decimal("100")
