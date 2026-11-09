"""
Unit Tests for ApexScalperEngine
Verifies:
1. Candidate evaluation with fee hurdle and OBI gates.
2. Apex candidate ranking and selection.
3. Strict single-slot mutual exclusion (N=1).
4. In-trade path updates (MAE/MFE tracking).
5. 46-item forensics post-mortem upon trade close.
6. 10-trade batch milestone learning audit trigger.
"""

from decimal import Decimal
import datetime
import pytest

from src.quant.apex_scalper import ApexScalperEngine, ScalpCandidate


def test_apex_candidate_evaluation_and_ranking():
    engine = ApexScalperEngine()
    
    # Candidate 1: SOL with high net drift, good volume, positive OBI
    sol_cand = engine.evaluate_candidate(
        symbol="SOLUSDT",
        current_price=Decimal("150.00"),
        predicted_drift_pct=Decimal("1.50"),
        atr_5m=Decimal("1.20"),
        atr_baseline=Decimal("1.00"),
        order_book_imbalance=Decimal("0.45"),
        spread_bps=Decimal("1.5")
    )
    assert sol_cand is not None
    assert sol_cand.symbol == "SOLUSDT"
    assert sol_cand.side == "BUY"
    assert sol_cand.score > Decimal("0.35")

    # Candidate 2: BTC with neutral/chop OBI and low volume that fails microstructure gates
    btc_cand = engine.evaluate_candidate(
        symbol="BTCUSDT",
        current_price=Decimal("60000.00"),
        predicted_drift_pct=Decimal("0.10"),
        atr_5m=Decimal("50.00"),
        atr_baseline=Decimal("50.00"),
        order_book_imbalance=Decimal("0.05"), # Fails OBI squeeze (>0.35) and flush (>0.10)
        spread_bps=Decimal("0.5")
    )
    assert btc_cand is None

    # Candidate 3: ETH with moderate drift
    eth_cand = engine.evaluate_candidate(
        symbol="ETHUSDT",
        current_price=Decimal("3000.00"),
        predicted_drift_pct=Decimal("0.90"),
        atr_5m=Decimal("15.00"),
        atr_baseline=Decimal("14.00"),
        order_book_imbalance=Decimal("0.20"),
        spread_bps=Decimal("1.2")
    )
    assert eth_cand is not None

    # Select the #1 apex candidate among the eligible
    apex = engine.select_apex_candidate([sol_cand, eth_cand])
    assert apex is not None
    assert apex.symbol == "SOLUSDT"  # SOL had higher score


def test_single_slot_concurrency_and_trade_flow():
    engine = ApexScalperEngine()
    assert engine.is_slot_available is True

    sol_cand = engine.evaluate_candidate(
        symbol="SOLUSDT",
        current_price=Decimal("150.00"),
        predicted_drift_pct=Decimal("1.50"),
        atr_5m=Decimal("1.20"),
        atr_baseline=Decimal("1.00"),
        order_book_imbalance=Decimal("0.45"),
        spread_bps=Decimal("1.5")
    )
    assert sol_cand is not None

    t0 = datetime.datetime.now(datetime.timezone.utc)
    # Open 1 scalp position
    pos = engine.open_scalp(sol_cand, account_equity=Decimal("2000.00"), position_id="SCALP-001", current_time_utc=t0)
    assert pos is not None
    assert engine.is_slot_available is False  # Slot is now LOCKED (N=1)

    # Attempting to open another scalp while slot is occupied MUST fail
    second_open = engine.open_scalp(sol_cand, account_equity=Decimal("2000.00"), position_id="SCALP-002", current_time_utc=t0)
    assert second_open is None

    # Update path
    engine.update_in_trade_path(Decimal("152.00")) # MFE rises
    engine.update_in_trade_path(Decimal("149.80")) # MAE drops

    # Close scalp at profit
    t1 = t0 + datetime.timedelta(minutes=15)
    telemetry = engine.close_scalp(
        exit_price=Decimal("152.00"),
        close_reason="TAKE_PROFIT_HIT",
        current_time_utc=t1,
        exchange_fees_usd=Decimal("0.20"),
        trade_mode="LIVE"
    )

    assert telemetry.trade_id == "SCALP-001"
    assert telemetry.root_cause_diagnosis == "CONVICTION_WIN"
    assert engine.is_slot_available is True  # Slot is now FREE again


