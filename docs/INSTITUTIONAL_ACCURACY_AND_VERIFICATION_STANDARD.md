# Kronos Institutional Testing, Backtesting & Trade Assessment Standard

> **Mission:** Eliminate simulation fantasy, vanity metrics, and execution drift so that **Backtest → Forward Paper → Real-Money Binance Futures** converge to within **±5–10% PnL fidelity**.
>
> **Core Rule:** Any ambiguity in price, queue priority, or fill order MUST resolve **pessimistically** (against the strategy). Alpha that only survives under optimistic fills is not alpha.

---

## Pillar 1: Truth-Grade Execution Simulation (Backtest & Forward Paper)

Both historical backtesters and `scripts/tiger_worker.py --paper` must obey the exact same **Exchange Realism Contract** (using `decimal.Decimal` exclusively):

### 1.1 Causal Entry Fill Rules (Zero Same-Candle Lookahead)
| Order Type | Trigger Condition | Fill Price Formula | Fee Tier (VIP0) |
| :--- | :--- | :--- | :--- |
| **Stop-Market Breakout** (`BUY` above `bar_high`, `SELL` below `bar_low`) | Must occur strictly **after** `signal.created_at_utc` (`tick.ts > signal_ts` or bar $t+1$). Never fill retroactively on the candle that created the signal. | `BUY`: $\max(\text{trigger}, \text{best\_ask}) \times (1 + s_{\text{entry}})$ <br> `SELL`: $\min(\text{trigger}, \text{best\_bid}) \times (1 - s_{\text{entry}})$ | Taker (`0.05%`) |
| **Limit Pullback** (resting passive order) | Price must trade strictly **through** the limit level by $\ge 1$ tick (queue penetration rule — touching exact price does not guarantee fill). | Exact `limit_price` | Maker (`0.02%`) |

### 1.2 Dynamic Slippage & Market Impact Model ($s$)
Replace flat `0 bps` slippage with a composable model grounded in `QuantFlawAuditor.compute_almgren_chriss_impact`:
$$s_{\text{total}} = \frac{\text{Live Spread}}{2} + \max\left(s_{\text{floor}},\; \eta \cdot \sigma_{24\text{h}} \cdot \sqrt{\frac{\text{Notional}}{\text{ADV}_{24\text{h}}}}\right)$$
* **Minimum Taker Slippage Floor ($s_{\text{floor}}$):**
  * Major pairs (`BTC`, `ETH`, `SOL`): `2 bps` (`0.0002`)
  * Mid/Small-cap Altcoins (Tiger prey, `>$30M` turnover): `5 bps` (`0.0005`) on normal entries, `8 bps` (`0.0008`) on stop-loss market flushes.

### 1.3 Order-Type Faithful Exit Rules
1. **Take-Profit (Limit Order):**
   * **Hard Cap:** Fill price is **strictly capped at `pos.take_profit`** (NEVER `current_price`). Real resting limit TPs do not earn phantom positive overshoot during flash spikes.
   * **Queue Penetration:** Trigger only when live WS tick or candle extreme trades strictly past `pos.take_profit`.
   * **Fee:** Maker (`0.02%`).
2. **Stop-Loss & Breakeven Ratchet (Stop-Market Order):**
   * **Bypass Cache:** Must evaluate against **sub-second live WS `@aggTrade` min/max** since last check AND the full un-cached 1m candle `High`/`Low` — never a 25-second cached close.
   * **Fill Price:** `pos.stop_loss` adjusted adversely by `stop_slippage` (`5–8 bps` or live spread). If market gaps past the stop (e.g., fast cascade), fill at the worse of `stop_price` or actual crossing tick.
   * **Fee:** Taker (`0.05%`).
3. **Same-Interval Tie-Breaker (Pessimistic Priority):**
   * If both TP and SL are touched inside the same bar/polling interval without tick-level timestamp proof of which occurred first, **STOP-LOSS ALWAYS WINS**.
