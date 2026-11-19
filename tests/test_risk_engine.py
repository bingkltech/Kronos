"""
tests/test_risk_engine.py — Comprehensive Adversarial & Real-Money Integrity Test Suite (v3)
for the Decoupled Institutional Risk Management Engine (`risk_engine/`).

Simulates:
- Flash crashes, volatility spikes, scale-invariant liquidity evaporation, spread blowouts, correlation convergence
- Fat-finger order quantities (scale-aware for $200 micro accounts & institutional accounts), book depth caps,
  off-market limit prices, mandatory SL, noise-floor SL (L#16/L#39), max SL ROI (L#25), stale quotes & equity
- Split Intraday (-3%/-6%) & Rolling (-6%/-12%) Drawdown Velocity Clocks + persistent HALT latch across restarts
- Cross-process SQLite RiskLedger atomic slot reservations (TOCTOU race prevention)
- Aggregate portfolio open stop-risk cap (2.5% normal / 1.25% Tier-1) & correlated small-account net-beta cap (1.0x)
- Safe native `reduceOnly` exit gate in non-desync HALT vs hard block in desync HALT (`SIDE_MISMATCH`)
- Infinite signal-loop bursts, duplicate orders, API message-rate limits, COD timeouts
- External `risk_state.txt` operator overrides (REDUCE_ONLY, HALT, FLATTEN, CORRUPTED)
- Post-trade API state desynchronization (phantom positions, ghost records, qty/side mismatch, orphan orders)
- Fail-closed live mode (`dry_run=False` rejects orders without `RiskEngine`)
"""

from __future__ import annotations

import ast
import asyncio
import csv
from decimal import Decimal
import json
from pathlib import Path
from typing import Any, Dict, List, Optional
import pytest

from risk_engine import (
    DEFAULT_CONFIG_PATH,
    DecisionStatus,
    MarketSnapshot,
    OrderBookSnapshot,
    OrderSide,
    OrderType,
    PortfolioState,
    PositionSnapshot,
    ProposedOrder,
    RiskConfig,
    RiskEngine,
    RiskGatedGateway,
    RiskLedger,
    RiskMode,
    StateReconciler,
    compute_empirical_cvar,
    compute_fractional_kelly,
)
from src.quant.binance_execution import BinanceAtomicExecutor, PositionState
from src.quant.kev_risk_arbiter import TradeTicket


# ==============================================================================
# Fixtures & Helpers
# ==============================================================================

def make_config(**overrides: Any) -> RiskConfig:
    defaults: Dict[str, Any] = {
        "control_file_path": None,
        "ledger_db_path": None,
        "audit_log_dir": None,
        "max_single_order_notional_usd": Decimal("25000.00"),
    }
    defaults.update(overrides)
    return RiskConfig(**defaults)


def make_portfolio(
    equity: str = "100000",
    peak: str = "100000",
    intraday_start: str = "100000",
    free_margin: Optional[str] = None,
    positions: Optional[Dict[str, PositionSnapshot]] = None,
    returns: Optional[List[str]] = None,
    ts_ms: Optional[int] = None,
) -> PortfolioState:
    return PortfolioState(
        equity_usd=Decimal(equity),
        peak_equity_usd=Decimal(peak),
        intraday_start_equity_usd=Decimal(intraday_start),
        free_margin_usd=Decimal(free_margin) if free_margin is not None else Decimal(equity),
        positions=positions or {},
        realized_returns_series=[Decimal(r) for r in (returns or [])],
        timestamp_ms=ts_ms,
    )


def make_market(
    symbol: str = "BTCUSDT",
    mark: str = "50000",
    bid: str = "49995",
    ask: str = "50005",
    bid_depth: str = "500000",
    ask_depth: str = "500000",
    tob_depth: Optional[str] = "200000",
    realized_vol: str = "0.015",
    baseline_vol: str = "0.015",
    atr_pct: Optional[str] = "0.015",
    returns: Optional[List[str]] = None,
    pairwise_corrs: Optional[Dict[str, str]] = None,
    avg_corr: Optional[str] = "0.35",
    ts_ms: int = 1_700_000_000_000,
    step_size: str = "0.001",
    min_qty: str = "0.001",
    min_notional: str = "5.00",
) -> MarketSnapshot:
    return MarketSnapshot(
        symbol=symbol,
        mark_price=Decimal(mark),
        order_book=OrderBookSnapshot(
            best_bid=Decimal(bid),
            best_ask=Decimal(ask),
            bid_depth_usd=Decimal(bid_depth),
            ask_depth_usd=Decimal(ask_depth),
            top_of_book_depth_usd=Decimal(tob_depth) if tob_depth is not None else None,
        ),
        realized_vol=Decimal(realized_vol),
        baseline_vol=Decimal(baseline_vol),
        atr_pct=Decimal(atr_pct) if atr_pct is not None else None,
        asset_returns_series=[Decimal(r) for r in (returns or [])],
        pairwise_correlations={k: Decimal(v) for k, v in (pairwise_corrs or {}).items()},
        portfolio_avg_correlation=Decimal(avg_corr) if avg_corr is not None else None,
        timestamp_ms=ts_ms,
        step_size=Decimal(step_size),
        min_qty=Decimal(min_qty),
        min_notional_usd=Decimal(min_notional),
    )


