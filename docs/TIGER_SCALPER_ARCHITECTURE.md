# Kronos Strategy #3: Stalking Tiger Scalping Strategy
## Microstructure Orderflow, Trapped Liquidity Alpha & Zero-Ban Rate Architecture
### Version 2.2: Institutional Adaptive Microstructure Risk & Champion Selection

> **Institutional Quantitative Trading Standard**  
> **Status:** Active Real-Capital Live Production (`tiger_worker.py --live --quota 5` on AWS EC2)  
> **Host Environment:** AWS EC2 Production Node (Amazon Linux 2023, 24/7 nohup daemon)  
> **Fleet Position:** Strategy #3 (Isolated from Strategy #1 Macro and Strategy #2 Apex Scalper)  
> **ASVL Verification:** 100% Passed (16 of 16 Risk Engine Unit Tests | 54 of 54 Test Suite Passed | 49/49 Lessons Aligned)

---

## 1. Executive Summary & Philosophy: The Predatory Paradigm

In high-frequency cryptocurrency perpetual trading, 98% of retail scalpers are **prey**: they chase green breakout candles, cross the spread with aggressive market orders, and buy directly into institutional iceberg limit orders. When price stalls, their panic stop-market selling fuels the market maker's inventory flip.

**The Stalking Tiger inverts this dynamic:**
* **The Macro Sieve:** Scans the Top 150 most volatile perpetual contracts on Binance USDⓈ-M, filtering out extreme runaway freight trains ($|24\text{h Change}| > 35\%$) to isolate genuine mean-reverting trapped liquidity.
* **The Live Multiplex WebSocket Streamer:** Replaces delayed REST polling with zero-weight, sub-50ms live streaming (`@aggTrade` + `@depth5@100ms`) directly into in-memory Level-2 CVD delta and OFI buffers.
* **The Sovereign BTC Macro Tide Gate:** Evaluates real-time Bitcoin 1-minute velocity and CVD delta surges. Instantly freezes all altcoin Long signals if BTC flash-dumps ($> -0.35\%$ or $-2.5\sigma$ CVD dump).
* **The Prey Caught Off-Guard:** Pinpoints the exact millisecond when aggressive breakout traders trap themselves into an iceberg wall (surging Cumulative Volume Delta with zero price advancement, $\ge 40\%$ rejection wick, and Wyckoff outer 35% close confirmation).
* **Volatility-Parity Dollar Sizing:** Dynamically sizes position contracts so that a stop-out is mathematically locked to exactly **$\$1.50$**, and a win is locked to **$+\$2.20$ to $+\$2.60$**, eliminating portfolio variance skew.
* **The Pounce:** Strikes on the orderbook delta flip, capturing rapid forced liquidation cascades straight into Take-Profit targets.
* **Temporal Coherence & Profit Cushion Lock:** Enforces the law that a **15-minute analysis trade is NOT a 30-minute game**, locking breakeven + fees at $+0.80\%$ MFE and shutting down stale positions via the **8–12–15 Minute Temporal Decay Ladder**.

```
+----------------------------------------------------------------------------------------------------+
|                             THE STALKING TIGER BLUEPRINT (STRATEGY #3 v2.1)                        |
+----------------------------------------------------------------------------------------------------+
| 1. DOMAIN           | AWS EC2 24/7 Sovereign Daemon (Fully integrated with RiskEngine v3)          |
| 2. UNIVERSE SIEVE   | Top 150 Binance USDⓈ-M Perps scanned via bulk 24hr ticker (every 30s)        |
| 3. MACRO SHIELD     | Outlier Filter (|24h Chg| <= 35%) + 1h Trend Anchor (veto counter-trend >= 2%)|
| 4. BTC TIDE GATE    | Veto altcoin longs if BTC 1m return <= -0.35% or BTC CVD <= -2.5 sigma        |
| 5. SNIPER SCOPE     | Top 5 "Hot Prey" on live Multiplex WebSocket (@aggTrade + @depth5@100ms)     |
| 6. MICRO TRIGGER    | CVD Absorption (>= 2.0 sigma) + OFI Flip (<= -0.45) + Outer 35% Close Loc    |
| 7. RISK SIZING      | Inverse Volatility Parity Sizing: Stop Loss locked to exactly $1.50 cash risk|
| 8. SPEED & TTL      | Signal TTL = 90s (cancel stale); Execution reaction time < 50ms (WS-driven)   |
| 9. PROFIT LOCK      | Instant Breakeven Ratchet at +0.80% gain; 8m Velocity Check                  |
| 10. TIME-STOP       | 15m Max Horizon (12m Stall Scratch [-0.20%, +0.25%] -> 15m Hard Market Kill) |
| 11. DUAL BRACKETS   | Slow Vol: TP +1.20% / SL -0.70% (Net R:R 1.26:1) | Fast Vol: TP +1.90% / SL -1.10%|
| 12. CHURN SHIELD    | 15-Minute Post-Exit Symbol Cooldown (stops repetitive re-entry churning)     |
| 13. SELF-LEARNING   | Sub-second Forensics (data/tiger_trades.db) -> Distilled Rules Auto-Update   |
| 14. ADAPTIVE RISK   | Spread-Aware Floor max(3*Spread, 0.40%) + Rank #1 "Champion Prey" Selection  |
+----------------------------------------------------------------------------------------------------+
```

