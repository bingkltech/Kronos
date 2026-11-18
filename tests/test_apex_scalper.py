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
    engine = ApexScalperEngine(cooldown_seconds=0)
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
            engine.update_in_trade_path(Decimal("155.00"))
            engine.close_scalp(
                exit_price=Decimal("149.20"),
                close_reason="STOP_LOSS_HIT",
                current_time_utc=t0 + datetime.timedelta(minutes=10),
                exchange_fees_usd=Decimal("0.10"),
                trade_mode="LIVE"
            )
        else:
            engine.update_in_trade_path(Decimal("155.00"))
            engine.close_scalp(
                exit_price=Decimal("155.00"),
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
    """Verify that evaluate_ratchet enforces Two-Tier Volatility Trailing Ratchet."""
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
        take_profit=Decimal("103.00"),
        stop_loss=Decimal("98.50"),
        reward_risk_ratio=Decimal("2.0")
    )
    pos = engine.open_scalp(cand, account_equity=Decimal("200.00"), position_id="TEST-1", current_time_utc=now_utc)
    assert pos is not None
    assert pos.stop_loss == Decimal("98.50")
    assert not pos.ratchet_active

    # 1. Price moves up +0.50% (net +0.40%, below +0.80% hurdle): ratchet should NOT fire (avoids noise choke!)
    triggered, new_sl = engine.evaluate_ratchet(Decimal("100.50"), fee_friction_pct=Decimal("0.10"))
    assert not triggered
    assert new_sl is None
    assert engine.active_scalp.stop_loss == Decimal("98.50")

    # 2. Price moves up +0.95% (net +0.85%, above +0.80% hurdle): Tier 1 fires and locks in profit + buffer
    triggered, new_sl = engine.evaluate_ratchet(Decimal("100.95"), fee_friction_pct=Decimal("0.10"), profit_lock_pct=Decimal("0.25"))
    assert triggered
    assert new_sl == Decimal("100.35")  # Entry + (0.10% fee + 0.25% profit lock)
    assert engine.active_scalp.stop_loss == Decimal("100.35")
    assert engine.active_scalp.ratchet_active

    # 3. Tier 2A: Harvest Floor Lock at >= +1.00% net (price at 101.15 -> locks in +0.65% net = 100.75)
    triggered_2a, new_sl_2a = engine.evaluate_ratchet(Decimal("101.15"), fee_friction_pct=Decimal("0.10"))
    assert triggered_2a
    assert new_sl_2a == Decimal("100.75")
    assert engine.active_scalp.stop_loss == Decimal("100.75")

    # 4. Tier 2B: Harvest Floor Lock at >= +1.30% net (price at 101.45 -> locks in +0.95% net = 101.05)
    triggered_2b, new_sl_2b = engine.evaluate_ratchet(Decimal("101.45"), fee_friction_pct=Decimal("0.10"))
    assert triggered_2b
    assert new_sl_2b == Decimal("101.05")
    assert engine.active_scalp.stop_loss == Decimal("101.05")

    # 5. Tier 3 Dynamic Runner Trailing: Price moves to +2.00% ($102.00) with ATR=1.50
    # Tightened trail buffer = min(0.50 * 1.50, 100.00 * 0.0050) = $0.50 -> runner_sl = 102.00 - 0.50 = $101.50!
    triggered3, new_sl3 = engine.evaluate_ratchet(Decimal("102.00"), fee_friction_pct=Decimal("0.10"), atr_5m=Decimal("1.50"))
    assert triggered3
    assert new_sl3 == Decimal("101.50")
    assert engine.active_scalp.stop_loss == Decimal("101.50")


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
    engine = ApexScalperEngine(max_duration_seconds=3600)
    now_utc = datetime.datetime.now(datetime.timezone.utc)

    # 1. High Volatility (ATR% = 1.00% >= 0.80%) -> 1800 seconds (30 min)
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
    assert pos_high.max_duration_seconds == 1800

    # Reset slot
    engine.active_scalp = None

    # 2. Medium Volatility (ATR% = 0.50% >= 0.40%) -> 2700 seconds (45 min)
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
    assert pos_med.max_duration_seconds == 2700

    # Reset slot
    engine.active_scalp = None

    # 3. Low Volatility (ATR% = 0.20% < 0.40%) -> 3600 seconds (60 min)
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
    assert pos_low.max_duration_seconds == 3600


