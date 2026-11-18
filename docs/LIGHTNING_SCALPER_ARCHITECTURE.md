# Kronos Lightning Scalper — Quantitative Architecture & Distillation Manual

> **Institutional Quantitative Trading Standard**  
> **Status:** Production Deployed  
> **Cockpit View:** [http://localhost:7070/scalper](http://localhost:7070/scalper)  
> **AWS Production Node:** `13.63.158.94` (Stockholm `eu-north-1`, `kronos-headless.service`)  
> **Last Verification:** ASVL 100% Passed (76 Local PC Tests / 21 Remote AWS Tests)

---

## 1. Executive Summary & Design Paradigm

The **Kronos Lightning Scalper** is an autonomous high-frequency microstructural execution engine designed to operate alongside the slower **Macro Swing Trajectory Engine** without financial or operational crosstalk.

While Macro Swing operates on 1h/15m multi-hour neural trajectories and macro breadths with $200+ capital, the Lightning Scalper operates strictly on sub-second order book imbalances, liquidation vacuum wicks, and lead-lag velocity shocks with **$20.00 ringfenced isolated margin (4x leverage)**.

### Core Architecture Invariant: Asymmetric Compute
```
+-----------------------------------------------------------------------------------+
|                        LOCAL PC RESEARCH & LEARNING NODE                          |
|  - Full GPU / Multi-core CPU                                                      |
|  - 46-Item Microstructural TCA Decomposition (MFE, MAE, Realization Tax Drag)     |
|  - Root-Cause Classification (CONVICTION_WIN, TOXIC_LUCKY_WIN, FRICTION_BLEED)    |
|  - Bayesian Hyperparameter Recalibration (ATR multipliers, fee hurdles)           |
|  - Toxic Symbol Quarantine Identification                                         |
|  - Distillation Engine -> generates data/scalper_distilled_rules.json              |
+-----------------------------------------------------------------------------------+
                                          |
                      Safe SCP Sync       | (Zero Downtime / Zero Restarts)
                                          v
+-----------------------------------------------------------------------------------+
|                           AWS EC2 EXECUTION NODE                                  |
|  - Micro instance (t3.micro, 1GB RAM)                                             |
|  - Ultra-Lean Memory: <105 MB RAM (Strictly NO PyTorch, NO heavy ML loops)        |
|  - Sub-50ms execution latency to Binance European matching engines                |
|  - Hot-reloads data/scalper_config.json & data/scalper_distilled_rules.json         |
|  - Single-Slot (N=1) lightning execution & algo bracket enforcement              |
|  - Records closed scalp telemetry to lessons.db for local sync back               |
+-----------------------------------------------------------------------------------+
```

---

## 2. Whole-Binance Universal Scanning (300+ Pairs)

Rather than limiting observation to a static list of 10-15 coins, the Lightning Scalper monitors the **entire Binance USDT-M Perpetual universe** (300+ trading pairs):

1. **Array Streams Ingestion:** Connects to aggregated Binance array streams:
   - `!forceOrder@arr`: Broadcasts real-time cascading liquidation events across all perpetual contracts.
   - `!miniTicker@arr`: Delivers sub-second price velocity, 24-hour volume, and high/low ranges for every contract.
2. **Pre-Filter Liquidity Sieve:**
   - Filters out any contract with $< \$50,000,000$ 24-hour turnover to eliminate illiquid shitcoins with wide bid-ask spreads.
   - Enforces maximum spread filter $\le 2.5\text{ bps}$.
3. **Dynamic Post-Exit Quarantine Reflex (Lesson #22):**
   - If a coin (e.g. BNB) was exited or closed (either manually by user or by exchange algo bracket), a **mandatory 900-second (15-minute) quarantine** is instantly placed on that symbol.
   - Prevents the bot from re-shorting the local bottom or re-buying into exhausted momentum.

---

## 3. The Three High-Frequency Alpha Strategies

### Strategy 1: Liquidation Vacuum Rebound
- **Quantitative Thesis:** When large cascading liquidations trigger on Binance, aggressive taker liquidations consume all available order book depth in milliseconds, creating an artificial price displacement ("vacuum wick") with zero natural trading counterparty. Once liquidations clear, natural mean-reversion occurs rapidly.
- **Entry Rules:**
  - Aggregated liquidation burst $\ge \$75,000\text{ USD}$ within a 3-second window.
  - Rejection wick ratio $\ge 0.40$ (candle leaves a 40%+ wick within the minute).
  - Target snapback: $+1.10\%$ net.

### Strategy 2: Cross-Asset Lead-Lag Delta
- **Quantitative Thesis:** Bitcoin (BTC) and Ethereum (ETH) lead institutional directional flow. When BTC undergoes a violent 3-second impulse spike ($>0.45\%$), high-beta altcoins (e.g., SOL, DOGE, NEAR, AVAX) often lag by 1.5 to 3.5 seconds before their order books catch up.
- **Entry Rules:**
  - BTC 3-second velocity spike $\ge 0.45\%$.
  - Altcoin price lag delta $\ge 0.35\%$ behind expected beta reaction.
  - Maximum allowable transmission latency $\le 3,500\text{ ms}$.

### Strategy 3: Stoikov Micro-Price & Iceberg Absorption
- **Quantitative Thesis:** Based on Avellaneda-Stoikov market microstructure. When large institutional iceberg orders absorb aggressive flow, the Order Book Imbalance (OBI) skews heavily ($|\text{OBI}| \ge 0.45$) while the micro-price diverges from the top-of-book mid-price.
- **Entry Rules:**
  - Order Book Imbalance $|\text{OBI}| \ge 0.45$ across top-10 book levels.
  - Micro-price skew $\ge 0.25\text{ bps}$.
  - Expected mean-reversion rebound $\ge 0.95\%$.

---

## 4. Execution Rules & Dynamic Trailing

| Parameter | Institutional Calibrated Value | Quantitative Justification |
| :--- | :--- | :--- |
| **Net Take-Profit Snapback** | `+1.10%` to `+1.25%` | Ensures positive expectancy after Binance taker fees ($0.08\%$ round-trip) and slippage ($0.02\%$). |
| **Two-Tier Profit Ratchet** | `+0.80%` Cushion Trigger | Prevents premature breakeven choking (Lesson #20). Once gain reaches $+0.80\%$, stop moves to entry $+0.25\%$ profit cushion. |
| **Hard Stop-Loss Floor** | `-0.70%` | Mathematical ceiling protecting isolated capital; enforces minimum $1.60\times$ Reward-to-Risk ratio. |
| **Max Hold Duration** | `600 seconds (10 min)` | Momentum decay horizon. If trade does not reach target within 10 minutes, market flattens immediately. |
| **Execution Rails** | `Maker-First Post-Only` | Minimizes fees by capturing maker rebates where possible; falls back to immediate taker on high-velocity wicks. |

---

## 5. Ringfenced Capital & Risk Guardrails

- **Isolated Allocation:** $\$20.00\text{ USDT}$ maximum initial margin per scalp.
- **Leverage:** Strictly capped at $4\times$ (Notional: $\$80.00$).
- **Single-Slot Concurrency:** Strictly $N=1$. Only one scalp position can be active across the entire account at any millisecond.
- **Daily Loss Circuit Breaker:** $\$3.00\text{ USD}$ max daily loss (halts scalping for 24 hours if hit).
- **Consecutive Loss Quarantine:** 5 consecutive stop-outs trigger an automated 1-hour cooling halt to eliminate tilt and adverse regime clustering.
- **Toxic Symbol Quarantine:** Automated exclusion of any symbol with persistent negative net returns or excessive realization tax.

---

## 6. Empirical Backtest Proof: Naive vs Institutional

Comparative empirical backtest executed across **4,000 live Binance 1-minute bars** (`SOL`, `ETH`, `BTC`, `DOGE`):

| Metric | Model A: Naive Unfiltered | Model A: Naive + Sieve | Model B: Institutional Upgrade |
| :--- | :--- | :--- | :--- |
| **Total Trades Executed** | 193 trades (Over-trading) | 34 trades | **34 trades (Selective)** |
| **Win Rate** | 63.7% | 67.6% | **76.5%** |
| **Gross PnL** | $+\$1.89$ | $+\$0.55$ | **$+\$2.67$** |
| **Binance Fees Incurred** | **$-\$20.07$ (Bleed)** | $-\$3.53$ | **$-\$2.36$ (88% Fee Reduction)** |
| **Net Realized PnL** | **$-\$18.18$ (-90.9% Account Destroyed)** | $-\$2.98$ (-14.9%) | **+$0.31 (+1.6% Net Gain)** |
| **Profit Factor** | $0.21\times$ | $0.54\times$ | **$1.86\times$** |
| **Choked at Breakeven** | $0\%$ | $23.5\%$ (Premature choking) | **$0.0\%$ (Eliminated via +0.80% cushion)** |

---

## 7. The PC-to-AWS Learning & Distillation Pipeline

### The Problem Solved
Running deep trade analytics, 46-item TCA regressions, and model training on AWS EC2 spikes memory past the 1GB t3.micro ceiling and introduces latency jitter to live order routing.

### The Solution: Asymmetric Distillation
1. **Local PC Learning Engine:**
   - Ingests closed scalp records and calculates 46-item TCA metrics: MFE, MAE, Realization Tax Drag bps, Holding Duration, and Root-Cause Diagnosis.
   - Categorizes outcomes into:
     - `CONVICTION_WIN`: Clean execution and timing.
     - `TOXIC_LUCKY_WIN`: Trade won after deep adverse drawdown ($|\text{MAE}| > 1.5 \times \text{MFE}$). Elevates win probability gate.
     - `FRICTION_BLEED`: Direction correct, but net PnL eaten by fees. Elevates take-profit hurdle.
     - `STOP_INSIDE_NOISE`: Stopped within 1.0x ATR noise. Recalibrates ATR stop multiplier from $1.0\times$ to $1.25\times$.
   - Generates distilled decision matrix: `data/scalper_distilled_rules.json` and updates `data/scalper_config.json`.
2. **AWS EC2 Synchronization:**
   - Transfers `scalper_distilled_rules.json` and `scalper_config.json` via secure SCP.
   - The AWS headless worker hot-reloads the updated configuration on its 5-second loop.
   - **Zero downtime, zero service restarts, zero disruption to open positions.**

### CLI Usage
```bash
# Run local learning audit and Bayesian calibration
python scripts/distill_scalper_learning.py

# Run local learning audit and sync distilled decision matrix to AWS EC2
python scripts/distill_scalper_learning.py --sync-aws
```

### Web UI Operation
1. Navigate to `http://localhost:7070/scalper`.
2. In the **Local PC Quantitative Learning & AWS Distillation Deck**:
   - Click `🧠 Run PC Learning Audit & Distill to AWS` to execute learning and sync in one click.
   - View live TCA forensics in the **Microstructural 46-Item TCA Forensics Table**.

---

## 8. Tsunami Storm Adaptive Protocol & High-Wave Governance

The Lightning Scalper is integrated with the **Tsunami Storm Adaptive Protocol** to prevent toxic churn during black swan news events or violent liquidation waves:

1. **Phase 1 Shock Pause (First 15 Minutes):**
   - When a high wave is detected (BTC 5m velocity $\ge 2\%$, 5m range $\ge 3\%$, or macroeconomic catalyst blackout), all scalp signals are **instantly vetoed** with `VETO: Storm Protocol Phase 1 (Shock Pause active)`.
   - Prevents the high-frequency engine from attempting to catch falling knives during the violent initial seconds of a liquidation cascade.
2. **Phase 2 Focused Caution (Minutes 15 to 60):**
   - Fleet capacity is clamped to strictly **1 Macro Position and 1 Scalp Position** across the entire account.
   - Scalper minimum conviction hurdle elevates from standard $65.0\%$ to **$\ge 75.0\%$**. Only setups with overwhelming microstructural order book skew and liquidity absorption are permitted.
3. **Exchange-Native Mark-Price Anti-Wick Protection:**
   - All conditional Stop-Loss orders dispatched to Binance Perpetual exchange enforce `workingType: "MARK_PRICE"`.
   - Prevents localized flash crashes or single-exchange scam wicks from hunting isolated stops, while Take-Profit orders remain on `CONTRACT_PRICE` to trigger instantly on favorable wicks.
4. **Post-Exit Symbol Quarantine Synergy (Lesson #22):**
   - When an active scalp position exits during storm conditions, the symbol is quarantined for a minimum of 15 minutes (900 seconds), eliminating destructive churn or emotional revenge re-entry.
5. **Phase 3 Calm Water Auto-Recovery:**
   - After 60 minutes, if volatility and breadth have normalized, the engine autonomously transitions back to `NORMAL_WATERS` with zero service restarts.

For full state machine diagrams, trigger telemetry, and empirical stress tests, consult [docs/TSUNAMI_STORM_ADAPTIVE_PROTOCOL.md](TSUNAMI_STORM_ADAPTIVE_PROTOCOL.md).
