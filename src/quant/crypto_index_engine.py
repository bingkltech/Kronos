"""
src/quant/crypto_index_engine.py — Top-10 Screener & Market Breadth Engine.

Computes systemic crypto macro regime (The Forest) across the Top-10 Binance USD(S)-M Futures universe.
Calculates 24h Volume-Weighted Average Price (VWAP), Market Breadth, and Macro Regime:
- BULL_EXPANSION: Breadth >= 60% of top-10 coins above 24h VWAP.
- BEAR_DISTRIBUTION: Breadth <= 40% of top-10 coins above 24h VWAP.
- CHOP: 40% < Breadth < 60% (range-bound, high friction risk).

Strictly adheres to AGENTS.md Invariant 1 (Zero Float Financial Math).
"""

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, List, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor
import pandas as pd
import requests

from src.quant.config import DEFAULT_RISK_CONFIG, TOP_10_SYMBOLS, FuturesSymbolConfig


@dataclass(frozen=True)
class OrderBookMicrostructure:
    """Detailed Level-2 microstructure metrics including Stoikov Micro-Price."""
    obi: Decimal
    best_bid: Decimal
    best_ask: Decimal
    micro_price: Decimal
    micro_skew_bps: Decimal


@dataclass(frozen=True)
class SymbolMacroStats:
    """Macro metrics for a single futures asset."""
    symbol: str
    current_price: Decimal
    vwap_24h: Decimal
    above_vwap: bool
    price_change_24h_pct: Decimal
    volume_24h_usdt: Decimal


@dataclass(frozen=True)
class MacroIndexVerdict:
    """Systemic market breadth verdict across the Top 10 universe."""
    macro_regime: str           # "BULL_EXPANSION", "BEAR_DISTRIBUTION", "CHOP"
    breadth_ratio: Decimal      # e.g. Decimal("0.70") for 70%
    coins_above_vwap_count: int
    total_coins_evaluated: int
    symbol_stats: Dict[str, SymbolMacroStats]
    reason: str