def make_order(
    symbol: str = "BTCUSDT",
    side: OrderSide = OrderSide.BUY,
    order_type: OrderType = OrderType.MARKET,
    qty: str = "0.05",
    price: str = "50000",
    sl: Optional[str] = "49500",             # 1.0% valid SL (5.0% ROI at 5x <= 6.0% clamp)
    tp: Optional[str] = "51000",             # 2.0% valid TP (net R:R ~ 1.73:1)
    conviction: str = "0.80",
    win_rate: Optional[str] = "0.58",
    payoff: Optional[str] = "1.80",
    reduce_only: bool = False,
    exchange_enforces_reduce_only: bool = False,
    is_gross_edge_estimate: bool = False,
    leverage: str = "5",
    ts_ms: int = 1_700_000_000_100,
) -> ProposedOrder:
    return ProposedOrder(
        symbol=symbol,
        side=side,
        order_type=order_type,
        quantity=Decimal(qty),
        price=Decimal(price),
        stop_loss=Decimal(sl) if sl is not None else None,
        take_profit=Decimal(tp) if tp is not None else None,
        conviction=Decimal(conviction),
        win_rate=Decimal(win_rate) if win_rate is not None else None,
        payoff_ratio=Decimal(payoff) if payoff is not None else None,
        reduce_only=reduce_only,
        exchange_enforces_reduce_only=exchange_enforces_reduce_only,
        is_gross_edge_estimate=is_gross_edge_estimate,
        leverage=Decimal(leverage),
        timestamp_ms=ts_ms,
    )


# ==============================================================================
# 1. Architectural Isolation & Configuration Schema Tests
# ==============================================================================

def test_zero_alpha_dependency_isolation():
    """Risk engine package must have ZERO imports from src.quant or alpha modules."""
    pkg_dir = Path(__file__).resolve().parent.parent / "risk_engine"
    py_files = list(pkg_dir.glob("*.py"))
    assert len(py_files) >= 8

    forbidden_prefixes = ("src.quant", "model.", "scripts.")
    for py_file in py_files:
        tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert not alias.name.startswith(forbidden_prefixes), (
                        f"Forbidden alpha import {alias.name} in {py_file.name}"
                    )
            elif isinstance(node, ast.ImportFrom) and node.module:
                assert not node.module.startswith(forbidden_prefixes), (
                    f"Forbidden alpha import {node.module} in {py_file.name}"
                )


def test_yaml_config_loads_and_validates():
    cfg = RiskConfig.from_file(DEFAULT_CONFIG_PATH)
    assert cfg.kelly_fraction == Decimal("0.25")
    assert cfg.tier1_drawdown_pct == Decimal("0.03")
    assert cfg.tier2_drawdown_pct == Decimal("0.06")
    assert cfg.tier1_rolling_drawdown_pct == Decimal("0.06")
    assert cfg.tier2_rolling_drawdown_pct == Decimal("0.12")
    assert cfg.max_concurrent_positions == 3
    assert cfg.tier1_max_concurrent_positions == 1

    with pytest.raises(ValueError):
        RiskConfig(tier1_drawdown_pct=Decimal("0.07"), tier2_drawdown_pct=Decimal("0.05"))
    with pytest.raises(ValueError):
        RiskConfig(kelly_fraction=Decimal("1.5"))


# ==============================================================================
# 2. Baseline Approval, Metrics & Stage-2 Shadow Warnings
# ==============================================================================

def test_healthy_order_approved_with_full_metrics_and_shadow_warnings():
    engine = RiskEngine(config=make_config())
    # Spread = 10 bps (> 5 bps shadow warn, < 25 bps hard disaster cap)
    decision = engine.evaluate_order(
        make_order(qty="0.05"),
        make_portfolio(),
        make_market(bid="49975", ask="50025"),
    )
    assert decision.status == DecisionStatus.APPROVED
    assert decision.approved_qty == Decimal("0.05")
    assert isinstance(decision.approved_qty, Decimal)
    assert "ALL_RISK_GATES_PASSED" in decision.reason_codes
    assert "SHADOW_WARN_SPREAD_ABOVE_CALIBRATION_TARGET" in decision.metrics_snapshot["shadow_warnings"]
    for key in ("drawdown_pct", "realized_vol", "kelly_fraction", "spread_bps", "empirical_cvar_pct", "open_stop_risk_usd"):
        assert key in decision.metrics_snapshot


