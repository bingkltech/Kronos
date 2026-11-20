"""
risk_engine/config.py — Institutional Risk Engine Configuration Schema & Loader (v3 Real-Money Integrity).

Supports JSON and YAML configuration files with strict Decimal parsing and
fail-fast structural validation so misconfigured bounds can never boot silently.
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from decimal import Decimal
import json
import os
from typing import Any, Dict, Optional

from risk_engine.models import to_decimal

try:
    import yaml  # type: ignore
except ImportError:
    yaml = None


DEFAULT_CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "risk_config.yaml")


@dataclass(frozen=True)
class RiskConfig:
    """Complete risk governance parameter schema (Real-Money Integrity Standard v3)."""

    # --- 1. Quantitative Sizing: Single-Pass Net-of-Fee Fractional Kelly & Vol Targeting ---
    kelly_fraction: Decimal = Decimal("0.25")                 # Quarter-Kelly default (0.25 * f*)
    default_win_rate: Decimal = Decimal("0.55")               # Prior win rate when order omits one
    default_payoff_ratio: Decimal = Decimal("1.50")           # Prior avg_win / avg_loss
    win_rate_decay_buffer: Decimal = Decimal("0.005")         # Calibrated 50 bps buffer (not 300 bps starvation)
    payoff_decay_buffer: Decimal = Decimal("0.05")            # 5% haircut ONLY when edge estimate is gross
    kelly_apply_decay_only_to_gross: bool = True              # Never double-penalize already net-of-fee stats
    max_kelly_allocation_pct: Decimal = Decimal("0.25")       # Hard cap on Kelly equity fraction
    target_volatility: Decimal = Decimal("0.015")             # Target per-period realized vol (1.5%)
    volatility_floor: Decimal = Decimal("0.005")              # Floor to prevent vol-scalar blowup
    max_vol_scalar: Decimal = Decimal("1.50")
    min_vol_scalar: Decimal = Decimal("0.15")

    # --- 2. Tail-Risk (Empirical CVaR), Portfolio Stop-Risk & Exposure Caps ---
    cvar_confidence_level: Decimal = Decimal("0.95")          # 95% Expected Shortfall (tail 5%)
    max_portfolio_cvar_pct: Decimal = Decimal("0.04")         # Max 4% equity Expected Shortfall
    cvar_fat_tail_multiplier: Decimal = Decimal("1.50")       # Heavy-tail fallback multiplier
    cvar_min_samples: int = 20
    max_single_asset_exposure_pct: Decimal = Decimal("0.25")  # Max 25% of equity per single asset (institutional)
    max_gross_leverage: Decimal = Decimal("3.00")
    max_net_leverage: Decimal = Decimal("2.00")
    small_account_threshold_usd: Decimal = Decimal("2500.00") # Micro-account governance threshold
    small_account_max_net_leverage: Decimal = Decimal("1.00") # Prevents observed 1.43x one-way directional pile-up
    preserve_indivisible_min_lot: bool = True                 # Allow 0.001 BTC when stop-risk & CVaR clear safely
    max_portfolio_open_stop_risk_pct: Decimal = Decimal("0.025")   # Max 2.5% aggregate stop-risk across ALL open trades
    tier1_max_portfolio_open_stop_risk_pct: Decimal = Decimal("0.0125")  # Cut to 1.25% in Tier 1
    max_single_trade_stop_risk_pct: Decimal = Decimal("0.015")     # Max 1.5% dollar risk at stop on any single trade

    # --- 3. Portfolio Concurrency & Same-Symbol Isolation (L#15 Alpha-Agnostic) ---
    max_concurrent_positions: int = 3                         # Unified cap across all strategies/workers
    tier1_max_concurrent_positions: int = 1                   # True 67% portfolio cut in Tier 1 (even with BTC min lot)
    max_positions_per_symbol: int = 1                         # Enforces L#15 without knowing strategy names

    # --- 4. Split Pod-Shop Drawdown Velocity Clocks (Intraday vs. Rolling) ---
    tier1_drawdown_pct: Decimal = Decimal("0.03")             # Intraday -3.0% Soft Breach (alias: tier1_intraday_drawdown_pct)
    tier2_drawdown_pct: Decimal = Decimal("0.06")             # Intraday -6.0% Hard Breach -> KILL_SWITCH + HALTED
    tier1_rolling_drawdown_pct: Decimal = Decimal("0.06")     # Rolling multi-day -6.0% Soft Breach
    tier2_rolling_drawdown_pct: Decimal = Decimal("0.12")     # Rolling multi-day -12.0% Hard Breach -> KILL_SWITCH
    tier1_size_multiplier: Decimal = Decimal("0.50")          # Cut divisible size by 50%
    tier1_min_conviction: Decimal = Decimal("0.75")
    tier1_spread_tightening_factor: Decimal = Decimal("0.60")
    base_min_conviction: Decimal = Decimal("0.50")

    # --- 5. Layer 1: Signal & Regime Defense (Scale-Invariant + Two-Stage Shadow Calibration) ---
    max_vol_spike_ratio: Decimal = Decimal("2.50")
    max_absolute_vol: Decimal = Decimal("0.10")
    max_spread_bps: Decimal = Decimal("25.0")                 # Stage-1 disaster ceiling (25 bps; Tier-1 = 15 bps)
    shadow_warn_spread_bps: Decimal = Decimal("5.0")          # Stage-2 72h shadow warning threshold (5 bps)
    min_top_of_book_depth_usd: Decimal = Decimal("500.00")    # Dust floor; scaled by min_book_depth_multiple * notional
    min_book_depth_multiple: Decimal = Decimal("10.0")        # Book must hold >= 10x order notional
    max_pairwise_correlation: Decimal = Decimal("0.85")
    max_portfolio_avg_correlation: Decimal = Decimal("0.80")

    # --- 6. Layer 2: Pre-Trade OMS Defense (Mandatory SL, Stop Geometry, Scale-Aware Fat-Finger) ---
    max_single_order_notional_usd: Decimal = Decimal("25000.00")   # Institutional hard cap
    small_account_fat_finger_floor_usd: Decimal = Decimal("100.00") # Scale-aware small-account floor (covers 0.001 BTC)
    fat_finger_equity_multiple: Decimal = Decimal("0.50")     # Small-account fat-finger = max($100, 0.50 * equity)
    fat_finger_hard_veto: bool = True
    max_order_book_depth_pct: Decimal = Decimal("0.10")
    max_price_collar_pct: Decimal = Decimal("0.015")
    require_stop_loss_on_entries: bool = True                 # Zero naked entries (mandatory SL on non-reduce-only)
    min_stop_distance_pct: Decimal = Decimal("0.0066")        # L#16 & L#39 noise floor (blocks vanishing-stop blowups)
    max_sl_roi_pct: Decimal = Decimal("0.06")                 # L#25 hard clamp: max 6.0% leveraged SL ROI
    min_rr_ratio: Decimal = Decimal("1.20")                   # Minimum net-of-fee R:R guard when TP+SL present
    min_cost_multiple: Decimal = Decimal("1.50")              # Hard net-positive TP-to-friction floor (L#10/L#37)
    shadow_warn_cost_multiple: Decimal = Decimal("4.00")      # Stage-2 72h shadow warning for <4x cost multiple
    duplicate_order_window_ms: int = 500
    burst_window_ms: int = 1000
    max_orders_per_burst_window: int = 5
    max_market_snapshot_age_ms: int = 5000
    max_portfolio_state_age_ms: int = 5000                    # Reject stale equity snapshots (>5s)

    # --- 7. Layer 3: Gateway, Kill-Switch & Cross-Process Ledger ---
    max_api_messages_per_second: int = 10
    max_api_messages_per_minute: int = 300
    cancel_on_disconnect_timeout_ms: int = 120000
    control_file_path: Optional[str] = None                   # e.g. "data/risk_state.txt"
    ledger_db_path: Optional[str] = None                      # e.g. "data/risk_ledger.db" (atomic multi-worker lock)
    slot_reservation_ttl_ms: int = 15000
    allow_reduce_only_in_non_desync_halt: bool = True         # Safe exit gate ONLY when halt is non-desync + native reduceOnly

    # --- 8. Layer 4: Post-Trade Reconciliation ---
    reconcile_interval_seconds: Decimal = Decimal("10.0")
    qty_mismatch_tolerance_pct: Decimal = Decimal("0.001")
    auto_flatten_phantom_positions: bool = True

    # --- 9. Telemetry & Auditability ---
    audit_log_dir: Optional[str] = None
    log_all_decisions: bool = True

    def __post_init__(self) -> None:
        for f in fields(self):
            val = getattr(self, f.name)
            if f.type == "Decimal" or f.type is Decimal:
                object.__setattr__(self, f.name, to_decimal(val, f.name))

        # Validate critical institutional invariants
        if not (Decimal("0") < self.kelly_fraction <= Decimal("1")):
            raise ValueError("kelly_fraction must be in (0, 1]")
        if not (Decimal("0") < self.tier1_drawdown_pct < self.tier2_drawdown_pct < Decimal("1")):
            raise ValueError("Must satisfy 0 < tier1_drawdown_pct < tier2_drawdown_pct < 1")
        if not (Decimal("0") < self.tier1_rolling_drawdown_pct < self.tier2_rolling_drawdown_pct < Decimal("1")):
            raise ValueError("Must satisfy 0 < tier1_rolling_drawdown_pct < tier2_rolling_drawdown_pct < 1")
        if not (Decimal("0") < self.tier1_size_multiplier < Decimal("1")):
            raise ValueError("tier1_size_multiplier must be in (0, 1)")
        if not (Decimal("0.50") < self.cvar_confidence_level < Decimal("1")):
            raise ValueError("cvar_confidence_level must be in (0.50, 1)")
        if self.max_single_order_notional_usd <= Decimal("0"):
            raise ValueError("max_single_order_notional_usd must be positive")
        if self.max_price_collar_pct <= Decimal("0"):
            raise ValueError("max_price_collar_pct must be positive")
        if self.max_gross_leverage < self.max_net_leverage:
            raise ValueError("max_gross_leverage must be >= max_net_leverage")
        if self.max_api_messages_per_second <= 0 or self.max_api_messages_per_minute <= 0:
            raise ValueError("API rate limits must be positive integers")
        if self.max_concurrent_positions < 1 or self.tier1_max_concurrent_positions < 1:
            raise ValueError("Concurrency caps must be >= 1")
        if self.tier1_max_concurrent_positions > self.max_concurrent_positions:
            raise ValueError("tier1_max_concurrent_positions must be <= max_concurrent_positions")
        if self.max_portfolio_open_stop_risk_pct <= Decimal("0"):
            raise ValueError("max_portfolio_open_stop_risk_pct must be positive")

    def effective_fat_finger_notional_usd(self, equity_usd: Decimal) -> Decimal:
        """
        Scale-aware fat-finger cap:
        - Small accounts (<= small_account_threshold_usd): max($100, 0.50 * equity), capped at hard ceiling.
        - Larger accounts: hard max_single_order_notional_usd ceiling.
        """
        if equity_usd <= self.small_account_threshold_usd:
            scaled = max(self.small_account_fat_finger_floor_usd, equity_usd * self.fat_finger_equity_multiple)
            return min(self.max_single_order_notional_usd, scaled)
        return self.max_single_order_notional_usd

    def effective_max_net_leverage(self, equity_usd: Decimal) -> Decimal:
        if equity_usd <= self.small_account_threshold_usd:
            return min(self.max_net_leverage, self.small_account_max_net_leverage)
        return self.max_net_leverage

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RiskConfig":
        valid_fields = {f.name: f for f in fields(cls)}
        kwargs: Dict[str, Any] = {}
        for key, val in data.items():
            if key not in valid_fields:
                continue
            f = valid_fields[key]
            if val is None:
                kwargs[key] = None
            elif f.type in ("Decimal", Decimal):
                kwargs[key] = to_decimal(val, key)
            elif f.type in ("int", int):
                kwargs[key] = int(val)
            elif f.type in ("bool", bool):
                kwargs[key] = bool(val)
            else:
                kwargs[key] = val
        return cls(**kwargs)

    @classmethod
    def from_file(cls, path: str = DEFAULT_CONFIG_PATH) -> "RiskConfig":
        if not os.path.exists(path):
            raise FileNotFoundError(f"RiskConfig file not found: {path}")
        with open(path, "r", encoding="utf-8") as fh:
            raw_text = fh.read()

        ext = os.path.splitext(path)[1].lower()
        if ext in (".yaml", ".yml"):
            if yaml is None:
                raise RuntimeError("PyYAML is required to load YAML risk configs.")
            parsed = yaml.safe_load(raw_text) or {}
        else:
            parsed = json.loads(raw_text)

        if not isinstance(parsed, dict):
            raise ValueError(f"RiskConfig root must be a mapping in {path}")
        return cls.from_dict(parsed)

    def to_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        for f in fields(self):
            val = getattr(self, f.name)
            out[f.name] = str(val) if isinstance(val, Decimal) else val
        return out