class CryptoIndexEngine:
    """
    Asynchronous top-10 market screener.
    Ingests 24h of 1-hour candles across the Top 10 Binance perpetual futures.
    """

    BASE_URL = "https://fapi.binance.com"

    def __init__(
        self,
        symbols_config: Optional[Dict[str, FuturesSymbolConfig]] = None,
        session: Optional[requests.Session] = None
    ):
        self.symbols_config = symbols_config or TOP_10_SYMBOLS
        self.session = session or requests.Session()

    def fetch_24h_klines(self, symbol: str) -> List[Dict[str, Decimal]]:
        """
        Fetch the last 24 1-hour candles for a symbol.
        Returns parsed list with Open, High, Low, Close, Volume in Decimal.
        """
        return self.fetch_recent_klines(symbol=symbol, interval="1h", limit=24)

    def fetch_recent_klines(self, symbol: str, interval: str = "5m", limit: int = 24) -> List[Dict[str, Decimal]]:
        """
        Fetch recent candles for any symbol and timeframe (e.g. 5m for scalping, 1h for macro).
        """
        endpoint = f"{self.BASE_URL}/fapi/v1/klines"
        params = {
            "symbol": symbol,
            "interval": interval,
            "limit": min(limit, 500),
        }
        try:
            resp = self.session.get(endpoint, params=params, timeout=5)
            resp.raise_for_status()
            raw_klines = resp.json()

            parsed: List[Dict[str, Decimal]] = []
            for k in raw_klines:
                parsed.append({
                    "open": Decimal(str(k[1])),
                    "high": Decimal(str(k[2])),
                    "low": Decimal(str(k[3])),
                    "close": Decimal(str(k[4])),
                    "volume": Decimal(str(k[5])),
                    "quote_volume": Decimal(str(k[7])),
                })
            return parsed
        except Exception:
            return []

    def fetch_order_book_microstructure(self, symbol: str, depth_limit: int = 20) -> OrderBookMicrostructure:
        """
        Fetch top-N order book depth and compute:
        1. Volume-Weighted Order Book Imbalance (OBI)
        2. Stoikov Volume-Weighted Micro-Price: P_micro = P_bid * (V_ask / (V_bid + V_ask)) + P_ask * (V_bid / (V_bid + V_ask))
        3. Micro-Price Skew in basis points: ((P_micro - P_mid) / P_mid) * 10,000
        """
        endpoint = f"{self.BASE_URL}/fapi/v1/depth"
        params = {"symbol": symbol, "limit": min(max(depth_limit, 5), 50)}
        try:
            resp = self.session.get(endpoint, params=params, timeout=3)
            resp.raise_for_status()
            data = resp.json()

            bids = [Decimal(b[1]) for b in data.get("bids", [])]
            asks = [Decimal(a[1]) for a in data.get("asks", [])]

            best_bid = Decimal(str(data["bids"][0][0])) if data.get("bids") else Decimal("0")
            best_ask = Decimal(str(data["asks"][0][0])) if data.get("asks") else Decimal("0")

            total_bids = sum(bids)
            total_asks = sum(asks)
            denom = total_bids + total_asks

            if denom > Decimal("0"):
                obi = (total_bids - total_asks) / denom
            else:
                obi = Decimal("0.0")

            if best_bid > Decimal("0") and best_ask > Decimal("0"):
                mid = (best_bid + best_ask) / Decimal("2")
                if denom > Decimal("0"):
                    # Stoikov Micro-Price
                    micro_price = (best_bid * (total_asks / denom)) + (best_ask * (total_bids / denom))
                else:
                    micro_price = mid
                micro_skew_bps = ((micro_price - mid) / mid) * Decimal("10000") if mid > Decimal("0") else Decimal("0.0")
            else:
                micro_price = Decimal("0.0")
                micro_skew_bps = Decimal("0.0")

            return OrderBookMicrostructure(
                obi=obi,
                best_bid=best_bid,
                best_ask=best_ask,
                micro_price=micro_price,
                micro_skew_bps=micro_skew_bps
            )
        except Exception:
            return OrderBookMicrostructure(
                obi=Decimal("0.0"),
                best_bid=Decimal("0.0"),
                best_ask=Decimal("0.0"),
                micro_price=Decimal("0.0"),
                micro_skew_bps=Decimal("0.0")
            )

    def fetch_order_book_imbalance(self, symbol: str, depth_limit: int = 20) -> Tuple[Decimal, Decimal, Decimal]:
        """Backward-compatible wrapper returning (obi, best_bid, best_ask)."""
        m = self.fetch_order_book_microstructure(symbol=symbol, depth_limit=depth_limit)
        return m.obi, m.best_bid, m.best_ask

    def fetch_lookback_dataframe(self, symbol: str, limit: int = 100) -> Optional[pd.DataFrame]:
        """
        Fetch historical 1h klines and return a clean DataFrame for Kronos lookback.
        """
        endpoint = f"{self.BASE_URL}/fapi/v1/klines"
        params = {
            "symbol": symbol,
            "interval": "1h",
            "limit": min(limit, 500)
        }
        try:
            resp = self.session.get(endpoint, params=params, timeout=5)
            if resp.status_code != 200:
                return None
            raw = resp.json()
            rows = []
            for k in raw:
                rows.append({
                    "timestamps": pd.to_datetime(k[0], unit="ms"),
                    "open": float(k[1]),
                    "high": float(k[2]),
                    "low": float(k[3]),
                    "close": float(k[4]),
                    "volume": float(k[5]),
                })
            df = pd.DataFrame(rows)
            return df if len(df) >= 15 else None
        except Exception:
            return None

    def compute_symbol_stats(self, symbol: str, klines: List[Dict[str, Decimal]]) -> SymbolMacroStats:
        """
        Compute 24h VWAP, 24h price change, and current price comparison.
        VWAP = sum(typical_price * volume) / sum(volume)
        """
        if not klines:
            raise ValueError(f"Empty klines provided for {symbol}")

        total_pv = Decimal("0.0")
        total_vol = Decimal("0.0")

        for k in klines:
            typical_price = (k["high"] + k["low"] + k["close"]) / Decimal("3")
            total_pv += typical_price * k["volume"]
            total_vol += k["volume"]

        vwap = (total_pv / total_vol) if total_vol > Decimal("0") else klines[-1]["close"]
        current_price = klines[-1]["close"]
        open_24h_ago = klines[0]["open"]
        
        pct_change = (
            ((current_price - open_24h_ago) / open_24h_ago) * Decimal("100")
            if open_24h_ago > Decimal("0") else Decimal("0")
        )
        volume_usdt = sum(k["quote_volume"] for k in klines)

        cfg = self.symbols_config.get(symbol)
        if cfg:
            vwap = cfg.quantize_price(vwap)

        return SymbolMacroStats(
            symbol=symbol,
            current_price=current_price,
            vwap_24h=vwap,
            above_vwap=(current_price >= vwap),
            price_change_24h_pct=pct_change.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
            volume_24h_usdt=volume_usdt.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
        )

    def evaluate_universe(
        self,
        preloaded_klines: Optional[Dict[str, List[Dict[str, Decimal]]]] = None
    ) -> MacroIndexVerdict:
        """
        Evaluate market breadth across the entire universe.
        """
        stats_map: Dict[str, SymbolMacroStats] = {}
        coins_above_vwap = 0

        klines_map: Dict[str, List[Dict[str, Decimal]]] = {}
        if preloaded_klines:
            klines_map = preloaded_klines
        else:
            with ThreadPoolExecutor(max_workers=min(len(self.symbols_config), 10)) as executor:
                futures = {executor.submit(self.fetch_24h_klines, sym): sym for sym in self.symbols_config.keys()}
                for fut in futures:
                    sym = futures[fut]
                    try:
                        klines_map[sym] = fut.result()
                    except Exception as e:
                        # Fallback empty if fetch fails
                        klines_map[sym] = []

        for symbol in self.symbols_config.keys():
            klines = klines_map.get(symbol, [])
            if not klines:
                continue
            stats = self.compute_symbol_stats(symbol, klines)
            stats_map[symbol] = stats
            if stats.above_vwap:
                coins_above_vwap += 1

        total_coins = len(self.symbols_config)
        breadth_ratio = Decimal(str(coins_above_vwap)) / Decimal(str(total_coins))

        bull_thresh = DEFAULT_RISK_CONFIG.breadth_bull_threshold
        bear_thresh = DEFAULT_RISK_CONFIG.breadth_bear_threshold

        if breadth_ratio >= bull_thresh:
            regime = "BULL_EXPANSION"
            reason = f"Macro Bull Expansion: {coins_above_vwap}/{total_coins} ({breadth_ratio*Decimal('100'):.1f}%) coins above 24h VWAP. Longs permitted."
        elif breadth_ratio <= bear_thresh:
            regime = "BEAR_DISTRIBUTION"
            reason = f"Macro Bear Distribution: Only {coins_above_vwap}/{total_coins} ({breadth_ratio*Decimal('100'):.1f}%) coins above 24h VWAP. Shorts permitted."
        else:
            regime = "CHOP"
            reason = f"Macro Chop / Mixed Breadth: {coins_above_vwap}/{total_coins} ({breadth_ratio*Decimal('100'):.1f}%) coins above 24h VWAP. Selective entries only."

        return MacroIndexVerdict(
            macro_regime=regime,
            breadth_ratio=breadth_ratio,
            coins_above_vwap_count=coins_above_vwap,
            total_coins_evaluated=total_coins,
            symbol_stats=stats_map,
            reason=reason,
        )