# ==============================================================================
# 3. Quantitative Sizing: Single-Pass Kelly, Vol Target, CVaR, Aggregate Stop-Risk
# ==============================================================================

def test_single_pass_kelly_no_false_starvation_on_real_edge():
    cfg = make_config()
    # Real Kronos empirical net edge: WR=51.1%, b=1.009 -> positive f* when is_gross=False!
    raw_net, frac_net = compute_fractional_kelly(Decimal("0.511"), Decimal("1.009"), cfg, is_gross_estimate=False)
    assert raw_net > Decimal("0")
    assert frac_net > Decimal("0")

    # Truly negative expectancy (WR=40%, b=1.20) is still vetoed
    engine = RiskEngine(config=cfg)
    decision = engine.evaluate_order(
        make_order(qty="0.05", win_rate="0.40", payoff="1.20", is_gross_edge_estimate=False),
        make_portfolio(),
        make_market(),
    )
    assert decision.status == DecisionStatus.VETOED
    assert "KELLY_NEGATIVE_EXPECTANCY_AFTER_DECAY" in decision.reason_codes


def test_kelly_vol_target_and_aggregate_portfolio_stop_risk_cap():
    engine = RiskEngine(config=make_config(require_stop_loss_on_entries=False))
    # Calm vs elevated vol scales down size
    d_calm = engine.evaluate_order(
        make_order(qty="0.40", sl=None, tp=None, ts_ms=1_700_000_001_000),
        make_portfolio(),
        make_market(realized_vol="0.015", baseline_vol="0.015", atr_pct="0.015", ts_ms=1_700_000_000_900),
        now_ms=1_700_000_001_000,
    )
    d_elevated = engine.evaluate_order(
        make_order(qty="0.40", sl=None, tp=None, ts_ms=1_700_000_003_000),
        make_portfolio(),
        make_market(realized_vol="0.030", baseline_vol="0.015", atr_pct="0.030", ts_ms=1_700_000_002_900),
        now_ms=1_700_000_003_000,
    )
    assert d_calm.status == DecisionStatus.RESIZED
    assert d_elevated.status == DecisionStatus.RESIZED
    assert d_elevated.approved_qty < d_calm.approved_qty

    # Aggregate portfolio open stop-risk cap (2.5% of $100k = $2,500):
    # Existing ETH position already risks $2,500 at stop -> new BTC trade MUST be vetoed!
    risky_eth = PositionSnapshot(
        symbol="ETHUSDT",
        side=OrderSide.BUY,
        quantity=Decimal("100"),
        entry_price=Decimal("3000"),
        mark_price=Decimal("3000"),
        stop_loss=Decimal("2975"),  # $25 * 100 = $2,500 stop risk (full 2.5% budget consumed!)
    )
    engine2 = RiskEngine(config=make_config())
    d_stop_cap = engine2.evaluate_order(
        make_order(qty="0.05", sl="49500", tp="51000"),
        make_portfolio(positions={"ETHUSDT": risky_eth}),
        make_market(),
    )
    assert d_stop_cap.status == DecisionStatus.VETOED
    assert "PORTFOLIO_OPEN_STOP_RISK_EXCEEDED" in d_stop_cap.reason_codes


def test_empirical_non_gaussian_cvar_tail_risk_cap():
    fat_tail_returns = [Decimal("0.005")] * 18 + [Decimal("-0.18"), Decimal("-0.22")]
    cvar = compute_empirical_cvar(
        returns_series=fat_tail_returns,
        confidence_level=Decimal("0.95"),
        fallback_vol=Decimal("0.015"),
        fat_tail_multiplier=Decimal("1.50"),
        min_samples=20,
    )
    assert cvar == Decimal("0.22")

    engine = RiskEngine(config=make_config())
    decision = engine.evaluate_order(
        make_order(qty="0.05"),
        make_portfolio(returns=["0.002"] * 18 + ["-0.08", "-0.10"]),
        make_market(),
    )
    assert decision.status == DecisionStatus.VETOED
    assert "PORTFOLIO_CVAR_LIMIT_BREACHED" in decision.reason_codes


# ==============================================================================
# 4. Small-Account Integrity ($200 BTC Preservation, Scale Fat-Finger, Net Beta)
# ==============================================================================

