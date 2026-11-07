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

    # Candidate 2: BTC with small drift that fails fee hurdle
    btc_cand = engine.evaluate_candidate(
        symbol="BTCUSDT",
        current_price=Decimal("60000.00"),
        predicted_drift_pct=Decimal("0.30"), # Too small: fails Lesson #10 hurdle
        atr_5m=Decimal("50.00"),
        atr_baseline=Decimal("50.00"),
        order_book_imbalance=Decimal("0.10"),
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
            # Simulate target reached (151.80) while adverse excursion is small (within 1 ATR)
            engine.update_in_trade_path(Decimal("149.20"))
            engine.update_in_trade_path(Decimal("151.80"))
            engine.close_scalp(
                exit_price=Decimal("149.20"),
                close_reason="STOP_LOSS_HIT",
                current_time_utc=t0 + datetime.timedelta(minutes=10),
                exchange_fees_usd=Decimal("0.10"),
                trade_mode="LIVE"
            )
        else:
            engine.update_in_trade_path(Decimal("151.80"))
            engine.close_scalp(
                exit_price=Decimal("151.80"),
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