def test_ten_trade_batch_learning_audit():
    engine = ApexScalperEngine()
    t0 = datetime.datetime.now(datetime.timezone.utc)

    # Simulate 10 sequential scalps to trigger batch learning
    for i in range(10):
        cand = engine.evaluate_candidate(
            symbol="SOLUSDT",
            current_price=Decimal("150.00"),
            predicted_drift_pct=Decimal("1.20"),
            atr_5m=Decimal("1.00"),
            atr_baseline=Decimal("1.00"),
            order_book_imbalance=Decimal("0.30"),
            spread_bps=Decimal("1.0")
        )
        engine.open_scalp(cand, account_equity=Decimal("1000.00"), position_id=f"SCALP-{i:03d}", current_time_utc=t0)
        
        # 7 stop inside noise losses, 3 wins
        if i < 7:
            # Simulate adverse noise excursion (149.20) and target reached (153.65 >= tp 153.59)
            # but stopped out prematurely inside noise
            engine.update_in_trade_path(Decimal("149.20"))
            engine.update_in_trade_path(Decimal("153.65"))
            engine.close_scalp(
                exit_price=Decimal("149.20"),
                close_reason="STOP_LOSS_HIT",
                current_time_utc=t0 + datetime.timedelta(minutes=10),
                exchange_fees_usd=Decimal("0.10"),
                trade_mode="LIVE"
            )
        else:
            engine.update_in_trade_path(Decimal("153.65"))
            engine.close_scalp(
                exit_price=Decimal("153.65"),
                close_reason="TAKE_PROFIT_HIT",
                current_time_utc=t0 + datetime.timedelta(minutes=12),
                exchange_fees_usd=Decimal("0.10"),
                trade_mode="LIVE"
            )

    # Verify that the 10-trade batch milestone triggered automatically
    assert len(engine.closed_scalp_records) == 10
    assert len(engine.learning_audits) == 1
    
    audit = engine.learning_audits[0]
    assert audit.batch_size == 10
    assert audit.win_rate_pct == Decimal("30.0")
    assert audit.dominant_root_cause == "STOP_INSIDE_NOISE"
    assert audit.recalibrated_atr_mult == Decimal("1.25")
    assert "Stop Inside Noise" in audit.recommended_remedy


def test_evaluate_ratchet_volatility_buffered():
    """Verify that evaluate_ratchet moves Stop-Loss to Entry + Fees when price expands >= +0.40%."""
    engine = ApexScalperEngine()
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    cand = ScalpCandidate(
        symbol="SOLUSDT",
        side="BUY",
        score=Decimal("0.80"),
        expected_net_drift_pct=Decimal("0.015"),
        atr_5m=Decimal("1.50"),
        atr_ratio=Decimal("1.2"),
        order_book_imbalance=Decimal("0.45"),
        spread_bps=Decimal("1.0"),
        entry_price=Decimal("100.00"),
        take_profit=Decimal("102.50"),
        stop_loss=Decimal("99.50"),
        reward_risk_ratio=Decimal("5.0")
    )
    pos = engine.open_scalp(cand, account_equity=Decimal("200.00"), position_id="TEST-1", current_time_utc=now_utc)
    assert pos is not None
    assert pos.stop_loss == Decimal("99.50")
    assert not pos.ratchet_active

    # 1. Price moves up +0.20% (below +0.40% threshold): ratchet should NOT fire
    triggered, new_sl = engine.evaluate_ratchet(Decimal("100.20"), fee_friction_pct=Decimal("0.10"))
    assert not triggered
    assert new_sl is None
    assert engine.active_scalp.stop_loss == Decimal("99.50")

    # 2. Price moves up +0.55% (net +0.45%, above +0.40% threshold): ratchet should FIRE!
    triggered, new_sl = engine.evaluate_ratchet(Decimal("100.55"), fee_friction_pct=Decimal("0.10"))
    assert triggered
    assert new_sl == Decimal("100.10")  # Entry + 0.10% fees
    assert engine.active_scalp.stop_loss == Decimal("100.10")
    assert engine.active_scalp.ratchet_active

    # 3. Subsequent calls should not re-trigger
    triggered2, new_sl2 = engine.evaluate_ratchet(Decimal("101.00"), fee_friction_pct=Decimal("0.10"))
    assert not triggered2