def test_small_account_btc_preservation_fat_finger_and_net_beta():
    engine = RiskEngine(config=make_config())
    p200 = make_portfolio(equity="200", peak="200", intraday_start="200")
    m_btc = make_market(
        symbol="BTCUSDT", mark="75000", bid="74998", ask="75002",
        bid_depth="500000", ask_depth="500000", tob_depth="50000",
        step_size="0.001", min_qty="0.001", min_notional="5.00",
    )

    # 1. Valid 0.001 BTC ($75 notional, 1.0% SL -> $0.75 stop risk = 0.375% equity) PASSES!
    d_btc = engine.evaluate_order(
        make_order(qty="0.001", price="75000", sl="74250", tp="76500", ts_ms=1_700_000_001_000),
        p200,
        m_btc,
        now_ms=1_700_000_001_000,
    )
    assert d_btc.status == DecisionStatus.APPROVED
    assert d_btc.approved_qty == Decimal("0.001")

    # 2. Scale-aware fat-finger on $200 account: $500 order >> $100 floor -> hard VETO!
    d_ff = engine.evaluate_order(
        make_order(qty="0.010", price="75000", sl="74250", tp="76500", ts_ms=1_700_000_003_000),
        p200,
        m_btc,
        now_ms=1_700_000_003_000,
    )
    assert d_ff.status == DecisionStatus.VETOED
    assert "OMS_FAT_FINGER_NOTIONAL_VETO" in d_ff.reason_codes

    # 3. Correlated Net Directional Cap (1.0x = $200 max net on small account):
    # Already holding $200 long ETH -> additional long BTC exceeds 1.0x net directional -> VETO!
    eth_long = PositionSnapshot("ETHUSDT", OrderSide.BUY, Decimal("0.10"), Decimal("2000"), Decimal("2000"), stop_loss=Decimal("1985"))
    d_net = engine.evaluate_order(
        make_order(qty="0.001", price="75000", sl="74250", tp="76500", ts_ms=1_700_000_005_000),
        make_portfolio(equity="200", peak="200", intraday_start="200", positions={"ETHUSDT": eth_long}),
        m_btc,
        now_ms=1_700_000_005_000,
    )
    assert d_net.status == DecisionStatus.VETOED
    assert "MAX_NET_LEVERAGE_EXCEEDED" in d_net.reason_codes


# ==============================================================================
# 5. Split Drawdown Clocks (Intraday vs Rolling), Safe HALTED Exits & Ledger Persistence
# ==============================================================================

def test_split_drawdown_clocks_and_tier1_concurrency_throttle():
    cancelled: List[str] = []
    flattened: List[str] = []
    engine = RiskEngine(
        config=make_config(),
        on_cancel_all_orders=lambda r: cancelled.append(r),
        on_flatten_all_positions=lambda r: flattened.append(r),
    )

    # Rolling drawdown -7.5% (within historical 7.47% variance) with 0% intraday DD:
    # Triggers Tier-1 Soft Breach (NOT Tier-2 Halt because rolling Tier-2 is -12%!)
    p_roll_t1 = make_portfolio(equity="92500", peak="100000", intraday_start="92500")
    d_roll = engine.evaluate_order(
        make_order(qty="0.04", conviction="0.85", ts_ms=1_700_000_001_000),
        p_roll_t1,
        make_market(ts_ms=1_700_000_000_900),
        now_ms=1_700_000_001_000,
    )
    assert d_roll.status == DecisionStatus.RESIZED
    assert d_roll.risk_mode == RiskMode.THROTTLED_TIER1
    assert d_roll.approved_qty == Decimal("0.020")
    assert engine.is_halted is False

    # In Tier-1, concurrency is throttled from 3 -> 1: with 1 position open, 2nd entry is blocked!
    existing_eth = PositionSnapshot("ETHUSDT", OrderSide.BUY, Decimal("1"), Decimal("3000"), Decimal("3000"), stop_loss=Decimal("2970"))
    d_conc = engine.evaluate_order(
        make_order(qty="0.02", conviction="0.90", ts_ms=1_700_000_003_000),
        make_portfolio(equity="92500", peak="100000", intraday_start="92500", positions={"ETHUSDT": existing_eth}),
        make_market(ts_ms=1_700_000_002_900),
        now_ms=1_700_000_003_000,
    )
    assert d_conc.status == DecisionStatus.VETOED
    assert "TIER1_CONCURRENCY_CAP_REACHED" in d_conc.reason_codes

    # Intraday -6.5% -> Tier-2 Hard Breach -> KILL_SWITCH + HALTED latch!
    p_intra_t2 = make_portfolio(equity="93500", peak="100000", intraday_start="100000", positions={"ETHUSDT": existing_eth})
    d_kill = engine.evaluate_order(
        make_order(qty="0.02", conviction="0.95", ts_ms=1_700_000_005_000),
        p_intra_t2,
        make_market(ts_ms=1_700_000_004_900),
        now_ms=1_700_000_005_000,
    )
    assert d_kill.status == DecisionStatus.KILL_SWITCH
    assert d_kill.risk_mode == RiskMode.HALTED
    assert "TIER2_INTRADAY_DRAWDOWN_HARD_BREACH" in d_kill.reason_codes
    assert len(cancelled) == 1 and len(flattened) == 1

    # Safe HALTED Exit Gate: reduce_only exit WITH native exchange reduceOnly="true" IS allowed in non-desync halt!
    d_safe_exit = engine.evaluate_order(
        make_order(
            symbol="ETHUSDT", side=OrderSide.SELL, qty="1.0", price="3000", sl=None, tp=None,
            reduce_only=True, exchange_enforces_reduce_only=True, ts_ms=1_700_000_007_000,
        ),
        p_intra_t2,
        make_market(symbol="ETHUSDT", mark="3000", bid="2999", ask="3001", ts_ms=1_700_000_006_900),
        now_ms=1_700_000_007_000,
    )
    assert d_safe_exit.status == DecisionStatus.APPROVED
    assert "SAFE_REDUCE_ONLY_EXIT_IN_NON_DESYNC_HALT" in d_safe_exit.reason_codes

    # Manual reset clears halt only with non-empty operator ID
    assert engine.manual_reset("", "attempt") is False
    assert engine.manual_reset("risk_officer_1", "Post-mortem completed") is True
    assert engine.is_halted is False