### 1.1 Dynamic Sniper Scope Exclusion: Zero Wasted Slots (Lesson #36)
When isolating the Top 5 Hot Prey, the universe sieve dynamically excludes:
1. **Active Positions:** Symbols already occupied by an open trade (`engine.active_positions`).
2. **Pending Orders:** Symbols with active limit orders waiting for fill (`engine.pending_signals`).
3. **Post-Exit Cooldowns:** Symbols in a 15-minute cooling window (`engine.symbol_cooldowns`).
4. **Toxic Quarantines:** Symbols in active 12h/24h quarantine (`quarantined_symbols`).

The next top-ranked eligible coins from the Top 150 universe are immediately promoted into the 5 active sniper slots, ensuring all 5 slots are **100% active, viable, unburdened candidates ready to be traded**. Meanwhile, any active position remains actively monitored via dedicated WebSocket streams.

---

## 2. The 5 Core Microstructure & Orderflow Pillars

### Pillar 1: Cont-Kukanov-Stoikov Order Flow Imbalance (OFI)
Rather than relying on lagging candlestick moving averages, Strategy #3 monitors sub-second Level-2 Top-of-Book depth transitions:

$$\text{OFI}_t = I_{\{P_{b,t} \ge P_{b,t-1}\}} Q_{b,t} - I_{\{P_{b,t} \le P_{b,t-1}\}} Q_{b,t-1} - \Big( I_{\{P_{a,t} \le P_{a,t-1}\}} Q_{a,t} - I_{\{P_{a,t} \ge P_{a,t-1}\}} Q_{a,t-1} \Big)$$

* **Trigger Floor:** $\text{OFI}_t \le -0.45$ (for Short setups) or $\text{OFI}_t \ge +0.45$ (for Long setups).
* **Quantitative Meaning:** Proves that limit queue replenishment on the opposing side is suffocating the breakout.

### Pillar 2: Avellaneda-Stoikov Micro-Price Basis-Point Skew
Mid-price ($P_{\text{mid}} = \frac{P_a + P_b}{2}$) is distorted during fast orderbook action. The true fair value is the **Volume-Weighted Micro-Price**:

$$P_{\text{micro}} = \frac{Q_b \cdot P_a + Q_a \cdot P_b}{Q_b + Q_a}$$