def test_live_scalp_ticket_drift_parameter_contract():
    """Verify that ScalpCandidate cleanly instantiates TradeTicket without AttributeError."""
    from src.quant.kev_risk_arbiter import TradeTicket
    cand = ScalpCandidate(
        symbol="SOLUSDT",
        side="BUY",
        score=Decimal("0.85"),
        expected_net_drift_pct=Decimal("0.018"),
        atr_5m=Decimal("1.50"),
        atr_ratio=Decimal("1.3"),
        order_book_imbalance=Decimal("0.45"),
        spread_bps=Decimal("1.0"),
        entry_price=Decimal("150.00"),
        take_profit=Decimal("153.50"),
        stop_loss=Decimal("148.20"),
        reward_risk_ratio=Decimal("1.94")
    )
    # This instantiation previously crashed with AttributeError: 'ScalpCandidate' object has no attribute 'predicted_drift_pct'
    ticket = TradeTicket(
        symbol=cand.symbol,
        side="BUY",
        entry_price=cand.entry_price,
        stop_loss=cand.stop_loss,
        take_profit=cand.take_profit,
        quantity=Decimal("0.35"),
        notional_usd=Decimal("52.50"),
        effective_leverage=3,
        risk_budget_usd=Decimal("15.00"),
        reward_risk_ratio=cand.reward_risk_ratio,
        net_expected_gain_pct=cand.expected_net_drift_pct,
        is_scalp=True
    )
    assert ticket.net_expected_gain_pct == Decimal("0.018")
    assert ticket.is_scalp is True


