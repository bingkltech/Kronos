"""
src/quant/tiger_config.py — Type-Strict Decimal Configuration for Strategy #3 (Stalking Tiger).

Strictly adheres to AGENTS.md Invariant 1 (Zero Float Financial Math).
All financial calculations, ratios, prices, and thresholds use decimal.Decimal.
Operates completely independently of Strategy #1 (Storm Protocol) and Strategy #2 (Apex Lightning Scalper).
"""

from dataclasses import dataclass, field, asdict
from decimal import Decimal
import json
import os
from typing import Any, Dict, Optional


@dataclass(frozen=True)
class TigerApiRateLimitConfig:
    """Binance USD(S)-M Futures API rate limits and throttling guardrails."""
    max_weight_per_minute: int = 2400          # Hard Binance IP rate limit
    warning_weight_threshold: int = 1200       # 50% cap -> throttles polling to 60s
    critical_weight_threshold: int = 1800      # 75% cap -> pauses all REST polling
    bulk_ticker_interval_seconds: int = 12     # Continuous Sieve: 5 bulk calls/min = 200 weight/min (8.3% budget)
    bulk_ticker_weight_cost: int = 40          # Weight cost of GET /fapi/v1/ticker/24hr
    max_ws_reconnect_attempts: int = 5         # Auto-reconnection attempts for WebSockets
    ws_ping_interval_seconds: int = 60         # Keepalive ping interval for persistent streams


@dataclass(frozen=True)
class TigerUniverseSieveConfig:
    """Universe filtering parameters to identify the Top 150 and narrow to Top 5 active prey."""
    min_24h_turnover_usd: Decimal = Decimal("50000000.00")  # Minimum $50M 24h turnover (quarantines illiquid meme traps)
    max_universe_size: int = 150                           # Top 150 scanned by 24h volatility score
    active_sniper_slots: int = 5                           # Top 5 active targets in WebSocket pool
    min_volatility_score: Decimal = Decimal("0.020")       # Minimum 2.0% 24h amplitude
    max_24h_change_abs_pct: Decimal = Decimal("0.35")      # Max +/-35% 24h change (Freight Train Outlier Shield)
    quote_asset: str = "USDT"                              # USD(S)-M quote asset


@dataclass(frozen=True)
class TigerTemporalConfig:
    """Speed, Signal TTL, and Temporal Expiration rules (8-12-15 Minute Decay Ladder)."""
    signal_ttl_seconds: int = 90                           # 90s max: cancel stale un-triggered orders
    max_analysis_window_minutes: int = 15                  # 15m maximum structural analysis horizon
    zero_mfe_abort_seconds: int = 30                       # 30s Zero-MFE Sanity Circuit Breaker (stops knife catch flushes)
    zero_mfe_max_loss_pct: Decimal = Decimal("-0.0025")    # -0.25% loss cutoff if MFE has failed to bounce
    zero_mfe_max_favorable_pct: Decimal = Decimal("0.0005") # +0.05% max favorable excursion threshold
    velocity_check_minutes: int = 8                       # Minute 8: verify momentum velocity
    velocity_min_gain_pct: Decimal = Decimal("0.0050")     # +0.50% price move triggers BE ratchet
    stall_scratch_minutes: int = 12                       # Minute 12: momentum stall scratch check
    stall_band_low_pct: Decimal = Decimal("-0.0020")       # -0.20% lower stall band
    stall_band_high_pct: Decimal = Decimal("0.0025")       # +0.25% upper stall band
    hard_temporal_expiry_minutes: int = 15                 # Minute 15: absolute hard market flatten
    fleet_inter_trade_cooldown_seconds: int = 60           # 60s min cooldown between any new trades across entire fleet (anti-burst)
    max_correlated_signals_per_scan: int = 1               # Max 1 signal allowed per scan cycle (rejects multi-coin basket tremor)
    plateau_ratchet_enabled: bool = True                   # 5m Micro-Plateau Breakeven Ratchet (Anti-Chop Capital Shield)
    plateau_ratchet_minutes: int = 5                       # Minute 5: Check plateau stagnation
    plateau_min_mfe_pct: Decimal = Decimal("0.0020")       # +0.20% MFE bounce triggers BE stop ratchet
    plateau_be_buffer_pct: Decimal = Decimal("-0.0010")     # -0.10% BE buffer to cover fee friction