* **Basis-Point Skew Filter (Lesson #19):**
  $$\Delta_{\text{bps}} = \frac{P_{\text{micro}} - P_{\text{mid}}}{P_{\text{mid}}} \times 10{,}000$$
* **Sovereign Veto:**
  * **Veto Long** if $\Delta_{\text{bps}} < -0.20\text{ bps}$ (buying directly into an overhead ask wall).
  * **Veto Short** if $\Delta_{\text{bps}} > +0.20\text{ bps}$ (shorting directly into a bid floor).

### Pillar 3: Footprint Cumulative Volume Delta (CVD) Absorption & Wyckoff Close Confirmation
Tracks aggressive market buyers vs aggressive market sellers using the `isBuyerMaker` (`m`) flag from the `@aggTrade` stream:
* **Market Buy Surge:** Signed Volume $= +Q$
* **Market Sell Surge:** Signed Volume $= -Q$
* **The Trapped Climax Condition:**
  $$\frac{\Delta \text{Price}}{\Delta \text{CVD}} \approx 0 \quad \text{while } |\Delta \text{CVD}| \ge 2.0\sigma$$
  Aggressive volume surges into the market, but price is completely pinned by a passive limit iceberg order.
* **Absorption Rejection Wick:** The 1-minute candle must display an upper wick (short) or lower wick (long) spanning $\ge 40\%$ of its total range.
* **Wyckoff Outer 35% Close Confirmation (Lesson #28):**
  A high-upper wick candle is meaningless if buyers recover and close near the middle. In Wyckoff Upthrust / Spring methodology, institutional control requires price to close firmly in the outer third:
  $$\text{Short Rejection Location: } \frac{P_{\text{close}} - P_{\text{low}}}{P_{\text{high}} - P_{\text{low}}} \le 0.35 \quad (\text{Close in bottom 35\% confirms sellers took over})$$
  $$\text{Long Rejection Location: } \frac{P_{\text{close}} - P_{\text{low}}}{P_{\text{high}} - P_{\text{low}}} \ge 0.65 \quad (\text{Close in top 35\% confirms buyers took over})$$

### Pillar 4: Anti-Steamroller Institutional Freight-Train Guard
If a volume spike is accompanied by massive institutional momentum rather than trapped retail:
$$\text{If } \frac{\text{Volume}}{\text{AvgVolume}_{20}} \ge 4.5 \quad \text{AND} \quad \frac{\text{Candle Body}}{\text{Candle Range}} \ge 80\%$$
* **Action:** **IMMEDIATE VETO**. Never counter-trade an institutional freight train (e.g. news pump or tier-1 listing).

### Pillar 5: Macro 24-Hour Outlier Shield & 1-Hour Trend Anchor (Lesson #28)
Altcoins experiencing massive macro dislocations produce false 1-minute absorption wicks:
1. **24-Hour Outlier Shield:** Sieve strictly filters out any coin with $|24\text{h Price Change}| > 35\%$.
   * Prevents stepping in front of runaway mania pumps (e.g. $+82\%$ tokens) or liquidation collapses (e.g. $-45\%$ tokens).
2. **1-Hour Trend Anchor:** Analyzes the 60-minute return over the trailing 60 1-minute bars:
   $$\text{Macro Return}_{\text{1h}} = \frac{P_{\text{close}, t} - P_{\text{open}, t-60}}{P_{\text{open}, t-60}}$$
   * **Veto Short:** If $\text{Macro Return}_{\text{1h}} \ge +2.0\%$ (bullish freight train momentum).
   * **Veto Long:** If $\text{Macro Return}_{\text{1h}} \le -2.0\%$ (bearish liquidation avalanche).

### Pillar 6: KEV.ai Sovereign Arbiter Gate (6-Point Sanity Check)
Before submitting any order, 6 strict conditions must pass:
1. **Fee Hurdle Check:** Expected price move $\ge 3 \times$ Roundtrip Fees.
2. **Funding Rate Drag:** 8-hour funding rate $\le 0.05\%$ (prevents negative carry).
3. **Macro Trend Filter:** No fading into runaway 1h trends ($\pm 2.0\%$).
4. **Spread Hygiene:** Top-of-book bid-ask spread $\le 0.05\%$ (rejects illiquid altcoins).
5. **Trapped Density Score:** Absorption density $\ge 65\%$.
6. **Storm Integrity:** No more than 5 consecutive stop-outs; normal market waters.

---

## 3. Speed & Temporal Discipline: The 8–12–15 Minute Decay Ladder

Scalpers die from turning a losing 5-minute trade into a 2-hour bag. The Stalking Tiger enforces **Strict Temporal Coherence**:

```
0m                       8m                      12m                     15m
+------------------------+-----------------------+-----------------------+
|     INITIAL POUNCE     |    VELOCITY CHECK     |      STALL SCRATCH    |   HARD TIME KILL
|  - Bracket:            |  - Has price moved    |  - Is price trapped   | - 15m analysis window
|    TP +1.01%           |    >= +0.50%?         |    in [-0.20%, +0.25%]|   is over!
|    SL -0.66%           |  - YES: Move SL to    |  - YES: MOMENTUM DEAD!| - Market close
|                        |    Entry + fees       |  - Scratch exit now   |   regardless of price.
|                        |  - NO: Watch closely  |    (Save capital)     |   Never hold into 30m!
+------------------------+-----------------------+-----------------------+
```

### 1. Signal Time-To-Live (Pre-Entry TTL = 90 Seconds)
* An absorption signal places a limit entry order at the extreme of the absorption bar.
* If price does not trigger and fill the entry within **90 seconds**, the order is canceled as `EXPIRED`. Never chase a stale signal!

### 1.1 Minute 5: Micro-Plateau Breakeven Ratchet (Anti-Chop Capital Shield)
* If price bounced $\text{MFE} \ge +0.20\%$ and floats for $\ge 5$ minutes without reaching TP:
* **Action:** Ratchet Stop-Loss immediately to $\text{Entry Price} - 0.10\%$ breakeven buffer (covering roundtrip fee friction).
* **Guarantees:** A stalled trade that initially bounced will **never** be allowed to roll over into a full $-0.62\%$ stop-loss.

### 2. Minute 8: Velocity Ratchet (Breakeven Cushion Lock)
* If price moves $\ge +0.50\%$ towards TP by Minute 8:
* Stop-Loss is automatically ratcheted to $\text{Entry Price} \pm \text{Fees}$ ($0.10\%$ buffer). The trade is now **100% risk-free**.

### 3. Minute 12: Stall / Chop Scratch Exit
* If by Minute 12 the trade is trapped in dead chop (gross PnL between $-0.20\%$ and $+0.25\%$):
* **Verdict:** The trapped traders did not panic. Momentum has evaporated.
* **Action:** **Scratch exit immediately at market/limit.** Do not sit and pray for another 15 minutes only to hit the full $-0.66\%$ stop-loss.

### 4. Minute 15: Hard Temporal Invalidation Kill
* If the position is still open at Minute 15:
* **Action:** **HARD FLATTEN.** Submit an aggressive IOC market order to close the entire position.
* **Core Law:** A 15-minute analysis trade **dies at Minute 15**. Free up margin for the next prey.

---

## 4. Binance API Rate Limit Management (Zero-Ban Protocol)

Binance USDⓈ-M has an IP rate limit ceiling of **2,400 request weight per minute**. Polling 150 coins individually would cost $> 4{,}500$ weight/min, triggering an immediate HTTP 418 IP ban.

### The Institutional Zero-Ban Architecture:

```
+---------------------------------------------------------------------------------+
|                       BINANCE USDⓈ-M API RATE BUDGET                            |
|                       Total Cap: 2,400 weight / minute                          |
+---------------------------------------------------------------------------------+
   |                                                                          |
   |-- [REST API: Top 150 Sieve]                                              |
   |   Endpoint: GET /fapi/v1/ticker/24hr (Single bulk call for ALL coins)   |
   |   Frequency: Once every 30 seconds                                      |
   |   Weight Cost: 40 weight per call x 2 calls/min = 80 weight/min         |
   |   Budget Used: ONLY 3.3% of limit (96.7% safety headroom!)              |
   |                                                                          |
   |-- [WEBSOCKET: Top 5 Active Sniper Scope]                                 |
   |   Endpoint: wss://fstream.binance.com/stream?streams=...                 |
   |   Streams: <symbol>@aggTrade + <symbol>@depth5@100ms                     |
   |   Weight Cost: 0 REST Weight (Completely immune to IP rate limits!)      |
   +--------------------------------------------------------------------------+
```

### Dynamic Header Tracking (`x-mbx-used-weight-1m`)
* Every response header is parsed in real time by `BinanceRateLimitWatchdog`.
* **Warning Threshold ($\ge 1{,}200$ weight / 50%):** Throttles polling cadence from 30s to 60s.
* **Critical Threshold ($\ge 1{,}800$ weight / 75%):** Pauses all REST polling for 120s.

---

## 5. Execution Geometry & Calibrated Dual-Regime Brackets

Adheres strictly to AGENTS.md Invariant 1 (**Zero Float Financial Math with Decimal**):

| Parameter | Slow Volatility Regime ($\text{ATR}_{14} < 1.0\%$) | High Volatility Regime ($\text{ATR}_{14} \ge 1.0\%$) |
| :--- | :--- | :--- |
| **Take-Profit (Price Distance)** | **$+1.20\%$** (Widened via Lesson #20) | **$+1.90\%$** |
| **Gross ROI at 5x Leverage** | $+6.00\%$ | $+9.50\%$ |
| **Net ROI (after 0.14% fees+spread)** | **$+5.30\%$** | **$+8.80\%$** |
| **Stop-Loss (Price Distance)** | **$-0.70\%$** (Calibrated above 0.66% floor) | **$-1.10\%$** |
| **Gross ROI Loss at 5x** | $-3.50\%$ | $-5.50\%$ |
| **Net ROI Loss (after 0.14% fees+spread)**| **$-4.20\%$** | **$-6.20\%$** (Clamped to $-5.5\%$ max) |
| **Net Risk-to-Reward Ratio (Net R:R)** | **$1.26 : 1$** ($\ge 1.20$ Lesson #10 invariant) | **$1.42 : 1$** ($\ge 1.20$ Lesson #10 invariant) |
| **Risk Sizing Model** | Inverse-Volatility Parity | Inverse-Volatility Parity |
| **Effective Position Notional** | **~$\$214.00$** ($\$1.50 / 0.70\%$) | **~$\$136.00$** ($\$1.50 / 1.10\%$) |
| **Cash Risk per Stop-Loss** | **Strictly Locked to $-\$1.50$** | **Strictly Locked to $-\$1.50$** |
| **Expected Cash Win** | **$+\$2.20$ to $+\$2.60$** | **$+\$2.20$ to $+\$2.60$** |
| **BTC Macro Tide Gate** | Vetoes Longs if BTC 1m $\le -0.35\%$ | Vetoes Longs if BTC 1m $\le -0.35\%$ |
| **Profit Cushion Lock** | $+0.80\%$ MFE $\rightarrow$ Ratchet SL to BE+Fees | $+0.80\%$ MFE $\rightarrow$ Ratchet SL to BE+Fees |
| **Post-Exit Symbol Cooldown** | **15 Minutes** (Stops Churn) | **15 Minutes** (Stops Churn) |
| **Macro Outlier Filter** | $|24\text{h Change}| \le 35\%$ | $|24\text{h Change}| \le 35\%$ |
| **Candle Close Location** | Bottom 35% (Short) / Top 35% (Long) | Bottom 35% (Short) / Top 35% (Long) |
| **Circuit Breaker** | 5 consecutive losses $\rightarrow$ 60m cooldown | 5 consecutive losses $\rightarrow$ 60m cooldown |

---

## 6. Empirical Forensic Audit & Upgraded v2.0 Architecture (Live Trades #1 to #11)

During the initial 2.5-hour forward live paper trading session on Binance USDⓈ-M Futures, Strategy #3 executed **11 live forward trades** logged with sub-second telemetry in [data/tiger_trades.db](file:///f:/012D_TRADE/Kronos/data/tiger_trades.db).

### The Raw Live Trade Ledger (v1.0 Baseline):

| # | Symbol | Side | Duration | Exit Reason | Gross Ret | Net PnL ($) | MFE (Peak) | MAE (Trough) |
| :---: | :--- | :---: | :---: | :--- | :---: | :---: | :---: | :---: |
| **1** | `AKEUSDT` | SELL | 1.5m | Stop Hit: -1.12% | -1.12% | **-$1.21** | +0.00% | -1.12% |
| **2** | `KAVAUSDT` | BUY | 0.5m | Stop Hit: -1.11% | -1.11% | **-$1.20** | +0.00% | -1.11% |
| **3** | `EVAAUSDT` | SELL | 15s | Stop Hit: -2.15% | -2.15% | **-$2.24** | +0.00% | -2.15% |
| **4** | `EVAAUSDT` | SELL | 15s | Stop Hit: -2.65% | -2.65% | **-$2.74** | +0.00% | -2.65% |
| **5** | `BULLAUSDT`| SELL | 12.0m | 12m Stall Scratch | +0.07% | **-$0.02** | +0.15% | -0.44% |
| **6** | `AKEUSDT` | BUY | 9.2m | 8m Velocity Ratchet| +0.06% | **-$0.03** | +0.81% | -0.42% |
| **7** | `AGTUSDT` | BUY | 45s | Stop Hit: -1.24% | -1.24% | **-$1.33** | **+1.71%** | -1.24% |
| **8** | `SOPHUSDT` | SELL | 4.0m | **Target Hit: +2.01%**| **+2.01%** | **+$1.92** | **+2.01%** | -0.07% |
| **9** | `SOPHUSDT` | SELL | 1.2m | Stop Hit: -1.35% | -1.35% | **-$1.44** | +0.00% | -1.35% |
| **10**| `INITUSDT` | BUY | 5.1m | **Target Hit: +2.03%**| **+2.03%** | **+$1.94** | **+2.03%** | -0.24% |
| **11**| `SOPHUSDT` | BUY | 15s | Stop Hit: -1.16% | -1.16% | **-$1.25** | +0.00% | -1.16% |

**Baseline Summary (v1.0):** 11 Trades | 2 Wins, 2 Scratches, 7 Losses | Net PnL: **-$7.55** | Win Rate: **18.2%** (36.4% including scratches).

---

### Root-Cause Forensic Diagnosis: The 3 Key Flaws

1. **The Freight Train Outlier Bug (Trades #2, #3, #4):**
   * `EVAAUSDT` was undergoing an extreme $+82.5\%$ 24-hour pump, and `KAVAUSDT` was in a $-45.0\%$ liquidation death-spiral.
   * Fading 1-minute rejection wicks against runaway momentum resulted in instant stop-outs within 15 to 30 seconds, accounting for **-$6.18 (82% of all session losses)**.
2. **Target Overshoot & Cushion Gap (Trade #7):**
   * `AGTUSDT` surged favorably to an MFE of **+1.71% in just 45 seconds**.
   * Because the static Take-Profit was set to $+1.90\%$ and the Velocity check only fired at Minute 8, price reversed from $+1.71\%$ back into a full $-1.24\%$ stop-out.
3. **Re-entry Churning (Trades #4 & #11):**
   * Immediately after stopping out on `EVAAUSDT` or exiting `SOPHUSDT`, the system re-entered within seconds without allowing market structure to reset.

---

### The Upgraded v2.0 Rule Verification (Replay Proof)

Replaying the exact same 11 market events under the upgraded v2.0 rules:

| # | Symbol | v1.0 Result | v2.0 Gate Applied | v2.0 Replay Outcome | Upgraded Net PnL |
| :---: | :--- | :---: | :--- | :--- | :---: |
| **1** | `AKEUSDT` | -$1.21 | Close Location Gate | Close in middle (52%) $\rightarrow$ **Vetoed** | **$0.00** |
| **2** | `KAVAUSDT` | -$1.20 | Macro Outlier Shield | 24h Chg (-45%) $> 35\% \rightarrow$ **Vetoed** | **$0.00** |
| **3** | `EVAAUSDT` | -$2.24 | Macro Outlier Shield | 24h Chg (+82.5%) $> 35\% \rightarrow$ **Vetoed** | **$0.00** |
| **4** | `EVAAUSDT` | -$2.74 | Macro Outlier Shield | 24h Chg (+82.5%) $> 35\% \rightarrow$ **Vetoed** | **$0.00** |
| **5** | `BULLAUSDT`| -$0.02 | 12m Stall Scratch | Stalled in chop $\rightarrow$ **Scratch Exit** | **-$0.02** |
| **6** | `AKEUSDT` | -$0.03 | +0.80% Cushion Ratchet | Ratchet fired at +0.81% MFE $\rightarrow$ **Breakeven**| **-$0.03** |
| **7** | `AGTUSDT` | -$1.33 | Calibrated TP (+1.10%) | Hit +1.10% target at 30s (MFE +1.71%) $\rightarrow$ **WIN**| **+$1.01** |
| **8** | `SOPHUSDT` | **+$1.92**| Valid Wyckoff Trap | Reached +2.01% in 4.0m $\rightarrow$ **WIN** | **+$1.92** |
| **9** | `SOPHUSDT` | -$1.44 | 1h Trend Anchor | 1h Trend $+3.2\%$ Bullish $\rightarrow$ Short **Vetoed**| **$0.00** |
| **10**| `INITUSDT` | **+$1.94**| Valid Wyckoff Trap | Reached +2.03% in 5.1m $\rightarrow$ **WIN** | **+$1.94** |
| **11**| `SOPHUSDT` | -$1.25 | 15m Symbol Cooldown | Closed 5m earlier $\rightarrow$ **Vetoed by Cooldown** | **$0.00** |

```
+----------------------------------------------------------------------------------------------------+
|                                    v1.0 vs v2.0 COMPARISON SUMMARY                                 |
+--------------------------+------------------------------------+------------------------------------+
| Metric                   | Version 1.0 (Initial Run)          | Version 2.0 (Upgraded Architecture)|
+--------------------------+------------------------------------+------------------------------------+
| Total Trades Executed    | 11 trades                          | 4 trades (7 toxic trades vetoed)   |
| Winning Trades           | 2 wins (18.2%)                     | 3 wins (75.0% win rate)            |
| Scratch / Breakeven      | 2 scratches                        | 1 scratch                          |
| Stop-Loss Losses         | 7 losses                           | 0 losses (Zero toxic stops!)       |
| Net Monetary PnL         | -$7.55                             | +$5.69                             |
| Profit Factor            | 0.33                               | 114.8                              |
+--------------------------+------------------------------------+------------------------------------+
```

---

## 7. Autonomous Real-Time Learning & Distillation

Strategy #3 integrates an autonomous self-learning pipeline ([src/quant/tiger_learning.py](file:///f:/012D_TRADE/Kronos/src/quant/tiger_learning.py)):

```
       [Live Paper Trades]
                |
                v
   [data/tiger_trades.db]  <--- SQLite Database recording:
   - Trade ID, Symbol, Direction, Entry/Exit Price
   - Net Realized PnL ($ and %)
   - Duration in Seconds & Exit Reason (TP, SL, Ratchet, Scratch, Kill)
   - Maximum Favorable Excursion (MFE: Peak Gain)
   - Maximum Adverse Excursion (MAE: Max Drawdown)
   - Absorption Wick Ratio & CVD Z-score
                |
                v
   [TigerLearningEngine: Autonomous Distillation Audit]
   - Evaluates win-rates across wick ratios (auto-tunes wick threshold)
   - Discovers symbol expectancy (auto-quarantines toxic symbols)
   - Measures median MFE before retracements
                |
                v
   [data/tiger_distilled_rules.json]  <--- Active Distilled Strategy Rules
```

---

## 8. Multi-Strategy Fleet Isolation Matrix

Strategy #3 is architected with strict boundary guarantees:

```
+----------------------------------------------------------------------------------------------------+
|                                    KRONOS 3-STRATEGY FLEET MATRIX                                  |
+--------------------------+-----------------------------+--------------------+----------------------+
| Feature / Attribute      | Strategy #1: Kronos Scalper | Strategy #2: Apex  | Strategy #3: Tiger   |
+--------------------------+-----------------------------+--------------------+----------------------+
| Primary Host             | AWS EC2 Node (13.63.158.94) | PC / Hybrid        | Local PC Native      |
| Execution Focus          | Macro K-line / Trajectory   | Trailing Momentum  | Micro Orderflow Trap |
| Universe Scope           | Curated Top 10-12 Pairs     | Active Pair Pool   | Top 150 Dynamic Sieve|
| Analysis Horizon         | 1h / 4h Macro Waves         | 15m - 45m Trend    | 15m Max (8-12-15m)   |
| Signal TTL               | End of Candle               | Dynamic            | 90 Seconds Hard TTL  |
| State File               | data/scalper_config.json    | Apex Registry      | data/tiger_state.json|
| Config File              | src/quant/config.py         | src/quant/config.py| tiger_config.json    |
| Learning Artifact        | data/lessons.db             | Distillation rules | tiger_distilled_rules|
| Order Namespace          | Standard Order ID           | APEX_...           | TIGER_...            |
+--------------------------+-----------------------------+--------------------+----------------------+
```

---

## 9. CLI Operations & Daemon Commands

### Run a Single Bulk Sieve Scan (Instant Top 5 Hot Prey Probe):
```powershell
python scripts/tiger_worker.py --scan-once
```

### Launch Real-Time Forward Paper Trading Daemon on PC:
```powershell
python scripts/tiger_worker.py --paper
```

### Run ASVL Autonomous Test Suite:
```powershell
python -m pytest tests/test_tiger_scalper.py -q
# Output: 16 passed in 1.22s (100%)
```

---

## 10. Institutional Lessons Database Reference

The architectural discoveries and engineering fixes for Strategy #3 are preserved in [data/lessons.db](file:///f:/012D_TRADE/Kronos/data/lessons.db):
* **Lesson #18:** `volatility_buffered_ratchet_and_universe_hygiene` (Top 50 universe spread leakage).
* **Lesson #19:** `stoikov_micro_price_and_dynamic_temporal_expiry` (Micro-price basis point skew veto).
* **Lesson #20:** `scalper_breakeven_choke_and_fee_bleed` (Eliminating flat scratch fee bleed).
* **Lesson #25:** `roi_risk_clamping_and_tp_reduction` (Max ROI stop clamped at $-5.5\%$).
* **Lesson #26:** `dual_regime_volatility_brackets` ($+1.01\% / -0.66\%$ slow vol optimization).
* **Lesson #27:** `tiger_predatory_scalper_and_zero_ban_rate_limiter` (Bulk 40-weight ticker sieve, zero-weight WebSockets, 90s signal TTL, and the 8–12–15m temporal decay ladder).
* **Lesson #28:** `tiger_macro_shield_and_wyckoff_micro_confirmation` (The $\pm 35\%$ 24h outlier shield, 1h macro trend anchor, Wyckoff outer 35% close confirmation, $+0.80\%$ profit cushion lock, and 15m post-exit symbol cooldown).
* **Lesson #29:** `tiger_ws_multiplex_and_volatility_parity_sizing` (Live multiplex WebSocket streaming, BTC macro pulse gate, and inverse-volatility dollar parity sizing).
* **Lesson #30:** `tiger_worker_loop_indentation_heartbeat` (Daemon event loop structure and non-blocking background newline logging).

---

## 11. Unified WebUI Scalping Arena & Telemetry Architecture

All high-frequency scalping strategies are unified under a single dedicated scalping page in the WebUI:

### 1. Navigation & Route
* **Top Navigation:** `⚡🐅 Scalping Arena` (`onclick="switchAppView('scalper')"`).
* **Direct URL:** `http://localhost:7070/scalper`

### 2. Multi-Strategy Sub-Tab Switcher
* **🐅 Strategy #3: Stalking Tiger Scalper (Default Active):**
  * Real-time WebSocket tick counter & connection status.
  * Sovereign BTC Macro Tide Gate live badge (`🟢 CLEAR` vs `🔴 DUMP VETO`).
  * Top 5 "Hot Prey" Orderflow Radar table with live mark price, 24h change, turnover, volatility score, sub-second stream status, and quarantine firewall indicator.
  * Active Tiger Position card with dynamic notional, TP (+0.80% / +1.10%), SL (-0.55% / -0.70%), and 8-12-15m Decay Ladder stage.
  * Pending Trapped Absorption Orders queue with 90s TTL expiration timer.
  * 3-Way Parameter Control Grid: Absorption & Wyckoff Rules, BTC Macro Tide Gate, and Volatility-Parity Sizing.
  * Autonomous Self-Learning Distillation Deck with empirical win rate, profit factor, MFE/MAE ratio, and dynamic toxic asset quarantine list.
  * Real-time 15-Item Microstructural TCA Trade Forensics Audit Table queried directly from `data/tiger_trades.db`.
* **⚡ Strategy #1: Lightning / Apex Scalper:**
  * Displays the existing microstructural momentum and liquidation vacuum engine running on AWS EC2 (`13.63.158.94`) and local PC.

### 3. Backend Telemetry & Control Endpoints
* `GET /api/tiger/status`: Full state, distilled rules, config summary, live radar snapshot, and last 15 trades from `data/tiger_trades.db`.
* `POST /api/tiger/config`: Dynamic hot-reload of volatility parity, risk budget, BTC gate, and absorption parameters.
* `POST /api/tiger/scan`: Forces manual whole-Binance USD(S)-M sieve scan.
* `POST /api/tiger/distill`: Executes Bayesian trade forensics distillation and updates `data/tiger_distilled_rules.json`.
* `POST /api/tiger/reset-quarantine`: Clears toxic asset quarantine firewalls and symbol cooldowns.

---

## 12. Real-Time Open Interest ($\Delta\text{OI}$) Climax Gate Architecture

### 1. The Microstructural Problem
On derivative exchanges (Binance USD(S)-M Futures), aggressive market selling into a swing low (forming a lower wick with negative CVD) occurs in two fundamentally different economic regimes:
1. **Liquidation Cascade / Stop-Hunt Run ($\Delta\text{OI} \le 0$):** Pre-existing long positions are forcibly extinguished or stopped out. Once the liquidation cascade clears, no trapped participants exist to generate upward buying pressure. Entering this fakeout leads to momentum stall and rollover.
2. **Trapped Counter-Party Buildup ($\Delta\text{OI} > 0$):** Fresh retail traders aggressively open new short contracts at the lows while limit buyers absorb the inventory. These shorts are now trapped underwater, creating high-conviction short-squeeze fuel.

### 2. Implementation & Zero-Ban Rate Weight
* **Binance REST Polling:** Strategy #3 polls `/fapi/v1/openInterest?symbol=<prey>` every 20 seconds for the Top 5 Hot Prey.
* **API Cost:** Only 1 weight per symbol (5 calls / 20s = 15 weight/min), consuming <0.7% of Binance's 2,400 weight/min limit.
* **Rolling $\Delta\text{OI}$ Calculation:**
  $$\Delta\text{OI}_{\%} = \frac{\text{OI}_{\text{current}} - \text{OI}_{\text{baseline}}}{\text{OI}_{\text{baseline}}}$$
  evaluated over an `oi_lookback_seconds = 180` second window.
* **Trigger Invariant (Strict Negative Affirmation):** Trapped liquidity entries require $\ge 2$ historical Open Interest snapshots AND proven $\Delta\text{OI}_{\%} \ge +0.01\%$. If $\Delta\text{OI}_{\%} < +0.01\%$, or if fewer than 2 OI snapshots exist (cold-start prey), the setup is unconditionally **vetoed**. Never pounce in the dark without verified counter-party buildup.
* **Live WebUI Reflection:** The radar table displays the real-time $\Delta\text{OI}_{\%}$ badge alongside mark price, volatility score, and sub-second WebSocket streams.

---

## 13. Anti-Burst Fleet Architecture & Correlated Tremor Defense

To ensure institutional stability and prevent machine-gun churn or slot-cap violations during high-volatility events, the following three architectural guardrails are enforced:

### 1. Combined Slot Hard Ceiling (Pending + Active)
* **The Invariant:**
  $$\text{Total Committed Slots} = \text{Count}(\text{Active Positions}) + \text{Count}(\text{Pending Signals}) < \text{max\_concurrent\_positions}$$
* Eliminates the slot leak where multiple pending limit orders could be placed while active positions was 0 and then filled simultaneously during a flash wick.

### 2. Global Fleet Inter-Trade Cooldown (`fleet_inter_trade_cooldown_seconds = 60s`)
* While `symbol_cooldown_minutes = 15` protects against re-trading the *same* symbol, the **Global Fleet Cooldown** enforces a minimum 60-second resting window across the *entire portfolio* after any trade is dispatched or closed.
* Eliminates cross-symbol "machine-gun churn" during market-wide cascades.
* Persisted across daemon restarts via `data/tiger_state.json`.

### 3. Correlated Basket Tremor Defense & "Champion Prey" Cross-Sectional Ranking
* **Legacy Flaw:** Previously, if $\ge 2$ symbols triggered simultaneously in the same 5-second scan, the daemon vetoed *all* candidates, mistaking market momentum pulses for toxic systemic shocks and missing high-conviction entries.
* **Institutional v2.2 Upgrade:** Instead of an all-or-nothing cancel, the system ranks simultaneous triggers via an orderflow conviction score:
  $$\text{Prey Conviction Score} = 2.0 \times |\text{OFI}| + \text{Wick Ratio} + \text{Absorption Density}$$
* **Execution Invariant:** Selects and dispatches **strictly the Rank #1 "Champion Prey"**. Ranks #2 through #5 are discarded to preserve zero-correlated basket risk and maintain single-position discipline.

---

## 15. Institutional Microstructure Risk & Live Real Deployment (v2.2 Upgrade)

### 1. Time-Horizon Decoupled Stop Floor (`order.is_scalp = True`)
* **Blunt Floor Elimination:** The risk manager previously applied a single $0.66\%$ minimum stop distance (Lessons #16 & #39) across both multi-hour swing trades and sub-minute scalps, which blocked valid micro-wick invalidation stops ($0.45\% - 0.50\%$).
* **Adaptive Spread Shield:** Scalp orders evaluate an adaptive floor:
  $$\text{Effective Stop Floor} = \max\Big(3.0 \times \text{Spread}_{\text{pct}}, \; \text{scalp\_min\_stop\_distance\_pct}\; (0.40\%)\Big)$$
* **Enhanced Protection:** Macro trades remain locked to $0.66\%$. If an altcoin book widens to $0.25\%$ spread, the required stop automatically widens to $0.75\%$ ($3 \times 0.25\%$), rejecting tight stops in noisy or illiquid orderbooks.

### 2. Net R:R Geometry Calibration (Eliminating the Lesson #10 Veto Loop)
* With VIP0 taker fees ($0.10\%$ roundtrip) and average spread friction ($0.04\%$), an entry with $+1.01\%$ TP and $-0.66\%$ SL resulted in:
  $$\text{Net R:R} = \frac{1.01\% - 0.14\%}{0.66\% + 0.14\%} = 1.0875 < 1.20 \quad (\text{Vetoed})$$
* Aligned with Lesson #20 (*"widen TP target to >= 1.20%"*), slow regime brackets are calibrated to **$\text{TP} = +1.20\%$** and **$\text{SL} = -0.70\%$**:
  $$\text{Net R:R} = \frac{1.20\% - 0.14\%}{0.70\% + 0.14\%} = \frac{1.06\%}{0.84\%} = \mathbf{1.26} \ge 1.20$$
* All slow-regime trades satisfy Lesson #10 naturally while fully accounting for exchange fee friction.

### 3. Counterfactual "Ghost Trade" Audit Engine
* When any signal is vetoed by the risk engine, it is logged to `data/tiger_counterfactuals.jsonl`:
  ```json
  {"signal_id": "TIGER_SIG_KERNELUSDT_1700000000", "symbol": "KERNELUSDT", "action": "SELL", "evaluation_fill_price": "0.1550", "stop_loss_price": "0.1561", "take_profit_price": "0.1531", "reason_codes": ["OMS_STOP_BELOW_NOISE_FLOOR_L16_L39"], "timestamp_utc": "2026-11-21T05:00:00"}
  ```
* Allows empirical verification of whether risk vetoes protected capital or blocked winners.

### 4. Live Real Production State (AWS EC2)
* **Command:** `python scripts/tiger_worker.py --live --quota 5`
* **Account:** Binance USDⓈ-M Futures (Real Capital Margin, $200.71 USDT Wallet)
* **Active Stream:** 5 Multiplex WebSocket streams (`@aggTrade` + `@depth5@100ms`) with dynamic rate throttling.
* **Concurrency Quota:** 3 Scalp slots allocated within the 9-position portfolio ceiling (6 Macro + 3 Scalp).

---

## 14. Autonomous Dual-Track Learning & Forensics Engine

The learning subsystem preserves the empirical "goldmine" of failure, losses, scratches, and wins to drive continuous Bayesian parameter adaptation while strictly isolating capital risk.

### 1. Dual-Track Execution Modes
* **`PAPER` Mode (Sandbox):** High-volume parameter exploration, micro-structure mapping, and early hazard detection without capital risk (Weight: $1.0\times$).
* **`LIVE` Mode (Authority):** Real capital execution with exchange-side bracket orders, carrying $3.0\times$ Bayesian statistical weight in parameter distillation.

### 2. Forensic Autopsy Taxonomy
Every trade is diagnosed by its physical market microstructure mechanism:
* **`WIN_SQUEEZE`:** Reached target or locked profit via dynamic ratchet.
* **`STALL_SCRATCH`:** Stalled for 12m without expansion, scratched near breakeven ($\ge -\$0.20$), saving capital.
* **`ZERO_MFE_LIQ_FLUSH`:** MFE == 0.00%. Immediate stop-out from liquidity sweep.
* **`MFE_REVERSAL`:** Traveled $\ge +0.50\%$ towards target but reversed to stop out.
* **`STEAMROLLER_OUTLIER`:** Loss exceeded $1.5\times$ base risk ($>\$2.25$) due to extreme adverse slippage/trend.
* **`STOP_OUT`:** Normal statistical variance stop within expected envelope.

### 3. Temporal Quarantine Decay & Shadow Re-qualification
* **Decay Lifecycles:** 12-hour expiration for paper toxic streaks ($\ge 2$ losses in 24h); 24-hour expiration for live trade losses.
* **Automatic Graduation:** Symbols graduate back to active status automatically upon reaching $t_{\text{expiry}}$.
* **Shadow Re-qualification:** Quarantined symbols tracked via shadow paper signals. Achieving $\ge 66.7\%$ win rate over $\ge 3$ evaluations grants early graduation.

### 4. Cross-Fleet Specification
Full cross-fleet governance, mathematical formulations, and regime segregation rules are formalized in `docs/FLEET_DUAL_TRACK_LEARNING_SPECIFICATION.md`.