def test_asymmetric_macro_confluence_gate():
    """Verify Option B: Asymmetric Conviction Gate (Adaptive Macro Confluence)."""
    engine = ApexScalperEngine()
    current_p = Decimal("100.00")
    now_utc = datetime.datetime.now(datetime.timezone.utc)

    # 1. Standard bullish klines (vol surge 1.8x, lower wick)
    mock_klines_standard = []
    for i in range(15):
        mock_klines_standard.append({
            "open": Decimal("99.80"),
            "high": Decimal("100.50"),
            "low": Decimal("99.20"),
            "close": Decimal("100.00"),
            "volume": Decimal("100.0") if i < 13 else Decimal("180.0"),  # 1.8x surge
            "quote_volume": Decimal("18000.0")
        })

    # Under Bear Distribution (breadth 15.0% < 25.0%):
    # A standard Long scalp with score < 0.55 or vol surge < 2.2x MUST BE VETOED
    vetoed_counter_long = engine.evaluate_microstructure_candidate(
        symbol="SOLUSDT",
        current_price=current_p,
        best_bid=Decimal("99.98"),
        best_ask=Decimal("100.02"),
        order_book_imbalance=Decimal("0.38"),
        recent_klines=mock_klines_standard,
        bnb_discount=True,
        micro_skew_bps=Decimal("0.10"),
        micro_price=Decimal("100.001"),
        macro_breadth_pct=Decimal("15.0")  # Systemic Bear Distribution
    )
    assert vetoed_counter_long is None

    # Trend-aligned SHORT under Bear Distribution with same standard volume surge MUST BE APPROVED
    mock_klines_short = []
    for i in range(15):
        mock_klines_short.append({
            "open": Decimal("100.20"),
            "high": Decimal("100.80"),
            "low": Decimal("99.50"),
            "close": Decimal("100.00"),
            "volume": Decimal("100.0") if i < 13 else Decimal("180.0"),
            "quote_volume": Decimal("18000.0")
        })
    approved_trend_short = engine.evaluate_microstructure_candidate(
        symbol="SOLUSDT",
        current_price=current_p,
        best_bid=Decimal("99.98"),
        best_ask=Decimal("100.02"),
        order_book_imbalance=Decimal("-0.38"),
        recent_klines=mock_klines_short,
        bnb_discount=True,
        micro_skew_bps=Decimal("-0.10"),
        micro_price=Decimal("99.999"),
        macro_breadth_pct=Decimal("15.0")
    )
    assert approved_trend_short is not None
    assert approved_trend_short.side == "SELL"
    assert not approved_trend_short.is_counter_trend

    # 2. Extreme Conviction V-Bottom Setup (3.0x vol surge, massive OBI 0.45, positive skew)
    mock_klines_extreme = []
    for i in range(15):
        mock_klines_extreme.append({
            "open": Decimal("99.80"),
            "high": Decimal("100.60"),
            "low": Decimal("98.80"),
            "close": Decimal("100.00"),
            "volume": Decimal("100.0") if i < 13 else Decimal("320.0"),  # 3.2x surge
            "quote_volume": Decimal("32000.0")
        })
    approved_v_bottom_long = engine.evaluate_microstructure_candidate(
        symbol="SOLUSDT",
        current_price=current_p,
        best_bid=Decimal("99.98"),
        best_ask=Decimal("100.02"),
        order_book_imbalance=Decimal("0.45"),
        recent_klines=mock_klines_extreme,
        bnb_discount=True,
        micro_skew_bps=Decimal("0.25"),
        micro_price=Decimal("100.0025"),
        macro_breadth_pct=Decimal("15.0")
    )
    assert approved_v_bottom_long is not None
    assert approved_v_bottom_long.side == "BUY"
    assert approved_v_bottom_long.is_counter_trend is True

    # 3. Verify Asymmetric Sizing: Counter-trend V-bottom gets half-margin ($7.50 max), trend short gets full ($15.00)
    pos_trend = engine.open_scalp(approved_trend_short, account_equity=Decimal("2000.00"), position_id="TREND-1", current_time_utc=now_utc)
    assert pos_trend is not None
    engine.active_scalp = None  # Free slot

    pos_counter = engine.open_scalp(approved_v_bottom_long, account_equity=Decimal("2000.00"), position_id="COUNTER-1", current_time_utc=now_utc)
    assert pos_counter is not None
    assert pos_counter.is_counter_trend is True
    # Counter-trend margin must be approximately half of trend-confluent margin
    assert pos_counter.initial_margin_usd < pos_trend.initial_margin_usd