def test_desync_halt_blocks_even_reduce_only_and_persists_across_restarts(tmp_path: Path):
    db_path = str(tmp_path / "risk_ledger.db")
    ctrl_path = str(tmp_path / "risk_state.txt")
    cfg = make_config(ledger_db_path=db_path, control_file_path=ctrl_path)

    engine1 = RiskEngine(config=cfg)
    engine1.trigger_kill_switch("SIDE_MISMATCH:BTCUSDT", flatten_positions=False)
    assert engine1.is_halted is True
    assert engine1.is_desync_halt is True

    # Simulate fresh process restart -> HALTED latch MUST survive via RiskLedger & control file!
    engine2 = RiskEngine(config=cfg)
    assert engine2.is_halted is True
    assert engine2.is_desync_halt is True

    pos = PositionSnapshot("BTCUSDT", OrderSide.BUY, Decimal("0.10"), Decimal("50000"), Decimal("50000"))
    d_blocked_exit = engine2.evaluate_order(
        make_order(
            side=OrderSide.SELL, qty="0.10", sl=None, tp=None,
            reduce_only=True, exchange_enforces_reduce_only=True,
        ),
        make_portfolio(positions={"BTCUSDT": pos}),
        make_market(),
    )
    assert d_blocked_exit.status == DecisionStatus.KILL_SWITCH
    assert "HALTED_REDUCE_ONLY_BLOCKED_DESYNC_OR_UNPROTECTED" in d_blocked_exit.reason_codes


def test_cross_process_ledger_prevents_toctou_slot_and_symbol_races(tmp_path: Path):
    db_path = str(tmp_path / "shared_ledger.db")
    cfg = make_config(ledger_db_path=db_path, max_concurrent_positions=2, max_positions_per_symbol=1)
    worker_macro = RiskEngine(config=cfg)
    worker_tiger = RiskEngine(config=cfg)

    ts = 1_700_000_001_000
    # Worker 1 reserves BTCUSDT slot
    d1 = worker_macro.evaluate_order(
        make_order(symbol="BTCUSDT", qty="0.02", ts_ms=ts),
        make_portfolio(),
        make_market(symbol="BTCUSDT", ts_ms=ts - 100),
        now_ms=ts,
    )
    assert d1.status == DecisionStatus.APPROVED
    assert "reservation_id" in d1.metrics_snapshot

    # Worker 2 simultaneously tries to enter BTCUSDT before exchange REST position shows up -> BLOCKED atomically!
    d2 = worker_tiger.evaluate_order(
        make_order(symbol="BTCUSDT", qty="0.02", ts_ms=ts + 10),
        make_portfolio(),
        make_market(symbol="BTCUSDT", ts_ms=ts - 100),
        now_ms=ts + 10,
    )
    assert d2.status == DecisionStatus.VETOED
    assert "LEDGER_SAME_SYMBOL_RESERVATION_CONFLICT" in d2.reason_codes


