# Volatility-Buffered Ratchet, Microstructure Friction & Universe Governance

**Module / Specification Reference:** `KRONOS-SPEC-2026-11-L18`  
**Severity / Impact:** CORE EXECUTION ARCHITECTURE & FRICTION MITIGATION  
**System Components:** [`src/quant/apex_scalper.py`](file:///F:/012D_TRADE/Kronos/src/quant/apex_scalper.py), [`src/quant/kev_risk_arbiter.py`](file:///F:/012D_TRADE/Kronos/src/quant/kev_risk_arbiter.py), [`src/quant/config.py`](file:///F:/012D_TRADE/Kronos/src/quant/config.py), [`webui/app.py`](file:///F:/012D_TRADE/Kronos/webui/app.py)  
**Status:** IMPLEMENTED, TESTED & DEPLOYED ([Commit `d928912`](https://github.com/bingkltech/Kronos/commit/d928912))  
**Registered Institutional Lesson:** Active Lesson #18 in [`data/lessons.db`](file:///F:/012D_TRADE/Kronos/data/lessons.db) (`volatility_buffered_ratchet_and_universe_hygiene`)

---

## 1. Executive Summary & Purpose

This institutional document codifies the findings, mathematical models, empirical audit data, and architectural changes from the **3-day live Binance Futures performance review** conducted on November 9, 2026.

It addresses three vital operational dimensions:
1. **The Volatility-Buffered Ratchet:** Replacing inverted 0.5:1 profit-snatching and naïve breakeven traps with an asymmetric trailing ratchet that guarantees fee coverage at $+0.40\%$ while preserving $+2.5\%$ positive skew runners.
2. **Universe Governance & The False Discovery Trap:** Quantitative rebuttal to the "Top 50 universe" fallacy, detailing the statistical (multiple comparisons bias), microstructure (spread expansion), and computational (Binance 2,400 weight API limit) boundaries that demand a curated 10–12 hyper-liquid universe.
3. **Small-Account Friction & Capital Clamping:** Fixing the Bitcoin micro-notional balloon bug to clamp BTC lot sizes to 0.001 BTC (~$76), cutting Bitcoin fee drag by 67%.
4. **State Reconciliation & External Flatten Adaptation:** Auto-detecting manual trade closures executed directly in the Binance app, releasing the scalper slot and cancelling orphan algo orders.

---

## 2. 3-Day Real Live Financial Audit (139 Income Events)

A forensic query of Binance USD(S)-M Futures ledger endpoints (`/fapi/v1/income`) across 72 hours (November 6–9, 2026) revealed the empirical baseline of our live micro-trading account:

```
========================================================================================
 [Binance USD-M Futures] 72-Hour Forensic Financial Audit (139 Ledger Events)
========================================================================================
 Starting Equity (Nov 6)    : $182.91 USDT
 Current Wallet Balance     : $183.79 USDT (Net Gain: +$0.88 USDT)
 Gross Realized Trading PnL : -$0.8660 USDT
 Total Exchange Commissions : -$2.1550 USDT (Paid in 0.00202 BNB @ ~$676/BNB)
 Net Funding Fees Received  : +$0.0922 USDT (Carry was NET POSITIVE!)
 Net Realized PnL (Friction): -$2.9289 USDT
 Active Unrealized PnL      : +$1.1000 USDT (ETHUSDT Short open at +2.24% gain)
========================================================================================
```

### Symbol-by-Symbol Breakdown

| Symbol | Gross PnL | Commissions | Net Funding | Net Operational PnL | Trades / Funding | Performance Verdict |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **`XRPUSDT`** | **+$4.0724** | -$0.3612 | +$0.0224 | **+$3.7336** | 13 tr / 5 fund | **Alpha Engine (8.8% fee drag)** |
| **`LINKUSDT`** | **+$1.0905** | -$0.1304 | +$0.0013 | **+$0.9614** | 3 tr / 1 fund | **High Efficiency (11.9% fee drag)** |
| **`BNBUSDT`** | **+$0.7616** | -$0.0426 | +$0.0000 | **+$0.7190** | 1 tr / 0 fund | **Clean Win (5.5% fee drag)** |
| **`SOLUSDT`** | **+$0.6986** | -$0.0874 | +$0.0000 | **+$0.6112** | 2 tr / 0 fund | **Solid Gain (12.5% fee drag)** |
| **`SUIUSDT`** | **+$0.2062** | -$0.0435 | +$0.0033 | **+$0.1659** | 2 tr / 1 fund | **Positive Net** |
| **`ETHUSDT`** | **+$0.3160** | -$0.2516 | -$0.0024 | **+$0.0620** | 6 tr / 2 fund | **Positive** *(+$1.10 open)* |
| `ADAUSDT` | -$0.8040 | -$0.0434 | -$0.0049 | -$0.8523 | 1 tr / 1 fund | Standard stop-out |
| `1000PEPEUSDT`| -$1.5641 | -$0.1302 | -$0.0050 | -$1.6992 | 3 tr / 1 fund | Mixed chop |
| `BTCUSDT` | **-$5.6432** | **-$1.0648** | +$0.0776 | **-$6.6305** | 7 tr / 6 fund | **Oversized Notional Bottleneck** |

### Key Audit Conclusions:
1. **The Altcoin Core Generated +$6.19 Net Profit:** `XRP`, `LINK`, `BNB`, `SOL`, and `SUI` generated +$6.83 gross gains with only -$0.66 in fees (a stellar **9.6% fee-to-profit ratio**).
2. **Bitcoin Caused 50% of All Commissions:** BTC trades generated $1.0648 in commissions alone due to oversized notional sizing (~$228 per trade).
3. **Carry was Net Positive (+0.0922 USDT):** Funding rates were positive across the board, paying our short positions funding interest and dispelling concerns of negative carry bleed.

---

## 3. Pillar 1: The Volatility-Buffered Ratchet (Lesson #18)

### The Quantitative Flaw in Previous Exit Logic
Previously, the scalper utilized two flawed mechanics:
1. **Fast Profit Snatch (+0.25% market close):** Capped wins at $+0.25\%$ (\$0.125 on \$50 notional) while risking $-0.40\%$ to $-0.50\%$ on Stop-Loss (\$0.225).
   - Reward-to-Risk ratio was inverted: $b = 0.55 : 1$.
   - Required break-even win rate: $p^* = \frac{0.225 + 0.045}{0.125 + 0.225} = \mathbf{77.1\%}$.
2. **Naïve Breakeven (Stop to Entry at 0.0%):** Moving stops to entry price when slightly green places the stop directly inside the 1-minute $\pm 0.15\%$ bid-ask noise band. Routine retests trip the stop, while round-trip exchange fees (~0.09%) turn "breakeven" trades into **realized financial losses**.

### The Institutional Solution: The Volatility-Buffered Ratchet
Instead of market-closing at $+0.25\%$ or pinning stops at $0.0\%$:
1. **Wait for Expansion:** Price must clear the noise band by expanding $\ge \mathbf{+0.40\%}$ in our favor.
2. **Ratchet to Entry + Fees:** Move the Stop-Loss to $\mathbf{\text{Entry} + \text{Round-Trip Fees} \, (0.10\%)}$.
3. **Leave Upside Open:** DO NOT market-close. Allow the trade to run toward the full dynamic ATR Target (+1.5% to +2.5%).

$$\text{Ratcheted SL}_{\text{BUY}} = P_{\text{entry}} \times \left(1 + \frac{\text{Friction}_{\text{pct}}}{100}\right)$$
$$\text{Ratcheted SL}_{\text{SELL}} = P_{\text{entry}} \times \left(1 - \frac{\text{Friction}_{\text{pct}}}{100}\right)$$

### Expectancy Transformation:
- **Average Win ($W$):** Weighted blend of guaranteed green retests (+$0.02) and runners (+$1.10) $\approx \mathbf{+\$0.55 \text{ USDT}}$.
- **Average Loss ($L$):** Capped at initial ATR Stop $\approx \mathbf{-\$0.20 \text{ USDT}}$.
- **New Reward-to-Risk Ratio:** $\mathbf{2.75 : 1}$.
- **Required Break-Even Win Rate:** Drops from **77.1% down to 26.6%**!

```python
# Implementation: src/quant/apex_scalper.py
def evaluate_ratchet(self, current_price: Decimal, fee_friction_pct: Decimal = Decimal("0.10"), expansion_threshold_pct: Decimal = Decimal("0.40")):
    if not self.active_scalp or self.active_scalp.ratchet_active:
        return False, None
    pos = self.active_scalp
    entry = pos.entry_price
    if pos.side == "BUY":
        net_gain_pct = (((current_price - entry) / entry) * Decimal("100")) - fee_friction_pct
        if net_gain_pct >= expansion_threshold_pct:
            new_sl = entry * (Decimal("1.0") + (fee_friction_pct / Decimal("100")))
            if new_sl > pos.stop_loss:
                # Update Stop-Loss to guaranteed green level
                self.active_scalp = self.active_scalp._replace(stop_loss=new_sl, ratchet_active=True)
                return True, new_sl
    # (Symmetric logic for SELL)
```

---

## 4. Pillar 2: Universe Size Governance (Top 10 vs. Top 50)

The hypothesis that *"More choices mean more chances"* was evaluated and rejected based on four institutional quant invariants:

### 1. The Multiple Comparisons Fallacy (Spurious Alpha)
Scanning $N$ assets at confidence level $\alpha = 0.05$ creates an escalating Family-Wise Error Rate (FWER):
$$\text{FWER} = 1 - (1 - \alpha)^N$$
- For $N = 10$: $\text{FWER} = 1 - (0.95)^{10} = \mathbf{40.1\%}$.
- For $N = 50$: $\text{FWER} = 1 - (0.95)^{50} = \mathbf{92.3\%}$.

In a 50-coin universe, the highest-ranking candidate is mathematically almost guaranteed to be **random microstructure noise or an unclosed liquidity wick**, rather than true predictive edge.

### 2. Microstructure Spread & Depth Penalty
Top 10 assets (`BTC`, `ETH`, `SOL`, `XRP`) have tight 0.5–1.5 bps spreads and deep \$500k+ order books. Coins #20 through #50 have **5.0–20.0 bps spreads** (up to 10x wider) and thin books. Entering coins #20–#50 incurs an immediate **-0.25% to -0.40% round-trip slippage penalty**, destroying the scalper's edge.

### 3. API Quota & Latency Constraints
- **Binance IP Weight Limit:** 2,400 weight per minute.
- Top 10 universe burns $\approx 150 \text{ weight/cycle}$ (6% quota, safe).
- Top 50 universe burns $\approx 750 \text{ weight/cycle}$. At 1–2 minute cycles, weight reaches **1,500–2,250 weight/min**, risking HTTP 429 IP bans.
- Sequential REST latency for 50 order books takes **12–15 seconds**, rendering candle snapshots stale.

### 4. Machine Learning Inference Budget
Kronos ONNX neural rollouts require 512 context tokens. Running 50 neural trajectories every scan will saturate 100% CPU on cloud instances (e.g. AWS t4g.small / t3.micro), triggering CPU throttling and service crashes.

**Governance Verdict:** The asset universe is strictly locked to the **Top 10–12 Hyper-Liquid Pairs** (`BTC`, `ETH`, `SOL`, `BNB`, `XRP`, `DOGE`, `ADA`, `AVAX`, `LINK`, `SUI`, `1000PEPE`).

---

## 5. Pillar 3: Bitcoin Sizing Fix & Capital Preservation

### The Sizing Balloon Bug
In [`src/quant/kev_risk_arbiter.py`](file:///F:/012D_TRADE/Kronos/src/quant/kev_risk_arbiter.py), the small-account micro-notional ceiling was configured to $50.00 USDT.
- For Bitcoin at \$76,000, 1 minimum contract lot (0.001 BTC) equals **\$76.00 notional**.
- Because \$50.00 could not buy 1 minimum lot, `max_units` quantized to `0.000 BTC`.
- The condition `if max_units >= cfg.min_quantity:` evaluated to `False`, **bypassing the ceiling guard entirely** and allowing raw risk sizing to dispatch **0.003 BTC (\$228 notional)**!

### The Institutional Clamp
```python
# Fixed in src/quant/kev_risk_arbiter.py
if notional_usd > max_micro_notional:
    step = Decimal("10") ** -cfg.quantity_precision
    max_units = (max_micro_notional / entry).quantize(step, rounding=ROUND_DOWN)
    if max_units >= cfg.min_quantity and (max_units * entry) >= cfg.min_notional:
        quantized_qty = max_units
    else:
        # Fallback: Clamp strictly to 1 single minimum lot (0.001 BTC)
        # Prevents sizing from ballooning to 0.003 BTC ($228 notional)
        quantized_qty = cfg.min_quantity
    notional_usd = (quantized_qty * entry).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
```
This guarantees that Bitcoin trades on small accounts are strictly capped at **0.001 BTC (~$76)**, cutting Bitcoin fee drag and margin requirements by **67%**.

---

## 6. Pillar 4: State Reconciliation & External Flatten Adaptation

If an operator manually market-closes a position directly on the Binance mobile app or web interface, Kronos automatically synchronizes state within 3 seconds:

```python
# Implementation: webui/app.py
if live_trading_enabled:
    live_acc = quant_bot.executor.get_live_account_summary()
    if live_acc.get("connected"):
        open_syms = [p.get("symbol") for p in live_acc.get("positions", [])]
        if pos.symbol not in open_syms:
            print(f">> [External Flatten Detected] {pos.symbol} position closed on Binance. Releasing scalp slot.")
            # 1. Clean up lingering algo orders on Binance
            quant_bot.executor._signed_request("DELETE", "/fapi/v1/algoOpenOrders", {"symbol": pos.symbol})
            quant_bot.executor._signed_request("DELETE", "/fapi/v1/allOpenOrders", {"symbol": pos.symbol})
            # 2. Release in-memory scalp slot
            apex_scalper.close_scalp(exit_price=curr_price, close_reason="MANUAL_OVERRIDE", current_time_utc=now_utc)
            return
```

---

## 7. Automated Test Suite & Verification Gates

| Test Target | Suite | Verification Result |
| :--- | :--- | :--- |
| **Volatility-Buffered Ratchet** | [`tests/test_apex_scalper.py`](file:///F:/012D_TRADE/Kronos/tests/test_apex_scalper.py) | Verified ratchet ignores $<+0.40\%$ noise, triggers at $+0.55\%$, and locks Stop at `Entry + 0.10%`. |
| **Bitcoin Micro-Notional Clamp** | [`tests/test_kev_risk_arbiter.py`](file:///F:/012D_TRADE/Kronos/tests/test_kev_risk_arbiter.py) | Verified 8/8 sizing tests pass; large assets clamp to single minimum contract lot. |
| **System Smoke Check** | [`tests/test_smoke.py`](file:///F:/012D_TRADE/Kronos/tests/test_smoke.py) | Verified end-to-end pipeline integrity (4 passed in 3.04s). |
| **Lessons Database** | [`data/lessons.db`](file:///F:/012D_TRADE/Kronos/data/lessons.db) | Staged and promoted as **Active Lesson #18**. |
