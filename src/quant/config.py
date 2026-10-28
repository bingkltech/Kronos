"""
src/quant/config.py — Type-Strict Decimal Configuration & Domain Entities for Binance Futures.

Enforces AGENTS.md Invariant 1 (Zero Float Financial Math).
All accounting, lot sizing, price quantization, fee schedules, and risk limits
are strictly represented as decimal.Decimal.
"""

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP, ROUND_DOWN
from typing import Dict, List, Optional


# ==============================================================================
# Symbol Level Configuration Dataclass
# ==============================================================================

@dataclass(frozen=True)
class FuturesSymbolConfig:
    """Trading and precision parameters for a Binance USD(S)-M Futures contract."""
    symbol: str
    price_precision: int       # Number of decimals for price quotation
    quantity_precision: int    # Number of decimals for contract sizing (stepSize)
    min_quantity: Decimal      # Minimum order size allowed
    min_notional: Decimal      # Minimum notional order value in USDT (usually 5.0)
    taker_fee_rate: Decimal = Decimal("0.0005")   # Standard VIP0 taker fee (0.05%)
    maker_fee_rate: Decimal = Decimal("0.0002")   # Standard VIP0 maker fee (0.02%)
    est_slippage_rate: Decimal = Decimal("0.0003") # 0.03% estimated execution slippage

    def quantize_price(self, price: Decimal) -> Decimal:
        """Quantize price to exchange tick precision (ROUND_HALF_UP)."""
        fmt = Decimal("10") ** -self.price_precision
        return price.quantize(fmt, rounding=ROUND_HALF_UP)

    def quantize_quantity(self, quantity: Decimal) -> Decimal:
        """Quantize quantity to contract stepSize (ROUND_DOWN to prevent margin rejection)."""
        fmt = Decimal("10") ** -self.quantity_precision
        return quantity.quantize(fmt, rounding=ROUND_DOWN)

    def round_trip_taker_friction(self) -> Decimal:
        """Round-trip taker friction: 2x taker fee + 2x estimated slippage."""
        return (self.taker_fee_rate * Decimal("2")) + (self.est_slippage_rate * Decimal("2"))

    def round_trip_maker_friction(self) -> Decimal:
        """Round-trip sniper friction: 1x maker entry + 1x taker exit + 1x slippage."""
        return self.maker_fee_rate + self.taker_fee_rate + self.est_slippage_rate


# ==============================================================================
# Top-10 Binance USD(S)-M Futures Universe Registry
# ==============================================================================

TOP_10_SYMBOLS: Dict[str, FuturesSymbolConfig] = {
    "BTCUSDT": FuturesSymbolConfig(
        symbol="BTCUSDT",
        price_precision=2,
        quantity_precision=3,
        min_quantity=Decimal("0.001"),
        min_notional=Decimal("5.0"),
    ),
    "ETHUSDT": FuturesSymbolConfig(
        symbol="ETHUSDT",
        price_precision=2,
        quantity_precision=3,
        min_quantity=Decimal("0.001"),
        min_notional=Decimal("5.0"),
    ),
    "SOLUSDT": FuturesSymbolConfig(
        symbol="SOLUSDT",
        price_precision=2,
        quantity_precision=2,
        min_quantity=Decimal("0.01"),
        min_notional=Decimal("5.0"),
    ),
    "BNBUSDT": FuturesSymbolConfig(
        symbol="BNBUSDT",
        price_precision=2,
        quantity_precision=2,
        min_quantity=Decimal("0.01"),
        min_notional=Decimal("5.0"),
    ),
    "XRPUSDT": FuturesSymbolConfig(
        symbol="XRPUSDT",
        price_precision=4,
        quantity_precision=1,
        min_quantity=Decimal("0.1"),
        min_notional=Decimal("5.0"),
    ),
    "DOGEUSDT": FuturesSymbolConfig(
        symbol="DOGEUSDT",
        price_precision=5,
        quantity_precision=0,
        min_quantity=Decimal("1"),
        min_notional=Decimal("5.0"),
    ),
    "ADAUSDT": FuturesSymbolConfig(
        symbol="ADAUSDT",
        price_precision=4,
        quantity_precision=1,
        min_quantity=Decimal("0.1"),
        min_notional=Decimal("5.0"),
    ),
    "AVAXUSDT": FuturesSymbolConfig(
        symbol="AVAXUSDT",
        price_precision=2,
        quantity_precision=2,
        min_quantity=Decimal("0.01"),
        min_notional=Decimal("5.0"),
    ),
    "LINKUSDT": FuturesSymbolConfig(
        symbol="LINKUSDT",
        price_precision=3,
        quantity_precision=2,
        min_quantity=Decimal("0.01"),
        min_notional=Decimal("5.0"),
    ),
    "SUIUSDT": FuturesSymbolConfig(
        symbol="SUIUSDT",
        price_precision=4,
        quantity_precision=1,
        min_quantity=Decimal("0.1"),
        min_notional=Decimal("5.0"),
    ),
}

MEME_ASSETS: Dict[str, FuturesSymbolConfig] = {
    "1000PEPEUSDT": FuturesSymbolConfig(
        symbol="1000PEPEUSDT",
        price_precision=7,
        quantity_precision=0,
        min_quantity=Decimal("1"),
        min_notional=Decimal("5.0"),
    ),
    "PEPEUSDT": FuturesSymbolConfig(
        symbol="PEPEUSDT",
        price_precision=8,
        quantity_precision=0,
        min_quantity=Decimal("10000"),
        min_notional=Decimal("5.0"),
    ),
}

ALL_SUPPORTED_SYMBOLS: Dict[str, FuturesSymbolConfig] = {
    **TOP_10_SYMBOLS,
    **MEME_ASSETS,
}


# ==============================================================================
# Global Quantitative Governance & Risk Bounds
# ==============================================================================

@dataclass(frozen=True)
class GlobalRiskConfig:
    """Institutional risk parameters and safety boundaries."""
    # Leverage & Capital Allocation
    max_account_leverage: int = 5
    base_risk_budget_ratio: Decimal = Decimal("0.015")  # Max 1.5% equity risked per trade
    max_concurrent_positions: int = 3
    max_pair_correlation: Decimal = Decimal("0.85")     # Correlation veto ceiling
    
    # Circuit Breakers
    daily_drawdown_limit_ratio: Decimal = Decimal("0.03") # 3.0% 24h loss forces shutdown
    min_net_fee_hurdle: Decimal = Decimal("0.0050")        # 0.50% net expected gain (Lesson #10)
    min_rr_ratio: Decimal = Decimal("1.50")                # Minimum 1.50:1 Take-Profit over Stop-Loss
    
    # Execution & Microstructure Timeouts
    stale_trade_hours: int = 12                         # Temporal exit threshold
    bracket_confirm_timeout_ms: int = 1000              # Anti-naked-position emergency flatten timeout
    
    # Macro Market Breadth
    breadth_bull_threshold: Decimal = Decimal("0.60")   # >= 60% coins above VWAP
    breadth_bear_threshold: Decimal = Decimal("0.40")   # <= 40% coins above VWAP
    
    # Funding Rate Safety Guard
    max_prohibitive_funding_rate: Decimal = Decimal("0.0003") # 0.03% 8h funding rate veto ceiling


DEFAULT_RISK_CONFIG = GlobalRiskConfig()