# ==============================================================================
# 6. Layer 1 & Layer 2 Adversarial Scenarios
# ==============================================================================

def test_flash_crash_spread_blowout_depth_and_correlation():
    engine = RiskEngine(config=make_config())

    # Vol spike (4x baseline)
    d_vol = engine.evaluate_order(
        make_order(ts_ms=1_700_000_001_000),
        make_portfolio(),
        make_market(realized_vol="0.060", baseline_vol="0.015", ts_ms=1_700_000_000_900),
        now_ms=1_700_000_001_000,
    )
    assert d_vol.status == DecisionStatus.VETOED
    assert "REGIME_VOLATILITY_SPIKE_RATIO" in d_vol.reason_codes

    # Spread blowout (60 bps > 25 bps ceiling; use wide TP so Layer-2 net-RR clears and Layer-1 spread guard fires)
    d_spread = engine.evaluate_order(
        make_order(tp="53000", ts_ms=1_700_000_003_000),
        make_portfolio(),
        make_market(bid="49850", ask="50150", ts_ms=1_700_000_002_900),
        now_ms=1_700_000_003_000,
    )
    assert d_spread.status == DecisionStatus.VETOED
    assert "LIQUIDITY_SPREAD_WIDENING" in d_spread.reason_codes

    # Scale-invariant depth evaporation: order is $2,500 -> needs >= 10x ($25,000), book has $5,000 -> VETO!
    d_liq = engine.evaluate_order(
        make_order(qty="0.05", ts_ms=1_700_000_005_000),
        make_portfolio(),
        make_market(tob_depth="5000", ts_ms=1_700_000_004_900),
        now_ms=1_700_000_005_000,
    )
    assert d_liq.status == DecisionStatus.VETOED
    assert "LIQUIDITY_DEPTH_EVAPORATION" in d_liq.reason_codes

    # Correlation convergence (avg rho = 0.93)
    d_corr = engine.evaluate_order(
        make_order(ts_ms=1_700_000_007_000),
        make_portfolio(),
        make_market(avg_corr="0.93", ts_ms=1_700_000_006_900),
        now_ms=1_700_000_007_000,
    )
    assert d_corr.status == DecisionStatus.VETOED
    assert "CORRELATION_SYSTEMIC_CONVERGENCE" in d_corr.reason_codes


def test_oms_mandatory_sl_noise_floor_sl_roi_collar_and_loops():
    engine = RiskEngine(config=make_config(duplicate_order_window_ms=500, max_orders_per_burst_window=3))
    base_ts = 1_700_000_000_000
    market = make_market(ts_ms=base_ts)
    portfolio = make_portfolio(ts_ms=base_ts)

    # Missing mandatory stop-loss
    d_nosl = engine.evaluate_order(make_order(sl=None, ts_ms=base_ts + 10), portfolio, market, now_ms=base_ts + 10)
    assert d_nosl.status == DecisionStatus.VETOED
    assert "OMS_MISSING_STOP_LOSS" in d_nosl.reason_codes

    # Vanishing-stop below 0.66% noise floor (L#16/L#39)
    engine.oms_layer.reset_history()
    d_tight = engine.evaluate_order(make_order(price="50000", sl="49900", ts_ms=base_ts + 20), portfolio, market, now_ms=base_ts + 20)
    assert d_tight.status == DecisionStatus.VETOED
    assert "OMS_STOP_BELOW_NOISE_FLOOR_L16_L39" in d_tight.reason_codes

    # SL ROI exceeds 6.0% clamp at 5x (2.0% price stop * 5x = 10% ROI > 6% L#25)
    engine.oms_layer.reset_history()
    d_roi = engine.evaluate_order(make_order(price="50000", sl="49000", tp="52500", leverage="5", ts_ms=base_ts + 30), portfolio, market, now_ms=base_ts + 30)
    assert d_roi.status == DecisionStatus.VETOED
    assert "OMS_SL_ROI_EXCEEDS_CLAMP_L25" in d_roi.reason_codes

    # Off-market LIMIT order collar breach
    engine.oms_layer.reset_history()
    d_collar = engine.evaluate_order(
        make_order(order_type=OrderType.LIMIT, price="52500", sl="51975", tp="53600", ts_ms=base_ts + 40),
        portfolio,
        market,
        now_ms=base_ts + 40,
    )
    assert d_collar.status == DecisionStatus.VETOED
    assert any(c.startswith("OMS_PRICE_COLLAR_BREACH") for c in d_collar.reason_codes)

    # Duplicate loop & burst limiter
    engine.oms_layer.reset_history()
    assert engine.evaluate_order(make_order(qty="0.02", ts_ms=base_ts + 100), portfolio, market, now_ms=base_ts + 100).is_executable
    d_dup = engine.evaluate_order(make_order(qty="0.02", ts_ms=base_ts + 150), portfolio, market, now_ms=base_ts + 150)
    assert d_dup.status == DecisionStatus.VETOED
    assert "OMS_DUPLICATE_ORDER_LOOP_BLOCKED" in d_dup.reason_codes

    # Stale portfolio snapshot (>5s)
    engine.oms_layer.reset_history()
    d_stale_port = engine.evaluate_order(
        make_order(qty="0.02", ts_ms=base_ts + 10_000),
        make_portfolio(ts_ms=base_ts),
        make_market(ts_ms=base_ts + 9_900),
        now_ms=base_ts + 10_000,
    )
    assert d_stale_port.status == DecisionStatus.VETOED
    assert "OMS_STALE_PORTFOLIO_STATE" in d_stale_port.reason_codes

    # Malformed None input fails closed
    d_bad = engine.evaluate_order(None, portfolio, market)  # type: ignore[arg-type]
    assert d_bad.status == DecisionStatus.VETOED
    assert "RISK_ENGINE_FAIL_CLOSED_ERROR" in d_bad.reason_codes