def test_stoikov_micro_price_veto_filter():
    """Verify that Stoikov micro-price skew vetoes false breakouts."""
    engine = ApexScalperEngine()
    current_p = Decimal("100.00")
    
    # 15 klines with a bullish volume surge at the end
    mock_klines = []
    for i in range(15):
        mock_klines.append({
            "open": Decimal("99.50"),
            "high": Decimal("100.50"),
            "low": Decimal("99.00"),
            "close": Decimal("100.00"),
            "volume": Decimal("100.0") if i < 14 else Decimal("300.0"),  # 3x volume surge
            "quote_volume": Decimal("30000.0")
        })

    # Test 1: Long candidate with positive OBI (+0.40) but NEGATIVE micro-skew (-0.45 bps)
    # Opposing skew indicates massive overhead ask wall -> MUST BE VETOED
    vetoed_long = engine.evaluate_microstructure_candidate(
        symbol="SOLUSDT",
        current_price=current_p,
        best_bid=Decimal("99.98"),
        best_ask=Decimal("100.02"),
        order_book_imbalance=Decimal("0.40"),
        recent_klines=mock_klines,
        bnb_discount=True,
        micro_skew_bps=Decimal("-0.45"),
        micro_price=Decimal("99.995")
    )
    assert vetoed_long is None

    # Test 2: Long candidate with positive OBI (+0.40) and POSITIVE micro-skew (+0.35 bps)
    # Skew confirms true buying pressure -> APPROVED with score bonus
    approved_long = engine.evaluate_microstructure_candidate(
        symbol="SOLUSDT",
        current_price=current_p,
        best_bid=Decimal("99.98"),
        best_ask=Decimal("100.02"),
        order_book_imbalance=Decimal("0.40"),
        recent_klines=mock_klines,
        bnb_discount=True,
        micro_skew_bps=Decimal("0.35"),
        micro_price=Decimal("100.0035")
    )
    assert approved_long is not None
    assert approved_long.side == "BUY"
    assert approved_long.micro_skew_bps == Decimal("0.35")

    # Test 3: Short candidate with negative OBI (-0.40) but POSITIVE micro-skew (+0.50 bps)
    # Hidden bid wall cushion below -> MUST BE VETOED
    vetoed_short = engine.evaluate_microstructure_candidate(
        symbol="SOLUSDT",
        current_price=current_p,
        best_bid=Decimal("99.98"),
        best_ask=Decimal("100.02"),
        order_book_imbalance=Decimal("-0.40"),
        recent_klines=mock_klines,
        bnb_discount=True,
        micro_skew_bps=Decimal("0.50"),
        micro_price=Decimal("100.005")
    )
    assert vetoed_short is None


def test_volatility_scaled_dynamic_duration():
    """Verify that open_scalp sets expiry based on asset volatility (ATR%)."""
    engine = ApexScalperEngine(max_duration_seconds=2700)
    now_utc = datetime.datetime.now(datetime.timezone.utc)

    # 1. High Volatility (ATR% = 1.00% >= 0.80%) -> 600 seconds (10 min)
    cand_high_vol = ScalpCandidate(
        symbol="1000PEPEUSDT",
        side="BUY",
        score=Decimal("0.85"),
        expected_net_drift_pct=Decimal("0.02"),
        atr_5m=Decimal("0.00010"),
        atr_ratio=Decimal("1.5"),
        order_book_imbalance=Decimal("0.40"),
        spread_bps=Decimal("1.0"),
        entry_price=Decimal("0.0100"),  # ATR% = 0.00010 / 0.0100 * 100 = 1.00%
        take_profit=Decimal("0.0105"),
        stop_loss=Decimal("0.0098"),
        reward_risk_ratio=Decimal("2.5")
    )
    pos_high = engine.open_scalp(cand_high_vol, account_equity=Decimal("200.00"), position_id="HIGH-VOL", current_time_utc=now_utc)
    assert pos_high.max_duration_seconds == 600

    # Reset slot
    engine.active_scalp = None

    # 2. Medium Volatility (ATR% = 0.50% >= 0.40%) -> 1200 seconds (20 min)
    cand_med_vol = ScalpCandidate(
        symbol="SOLUSDT",
        side="BUY",
        score=Decimal("0.75"),
        expected_net_drift_pct=Decimal("0.01"),
        atr_5m=Decimal("1.00"),
        atr_ratio=Decimal("1.2"),
        order_book_imbalance=Decimal("0.40"),
        spread_bps=Decimal("1.0"),
        entry_price=Decimal("200.00"),  # ATR% = 1.00 / 200.00 * 100 = 0.50%
        take_profit=Decimal("203.00"),
        stop_loss=Decimal("199.00"),
        reward_risk_ratio=Decimal("3.0")
    )
    pos_med = engine.open_scalp(cand_med_vol, account_equity=Decimal("200.00"), position_id="MED-VOL", current_time_utc=now_utc)
    assert pos_med.max_duration_seconds == 1200

    # Reset slot
    engine.active_scalp = None

    # 3. Low Volatility (ATR% = 0.20% < 0.40%) -> 2700 seconds (45 min)
    cand_low_vol = ScalpCandidate(
        symbol="BTCUSDT",
        side="BUY",
        score=Decimal("0.70"),
        expected_net_drift_pct=Decimal("0.008"),
        atr_5m=Decimal("160.00"),
        atr_ratio=Decimal("1.1"),
        order_book_imbalance=Decimal("0.40"),
        spread_bps=Decimal("0.5"),
        entry_price=Decimal("80000.00"),  # ATR% = 160 / 80000 * 100 = 0.20%
        take_profit=Decimal("80500.00"),
        stop_loss=Decimal("79700.00"),
        reward_risk_ratio=Decimal("2.0")
    )
    pos_low = engine.open_scalp(cand_low_vol, account_equity=Decimal("200.00"), position_id="LOW-VOL", current_time_utc=now_utc)
    assert pos_low.max_duration_seconds == 2700