@dataclass(frozen=True)
class TigerOrderflowConfig:
    """Microstructure Orderflow, CVD, Stoikov Micro-Price, and Anti-Steamroller filters."""
    ofi_threshold: Decimal = Decimal("0.45")               # Cont-Kukanov-Stoikov OFI trigger cutoff
    micro_price_skew_bps: Decimal = Decimal("0.20")        # 0.20 bps Stoikov Micro-Price skew filter
    cvd_divergence_sigma: Decimal = Decimal("1.4")         # 1.4 sigma CVD delta divergence (calibrated for high responsiveness)
    absorption_wick_min_ratio: Decimal = Decimal("0.45")   # 45% wick ratio for trapped liquidity candle (SELL setups)
    steamroller_vol_multiplier: Decimal = Decimal("4.5")   # Veto: volume > 4.5x average is a freight train
    max_spread_pct: Decimal = Decimal("0.0005")            # 0.05% max bid-ask spread tolerance
    min_trapped_trader_density: Decimal = Decimal("0.65")  # 65% minimum absorption density score
    max_candle_close_loc_pct: Decimal = Decimal("0.35")    # Outer 35% close requirement (Wyckoff Upthrust Confirmation)
    macro_trend_filter_enabled: bool = True                # 1h Trend alignment check
    btc_tide_gate_enabled: bool = True                     # Veto longs if BTC is flash-dumping
    btc_1m_dump_threshold_pct: Decimal = Decimal("-0.0035") # -0.35% BTC 1m drop triggers freeze
    btc_cvd_dump_sigma: Decimal = Decimal("-2.5")          # -2.5 sigma BTC CVD sell surge triggers freeze
    delta_oi_filter_enabled: bool = True                   # Trapped Trader Open Interest (ΔOI) Climax Gate
    min_delta_oi_pct: Decimal = Decimal("0.0001")          # Minimum +0.01% OI expansion during absorption window
    oi_lookback_seconds: int = 180                         # 180s window for measuring ΔOI trend
    falling_knife_guard_enabled: bool = True               # Anti-Falling-Knife Guard for BUY setups (Lesson #43 & #49)
    buy_absorption_wick_min_ratio: Decimal = Decimal("0.60") # 60% minimum lower wick for BUY setups (strictly higher than SELL 45%)
    buy_max_24h_drop_abs_pct: Decimal = Decimal("10.0")    # Veto BUY if coin 24h change <= -10.0%


@dataclass(frozen=True)
class TigerBracketConfig:
    """Dual-regime Take-Profit / Stop-Loss geometry, leverage, and circuit breakers."""
    # Dual-Regime Threshold
    slow_vol_atr_threshold_pct: Decimal = Decimal("0.0100") # ATR-14 < 1.00% triggers slow regime
    
    # Slow Volatility Regime (ATR < 1.00%)
    slow_vol_tp_price_pct: Decimal = Decimal("0.0101")      # +1.01% price move (+4.65% Net ROI at 5x)
    slow_vol_sl_price_pct: Decimal = Decimal("0.0066")      # -0.66% price move (-3.30% Net ROI at 5x)
    
    # High Volatility Regime (ATR >= 1.00%)
    fast_vol_tp_price_pct: Decimal = Decimal("0.0190")      # +1.90% price move (+9.10% Net ROI at 5x)
    fast_vol_sl_price_pct: Decimal = Decimal("0.0110")      # -1.10% price move (-5.50% Net ROI at 5x)
    calibrated_tp_price_pct: Decimal = Decimal("0.0110")    # +1.10% calibrated take-profit target
    ratchet_trigger_price_pct: Decimal = Decimal("0.0080")  # +0.80% move triggers breakeven cushion lock
    symbol_cooldown_minutes: int = 15                       # 15m post-exit symbol cooldown (stops churn)
    
    # Volatility Parity Dollar Risk Sizing
    volatility_parity_enabled: bool = True                 # Inverse-volatility risk parity sizing
    risk_budget_per_trade_usd: Decimal = Decimal("1.50")   # Strict $1.50 risk budget per trade
    min_notional_usd: Decimal = Decimal("20.00")           # Minimum $20 notional size
    max_notional_usd: Decimal = Decimal("300.00")          # Maximum $300 notional size
    
    # Risk Clamping & Leverage
    max_sl_roi_pct: Decimal = Decimal("5.5")                # Clamped to -5.0% to -5.5% max ROI
    leverage: int = 5                                       # 5x leverage
    max_concurrent_positions: int = 2                       # Max 2 concurrent Tiger positions
    risk_budget_per_trade_ratio: Decimal = Decimal("0.015") # 1.5% max equity risked per trade
    
    # Circuit Breakers
    consecutive_loss_pause_count: int = 5                   # 5 consecutive losses forces pause
    consecutive_loss_cooldown_minutes: int = 60             # 60 minutes cooling period after 5 losses
    daily_drawdown_limit_ratio: Decimal = Decimal("0.030")  # 3.0% 24h drawdown stop