# ==============================================================================
# 7. Layer 3 & Layer 4: Rate Limits, COD, Control File & Post-Trade Reconciliation
# ==============================================================================

def test_gateway_rate_limit_cod_and_control_file(tmp_path: Path):
    ctrl = tmp_path / "risk_state.txt"
    engine = RiskEngine(
        config=make_config(
            control_file_path=str(ctrl),
            max_api_messages_per_second=2,
            max_orders_per_burst_window=10,
            cancel_on_disconnect_timeout_ms=5000,
        )
    )
    base_ts = 1_700_000_000_000
    market = make_market(ts_ms=base_ts)
    portfolio = make_portfolio()

    engine.record_gateway_heartbeat(base_ts)
    assert engine.evaluate_order(make_order(qty="0.01", ts_ms=base_ts + 10), portfolio, market, now_ms=base_ts + 10).is_executable
    assert engine.evaluate_order(make_order(qty="0.02", ts_ms=base_ts + 20), portfolio, market, now_ms=base_ts + 20).is_executable
    d_rate = engine.evaluate_order(make_order(qty="0.03", ts_ms=base_ts + 30), portfolio, market, now_ms=base_ts + 30)
    assert d_rate.status == DecisionStatus.VETOED
    assert "GATEWAY_RATE_LIMIT_PER_SECOND" in d_rate.reason_codes

    # COD timeout -> KILL_SWITCH
    d_cod = engine.evaluate_order(
        make_order(qty="0.01", ts_ms=base_ts + 6000),
        portfolio,
        make_market(ts_ms=base_ts + 6000),
        now_ms=base_ts + 6000,
    )
    assert d_cod.status == DecisionStatus.KILL_SWITCH
    assert "GATEWAY_CANCEL_ON_DISCONNECT_TIMEOUT" in d_cod.reason_codes

    # Control file corrupted -> fail-closed
    ctrl.write_text("CORRUPTED_GARBAGE\n", encoding="utf-8")
    engine2 = RiskEngine(config=make_config(control_file_path=str(ctrl)))
    d_corrupt = engine2.evaluate_order(make_order(qty="0.01"), portfolio, market)
    assert d_corrupt.status == DecisionStatus.KILL_SWITCH
    assert "EXTERNAL_CONTROL_FILE_CORRUPTED" in d_corrupt.reason_codes


class MockExchangeAdapter:
    def __init__(self, positions: Dict[str, PositionSnapshot], open_orders: List[Dict[str, Any]]):
        self.positions = dict(positions)
        self.open_orders = list(open_orders)
        self.flattened_calls: List[Any] = []
        self.cancelled_calls: List[Any] = []

    def fetch_exchange_positions(self) -> Dict[str, PositionSnapshot]:
        return dict(self.positions)

    def fetch_exchange_open_orders(self) -> List[Dict[str, Any]]:
        return list(self.open_orders)

    def cancel_order(self, symbol: str, order_id: str) -> bool:
        self.cancelled_calls.append((symbol, order_id))
        return True

    def flatten_position(self, symbol: str, side: OrderSide, quantity: Decimal) -> bool:
        self.flattened_calls.append((symbol, side, quantity))
        return True