def test_post_exit_symbol_cooldown_prevents_immediate_reentry():
    """
    Verify Post-Exit Quarantine / Cooldown Mechanism:
    1. Closing an asset on take-profit/manual triggers 900s quarantine.
    2. Subsequent evaluation of the same asset is strictly VETOED during cooldown.
    3. Other assets remain eligible (forced opportunity rotation).
    4. Advancing time past cooldown window restores eligibility.
    """
    engine = ApexScalperEngine(cooldown_seconds=900)
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    current_p = Decimal("60000.00")

    mock_klines = []
    for i in range(15):
        mock_klines.append({
            "open": Decimal("59950.00"),
            "high": Decimal("60200.00"),
            "low": Decimal("59800.00"),
            "close": Decimal("60000.00"),
            "volume": Decimal("100.0") if i < 13 else Decimal("250.0"),
            "quote_volume": Decimal("25000.0")
        })

    # Step 1: Pre-cooldown candidate passes evaluation
    cand_btc = engine.evaluate_microstructure_candidate(
        symbol="BTCUSDT",
        current_price=current_p,
        best_bid=Decimal("59990.00"),
        best_ask=Decimal("60010.00"),
        order_book_imbalance=Decimal("0.45"),
        recent_klines=mock_klines,
        bnb_discount=True,
        micro_skew_bps=Decimal("0.10"),
        current_time_utc=now_utc
    )
    assert cand_btc is not None
    assert cand_btc.symbol == "BTCUSDT"

    # Step 2: Open and close scalp on BTC (e.g. TAKE_PROFIT_HIT or MANUAL_OVERRIDE)
    engine.open_scalp(cand_btc, account_equity=Decimal("1000.00"), position_id="SCALP-BTC-1", current_time_utc=now_utc)
    assert engine.active_scalp is not None

    # Close scalp at +1.25% profit
    exit_p = Decimal("60750.00")
    engine.close_scalp(
        exit_price=exit_p,
        close_reason="TAKE_PROFIT_HIT",
        current_time_utc=now_utc,
        exchange_fees_usd=Decimal("0.10")
    )
    assert engine.active_scalp is None
    assert engine.is_slot_available is True

    # Step 3: Verify BTC is in active cooldown
    assert engine.is_symbol_in_cooldown("BTCUSDT", now_utc) is True
    cooldown_info = engine.get_cooldown_status(now_utc)
    assert "BTCUSDT" in cooldown_info
    assert cooldown_info["BTCUSDT"]["remaining_seconds"] == 900
    assert "SCALP_CLOSE_TAKE_PROFIT_HIT" in cooldown_info["BTCUSDT"]["reason"]

    # Step 4: Immediate re-evaluation of BTC (even 10 seconds later) MUST BE VETOED
    immediate_reentry = engine.evaluate_microstructure_candidate(
        symbol="BTCUSDT",
        current_price=exit_p,
        best_bid=Decimal("60740.00"),
        best_ask=Decimal("60760.00"),
        order_book_imbalance=Decimal("0.50"), # Extreme bullish OBI
        recent_klines=mock_klines,
        bnb_discount=True,
        micro_skew_bps=Decimal("0.15"),
        current_time_utc=now_utc + datetime.timedelta(seconds=10)
    )
    assert immediate_reentry is None, "Immediate re-entry on BTC must be blocked by post-exit cooldown!"

    # Step 5: Opportunity Rotation: Another asset (e.g. ETHUSDT) is NOT in cooldown and MUST pass
    mock_eth_klines = []
    for i in range(15):
        mock_eth_klines.append({
            "open": Decimal("2990.00"),
            "high": Decimal("3020.00"),
            "low": Decimal("2980.00"),
            "close": Decimal("3000.00"),
            "volume": Decimal("50.0") if i < 13 else Decimal("120.0"),
            "quote_volume": Decimal("12000.0")
        })
    eth_cand = engine.evaluate_microstructure_candidate(
        symbol="ETHUSDT",
        current_price=Decimal("3000.00"),
        best_bid=Decimal("2999.00"),
        best_ask=Decimal("3001.00"),
        order_book_imbalance=Decimal("0.40"),
        recent_klines=mock_eth_klines,
        bnb_discount=True,
        micro_skew_bps=Decimal("0.10"),
        current_time_utc=now_utc + datetime.timedelta(seconds=10)
    )
    assert eth_cand is not None, "ETH must pass evaluation while BTC is cooling down!"
    assert eth_cand.symbol == "ETHUSDT"

    # Step 6: After 901 seconds (past the 15-minute cooldown), BTC becomes eligible again
    future_utc = now_utc + datetime.timedelta(seconds=901)
    assert engine.is_symbol_in_cooldown("BTCUSDT", future_utc) is False
    restored_cand = engine.evaluate_microstructure_candidate(
        symbol="BTCUSDT",
        current_price=exit_p,
        best_bid=Decimal("60740.00"),
        best_ask=Decimal("60760.00"),
        order_book_imbalance=Decimal("0.45"),
        recent_klines=mock_klines,
        bnb_discount=True,
        micro_skew_bps=Decimal("0.10"),
        current_time_utc=future_utc
    )
    assert restored_cand is not None, "BTC must be eligible again after cooldown expiration!"