@dataclass(frozen=True)
class TigerMasterConfig:
    """Root configuration container for Strategy #3 (Stalking Tiger)."""
    rate_limit: TigerApiRateLimitConfig = field(default_factory=TigerApiRateLimitConfig)
    sieve: TigerUniverseSieveConfig = field(default_factory=TigerUniverseSieveConfig)
    temporal: TigerTemporalConfig = field(default_factory=TigerTemporalConfig)
    orderflow: TigerOrderflowConfig = field(default_factory=TigerOrderflowConfig)
    brackets: TigerBracketConfig = field(default_factory=TigerBracketConfig)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize configuration to a JSON-compatible dictionary."""
        def _serialize_val(v: Any) -> Any:
            if isinstance(v, Decimal):
                return str(v)
            if hasattr(v, "__dataclass_fields__"):
                return {k: _serialize_val(getattr(v, k)) for k in v.__dataclass_fields__}
            return v
        return _serialize_val(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TigerMasterConfig":
        """Deserialize configuration from a dictionary, reconstructing Decimals."""
        def _parse_decimals(obj: Any) -> Any:
            if isinstance(obj, dict):
                return {k: _parse_decimals(v) for k, v in obj.items()}
            if isinstance(obj, list):
                return [_parse_decimals(v) for v in obj]
            if isinstance(obj, str):
                try:
                    # Parse as Decimal if it looks like a numeric string with decimal or digits
                    if obj.replace(".", "", 1).replace("-", "", 1).isdigit() and ("." in obj or len(obj) > 6):
                        return Decimal(obj)
                except Exception:
                    pass
            return obj

        p_rate = data.get("rate_limit", {})
        p_sieve = data.get("sieve", {})
        p_temp = data.get("temporal", {})
        p_of = data.get("orderflow", {})
        p_brk = data.get("brackets", {})

        return cls(
            rate_limit=TigerApiRateLimitConfig(
                max_weight_per_minute=int(p_rate.get("max_weight_per_minute", 2400)),
                warning_weight_threshold=int(p_rate.get("warning_weight_threshold", 1200)),
                critical_weight_threshold=int(p_rate.get("critical_weight_threshold", 1800)),
                bulk_ticker_interval_seconds=int(p_rate.get("bulk_ticker_interval_seconds", 12)),
                bulk_ticker_weight_cost=int(p_rate.get("bulk_ticker_weight_cost", 40)),
                max_ws_reconnect_attempts=int(p_rate.get("max_ws_reconnect_attempts", 5)),
                ws_ping_interval_seconds=int(p_rate.get("ws_ping_interval_seconds", 60)),
            ),
            sieve=TigerUniverseSieveConfig(
                min_24h_turnover_usd=Decimal(str(p_sieve.get("min_24h_turnover_usd", "30000000.00"))),
                max_universe_size=int(p_sieve.get("max_universe_size", 150)),
                active_sniper_slots=int(p_sieve.get("active_sniper_slots", 5)),
                min_volatility_score=Decimal(str(p_sieve.get("min_volatility_score", "0.020"))),
                max_24h_change_abs_pct=Decimal(str(p_sieve.get("max_24h_change_abs_pct", "0.35"))),
                quote_asset=str(p_sieve.get("quote_asset", "USDT")),
            ),
            temporal=TigerTemporalConfig(
                signal_ttl_seconds=int(p_temp.get("signal_ttl_seconds", 90)),
                max_analysis_window_minutes=int(p_temp.get("max_analysis_window_minutes", 15)),
                velocity_check_minutes=int(p_temp.get("velocity_check_minutes", 8)),
                velocity_min_gain_pct=Decimal(str(p_temp.get("velocity_min_gain_pct", "0.0050"))),
                stall_scratch_minutes=int(p_temp.get("stall_scratch_minutes", 12)),
                stall_band_low_pct=Decimal(str(p_temp.get("stall_band_low_pct", "-0.0020"))),
                stall_band_high_pct=Decimal(str(p_temp.get("stall_band_high_pct", "0.0025"))),
                hard_temporal_expiry_minutes=int(p_temp.get("hard_temporal_expiry_minutes", 15)),
                fleet_inter_trade_cooldown_seconds=int(p_temp.get("fleet_inter_trade_cooldown_seconds", 60)),
                max_correlated_signals_per_scan=int(p_temp.get("max_correlated_signals_per_scan", 1)),
            ),
            orderflow=TigerOrderflowConfig(
                ofi_threshold=Decimal(str(p_of.get("ofi_threshold", "0.45"))),
                micro_price_skew_bps=Decimal(str(p_of.get("micro_price_skew_bps", "0.20"))),
                cvd_divergence_sigma=Decimal(str(p_of.get("cvd_divergence_sigma", "1.4"))),
                absorption_wick_min_ratio=Decimal(str(p_of.get("absorption_wick_min_ratio", "0.30"))),
                steamroller_vol_multiplier=Decimal(str(p_of.get("steamroller_vol_multiplier", "4.5"))),
                max_spread_pct=Decimal(str(p_of.get("max_spread_pct", "0.0005"))),
                min_trapped_trader_density=Decimal(str(p_of.get("min_trapped_trader_density", "0.65"))),
                max_candle_close_loc_pct=Decimal(str(p_of.get("max_candle_close_loc_pct", "0.35"))),
                macro_trend_filter_enabled=bool(p_of.get("macro_trend_filter_enabled", True)),
                btc_tide_gate_enabled=bool(p_of.get("btc_tide_gate_enabled", True)),
                btc_1m_dump_threshold_pct=Decimal(str(p_of.get("btc_1m_dump_threshold_pct", "-0.0035"))),
                btc_cvd_dump_sigma=Decimal(str(p_of.get("btc_cvd_dump_sigma", "-2.5"))),
                delta_oi_filter_enabled=bool(p_of.get("delta_oi_filter_enabled", True)),
                min_delta_oi_pct=Decimal(str(p_of.get("min_delta_oi_pct", "0.0001"))),
                oi_lookback_seconds=int(p_of.get("oi_lookback_seconds", 180)),
                buy_absorption_wick_min_ratio=Decimal(str(p_of.get("buy_absorption_wick_min_ratio", "0.35"))),
            ),
            brackets=TigerBracketConfig(
                slow_vol_atr_threshold_pct=Decimal(str(p_brk.get("slow_vol_atr_threshold_pct", "0.0100"))),
                slow_vol_tp_price_pct=Decimal(str(p_brk.get("slow_vol_tp_price_pct", "0.0101"))),
                slow_vol_sl_price_pct=Decimal(str(p_brk.get("slow_vol_sl_price_pct", "0.0066"))),
                fast_vol_tp_price_pct=Decimal(str(p_brk.get("fast_vol_tp_price_pct", "0.0190"))),
                fast_vol_sl_price_pct=Decimal(str(p_brk.get("fast_vol_sl_price_pct", "0.0110"))),
                calibrated_tp_price_pct=Decimal(str(p_brk.get("calibrated_tp_price_pct", "0.0110"))),
                ratchet_trigger_price_pct=Decimal(str(p_brk.get("ratchet_trigger_price_pct", "0.0080"))),
                symbol_cooldown_minutes=int(p_brk.get("symbol_cooldown_minutes", 15)),
                volatility_parity_enabled=bool(p_brk.get("volatility_parity_enabled", True)),
                risk_budget_per_trade_usd=Decimal(str(p_brk.get("risk_budget_per_trade_usd", "1.50"))),
                min_notional_usd=Decimal(str(p_brk.get("min_notional_usd", "20.00"))),
                max_notional_usd=Decimal(str(p_brk.get("max_notional_usd", "300.00"))),
                max_sl_roi_pct=Decimal(str(p_brk.get("max_sl_roi_pct", "5.5"))),
                leverage=int(p_brk.get("leverage", 5)),
                max_concurrent_positions=int(p_brk.get("max_concurrent_positions", 2)),
                risk_budget_per_trade_ratio=Decimal(str(p_brk.get("risk_budget_per_trade_ratio", "0.015"))),
                consecutive_loss_pause_count=int(p_brk.get("consecutive_loss_pause_count", 5)),
                consecutive_loss_cooldown_minutes=int(p_brk.get("consecutive_loss_cooldown_minutes", 60)),
                daily_drawdown_limit_ratio=Decimal(str(p_brk.get("daily_drawdown_limit_ratio", "0.030"))),
            ),
        )

    def save(self, filepath: str = "data/tiger_config.json") -> None:
        """Persist configuration to disk."""
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2)

    @classmethod
    def load(cls, filepath: str = "data/tiger_config.json") -> "TigerMasterConfig":
        """Load configuration from disk, falling back to defaults if missing."""
        if not os.path.exists(filepath):
            default_cfg = cls()
            default_cfg.save(filepath)
            return default_cfg
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
        return cls.from_dict(data)


DEFAULT_TIGER_CONFIG = TigerMasterConfig()