4. **Funding Rate Deduction:**
   * If a position crosses Binance Futures funding settlement (`00:00`, `08:00`, `16:00` UTC), deduct/credit actual funding rate $\times$ notional.

---

## Pillar 2: Institutional Backtesting Protocol (Anti-Overfitting)

No parameter change, filter, or new strategy is accepted from a single raw backtest. Every test must clear 4 gates:

### 2.1 Point-in-Time Data Integrity
* **Strict Causality:** Features (ATR, CVD z-score, swing high/low, 1h EMA trend, Volume Profile) at time $t$ may only read data with `timestamp <= t`.
* **Kronos Context Slicing:** Always tail-slice `raw_df.iloc[-512:].copy()` (never head-slice).
* **Survivorship-Free Universe:** Include symbols that later crashed, spiked, or got quarantined during the test window (never filter history using today's active list).

### 2.2 Purged Walk-Forward Validation (WFO)
* Divide historical data chronologically into rolling windows:
  * **In-Sample Calibration (60%)** → **Purge Gap (30–60 min)** → **Out-of-Sample Validation (40%)**.
* Evaluate across **at least 3 distinct volatility/trend regimes**:
  1. Bull Momentum / Melt-Up
  2. Bear Cascade / Liquidation Flush
  3. Low-Volatility Range / Chop
* **Pass Requirement:** Out-of-sample Profit Factor must retain $\ge 70\%$ of in-sample Profit Factor (guards against curve-fitting).

### 2.3 Friction Stress-Test Matrix (Edge Fragility Check)
Every candidate patch/strategy must be scored across 3 friction tiers:
* **1.0x Baseline Reality:** VIP0 fees + modeled slippage (`~0.15%–0.20%` roundtrip total cost).
* **1.5x Stressed:** `1.5×` slippage (volatile altcoin conditions).
* **2.0x Hostile:** `2.0×` slippage (exchange congestion / thin book).
* **Hard Rule:** Strategy must remain **Net Profitable (`PF >= 1.25x`) at 1.5x friction**. Any edge that dies from `+5 bps` extra friction is execution noise and must be rejected.

### 2.4 Dual Counterfactual Audit (For Patches & Filters)
Whenever proposing a guard (e.g., Falling Knife Guard, US Open Lockout):
1. Measure **Losses Prevented** (gross/net dollars saved on losing trades).
2. Measure **Winners Sacrificed** (opportunity cost on winning trades).
3. Verify **False-Positive Ratio** and confirm net expectancy rises out-of-sample, not just on the exact 3 trades that just bled.

---

## Pillar 3: Automated Testing & Hallucination Circuit Breakers

### 3.1 Mandatory Verification Pyramid
1. **Unit & Invariant Suite (`pytest tests/ -q`):**
   * Zero-Float `Decimal` accounting invariant.
   * Bracket geometry invariant (`SL < Entry < TP` for BUY; `TP < Entry < SL` for SELL).
   * Anti-fantasy simulator tests:
     * Assert TP fill **never** exceeds `pos.take_profit`.
     * Assert same-candle retroactive fills are rejected.
     * Assert intra-candle wick stop-out closes the trade even if candle close recovers.
     * Assert same-bar TP+SL collision resolves to `STOP_LOSS`.
2. **Automated `QuantFlawAuditor` Gate:**
   * Automatically runs at the end of every backtest and paper report.
   * Immediately flags `CRITICAL_HALLUCINATION` if:
     * Win Rate `> 78%` (over $N \ge 15$ trades) or Profit Factor `> 10.0x`.
     * Any TP exit PnL exceeds theoretical `(TP - Entry)/Entry` (phantom overshoot).
     * Zero slippage recorded on taker/stop orders.
     * Realized loss exceeds `2.5×` budgeted dollar risk (broken sizing or stop failure).
3. **Closed-Loop Live-to-Paper Calibration (Implementation Shortfall):**
   * For live strategies (Storm / Apex), log `expected_entry_price` vs `actual_binance_fill_price` and `expected_exit_price` vs `actual_binance_exit_price` on every fill.
   * Compute rolling median **Implementation Shortfall (bps)** every 20 live trades and inject that empirical number directly back into the paper/backtest slippage floor.

---

## Pillar 4: Unvarnished Trade Result Assessment Scorecard

Every 12h / 24h / Release assessment report (both live and paper) must output the following **8-Block Truth Scorecard** — never raw PnL or Win Rate in isolation:

### Block 1 — Core Expectancy & Friction Drag
* **Total Trades ($N$)**, **Win Rate (%)**, **Payoff Ratio** ($\text{AvgWin} / \text{AvgLoss}$).
* **Gross PnL** vs. **Total Fees + Slippage + Funding** vs. **Net Realized PnL**.
* **Fee/Friction Drag Ratio:** $\text{Total Friction} / \text{Gross Profit}$ (warning if `> 30%`).
* **Net Profit Factor** ($\text{GrossNetWins} / \text{GrossNetLosses}$) and **Expectancy per Trade (\$)**.

### Block 2 — Risk, Tail & Drawdown Reality
* **Max Peak-to-Trough Drawdown (\$ and %)** and **Longest Losing Streak**.
* **Risk Budget Compliance:** Compare `Avg Loss` and `Worst Loss` against configured `risk_budget_per_trade_usd`.
* **Tail Concentration:** Net PnL **excluding the single best trade** (if removing 1 lucky outlier turns the strategy negative, there is no durable edge).

### Block 3 — Execution Fidelity Audit
* **TP Overshoot Count:** Must be `0` in paper/live.
* **Implementation Shortfall (bps):** Actual fill vs. trigger price (entry & exit separately).
* **Cache/Latency Lag:** Max age of price quote used at fill/exit decision time.

### Block 4 — MFE / MAE Pathology Matrix
* `MFE == 0%` + fast stop (`< 60s`): **Entry Timing / Falling Knife defect**.
* `MFE >= +0.50%` ending in loss: **Exit / Breakeven Ratchet defect** (`MFE_REVERSAL`).
* `MAE` repeatedly exceeds `SL` distance: **Stop-Slippage / Steamroller defect**.

### Block 5 — Multi-Axis Attribution Slicing
Always decompose Net PnL and WR across:
1. **Direction:** `BUY` vs. `SELL` (exposes directional asymmetry).
2. **UTC Session:** Asia (`00:00–07:00`), EU Prime (`07:00–13:30`), US Open Lockout (`13:30–15:30`), US Session (`15:30–22:00`), Late (`22:00–00:00`).
3. **Volatility Regime:** Slow ATR vs. Fast ATR.
4. **Symbol Concentration:** Top 3 winners vs. Bottom 3 bleeders.

### Block 6 — Statistical Significance & Promotion Gate (Paper → Live)
A paper strategy is **FORBIDDEN** from graduating to real money until ALL 6 gates pass simultaneously under the **Truth-Grade Paper Simulator**:
1. **Sample Size:** $N \ge 40$ closed trades over $\ge 72$ hours (covering at least 3 full UTC daily cycles).
2. **Net Profit Factor:** $\text{PF} \ge 1.40\text{x}$ net of fees and modeled slippage.
3. **Outlier-Stripped Expectancy:** Net PnL remains **`> $0`** even after removing the single largest winning trade.
4. **Directional Balance:** Neither `BUY` nor `SELL` side has a catastrophic negative bleed (`PF < 0.75x` with $N \ge 10$).
5. **Drawdown Cap:** Max drawdown $\le 5.0\%$ of allocated capital; worst single trade loss $\le 1.8\times$ budgeted trade risk.
6. **Zero Hallucinations:** `QuantFlawAuditor` returns `CLEAN` (zero TP overshoot, zero same-candle fills, zero float drift).