def test_post_trade_reconciliation_and_async_loop():
    engine = RiskEngine(config=make_config(auto_flatten_phantom_positions=True))
    synced: List[Any] = []
    internal = {
        "ETHUSDT": PositionSnapshot("ETHUSDT", OrderSide.BUY, Decimal("2.0"), Decimal("3000"), Decimal("3000")),
        "SOLUSDT": PositionSnapshot("SOLUSDT", OrderSide.BUY, Decimal("10.0"), Decimal("150"), Decimal("150")),
        "BNBUSDT": PositionSnapshot("BNBUSDT", OrderSide.BUY, Decimal("5.0"), Decimal("600"), Decimal("600")),
    }
    exchange = {
        "BTCUSDT": PositionSnapshot("BTCUSDT", OrderSide.BUY, Decimal("0.25"), Decimal("50000"), Decimal("50000")),
        "SOLUSDT": PositionSnapshot("SOLUSDT", OrderSide.BUY, Decimal("6.0"), Decimal("150"), Decimal("150")),
        "BNBUSDT": PositionSnapshot("BNBUSDT", OrderSide.SELL, Decimal("5.0"), Decimal("600"), Decimal("600")),
    }
    adapter = MockExchangeAdapter(exchange, [{"symbol": "BTCUSDT", "orderId": "ORPHAN_1"}])
    reconciler = StateReconciler(
        adapter=adapter,
        config=engine.config,
        on_kill_switch=lambda r: engine.trigger_kill_switch(r, flatten_positions=True),
        on_sync_internal_position=lambda s, p: synced.append((s, p)),
    )
    report = reconciler.reconcile_once(internal, internal_open_order_ids=[])
    assert report.is_synchronized is False
    assert {d.discrepancy_type for d in report.discrepancies} == {
        "PHANTOM_EXCHANGE_POSITION",
        "GHOST_INTERNAL_POSITION",
        "QTY_MISMATCH",
        "SIDE_MISMATCH",
        "ORPHAN_OPEN_ORDER",
    }
    assert engine.is_halted is True and engine.is_desync_halt is True

    # Async loop
    sync_adapter = MockExchangeAdapter({}, [])
    async_rec = StateReconciler(sync_adapter, make_config(reconcile_interval_seconds=Decimal("0.01")))
    asyncio.run(async_rec.run_loop(lambda: ({}, []), max_iterations=2))
    assert async_rec.last_report is not None and async_rec.last_report.is_synchronized is True


# ==============================================================================
# 8. Telemetry & Fail-Closed Live Execution Integration
# ==============================================================================

def test_telemetry_and_fail_closed_live_binance_executor(tmp_path: Path):
    log_dir = tmp_path / "risk_audit"
    engine = RiskEngine(config=make_config(audit_log_dir=str(log_dir)))
    engine.evaluate_order(make_order(qty="0.05", ts_ms=1_700_000_001_000), make_portfolio(), make_market(ts_ms=1_700_000_000_900), now_ms=1_700_000_001_000)
    assert (log_dir / "risk_decisions.jsonl").exists()
    assert (log_dir / "risk_decisions.csv").exists()

    ticket = TradeTicket(
        symbol="BTCUSDT",
        side="BUY",
        entry_price=Decimal("50000"),
        stop_loss=Decimal("49500"),
        take_profit=Decimal("51000"),
        quantity=Decimal("0.050"),
        notional_usd=Decimal("2500.00"),
        effective_leverage=5,
        risk_budget_usd=Decimal("25.00"),
        reward_risk_ratio=Decimal("2.00"),
        net_expected_gain_pct=Decimal("1.80"),
        forecast_confidence=Decimal("0.85"),
    )

    # Real-Money Integrity Standard (v3): dry_run=False with risk_engine=None MUST FAIL CLOSED!
    live_unprotected = BinanceAtomicExecutor(dry_run=False, risk_engine=None)
    pos_blocked = live_unprotected.submit_live_bracket_order(ticket)
    assert pos_blocked.state == PositionState.REJECTED
    assert "LIVE_MODE_REQUIRES_RISK_ENGINE" in (pos_blocked.close_reason or "")

    # With risk_engine attached, omitting snapshots also fails closed; valid snapshots pass
    paper_gated = BinanceAtomicExecutor(dry_run=True, risk_engine=RiskEngine(config=make_config()))
    pos_missing = paper_gated.submit_bracket_order(ticket)
    assert pos_missing.state == PositionState.REJECTED
    assert "MISSING_PORTFOLIO_OR_MARKET_SNAPSHOT" in (pos_missing.close_reason or "")

    now_ms = int(__import__("time").time() * 1000)
    pos_ok = paper_gated.submit_bracket_order(
        ticket,
        portfolio_state=make_portfolio(ts_ms=now_ms),
        market_snapshot=make_market(ts_ms=now_ms),
    )
    assert pos_ok.state == PositionState.BRACKETS_ACTIVE
    assert pos_ok.quantity == Decimal("0.050")
