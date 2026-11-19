# Specialized Advisory Consultant & Tri-Perspective Adversarial Conviction Ratio (ACR)

This document specifies the architecture, mathematical formulations, and operational protocols of the **Kronos Specialized Advisory Consultant**, the **Tri-Perspective Adversarial Conviction Ratio ($ACR$)**, the **3-Position Fleet Concurrency Cap (2 Macro + 1 Scalp)**, the **Sweetspot Trade Expiration Engine**, and the **50-Trade Session Quota Circuit Breaker**.

---

## 1. Executive Summary & Architecture

High-frequency algorithmic execution engines cannot afford the multi-second latency, non-deterministic reasoning, or high API credit burn associated with direct LLM calls during real-time order dispatch. Conversely, rigid single-indicator rule engines often lack multi-perspective risk awareness—failing to cross-examine whether a technically bullish signal is firing straight into an overhead institutional resistance ceiling or carrying severe friction drag.

The **Specialized Advisory Consultant** solves this paradox by decoupling **deliberation and audit** from **execution**:

```
+-----------------------------------------------------------------------------------+
|                        KRONOS 24/7 EXECUTION ENGINE (AWS EC2)                     |
|                                                                                   |
|   +-----------------------+   +-----------------------+   +-------------------+   |
|   |  Macro Strategy #1    |   |  Macro Strategy #2    |   |  Lightning Scalp  |   |
|   |  (e.g., SOL Swing)    |   |  (e.g., ETH Breakout) |   |  (e.g., PEPE OB)  |   |
|   +-----------+-----------+   +-----------+-----------+   +---------+---------+   |
|               |                           |                         |             |
|               +---------------------------+-------------------------+             |
|                                           |                                       |
|                                           v                                       |
|                  [CONCURRENCY GOVERNOR: MAX 3 TRADES (2 Macro + 1 Scalp)]         |
|                  [SESSION QUOTA GUARD: MAX 50 TRADES -> EMAIL ALERT]              |
+-------------------------------------------+---------------------------------------+
                                            ^
                                            | Asynchronous / Read-Only Audit
+-------------------------------------------+---------------------------------------+
|                    SPECIALIZED ADVISORY CONSULTANT & AUDIT SUITE                   |
|                                                                                   |
|   +---------------------------------------------------------------------------+   |
|   |  Tri-Perspective Adversarial Conviction Ratio (ACR):                      |   |
|   |    ACR = [ C_bull * (1 - P_bear) ] / [ 1 + R_drag ]                       |   |
|   |                                                                           |   |
|   |    - Perspective 1 (Bullish Alpha): OBI, Micro-Price Skew, Momentum       |   |
|   |    - Perspective 2 (Bearish Hazard): Volume Profile POC Ceilings, Funding |   |
|   |    - Perspective 3 (Cost & Friction): VIP0 Taker Fees, Spread, Slippage   |   |
|   +---------------------------------------------------------------------------+   |
|                                           |                                       |
|                                           v                                       |
|   +---------------------------------------------------------------------------+   |
|   |  Autonomous Post-Trade Reflection & Alpha Settlement:                     |   |
|   |    alpha = R_trade - R_BTC                                                |   |
|   |    Sweetspot Duration Compliance Audit (10-15m Scalp, 90m Macro)          |   |
|   |    Empirical Lesson Generation -> data/consultant_lessons.jsonl           |   |
|   +---------------------------------------------------------------------------+   |
+-----------------------------------------------------------------------------------+
```

### Key Principles
1. **Advisor, Not Commander (Zero Live Battle Authority):** The consultant is strictly an assessment, intelligence, and post-battle audit engine. It has **no right or command over live order dispatch**, cannot modify or cancel active orders, and never intercepts live sub-second order routing. Active battle command belongs 100% to the production execution engines (`ApexScalperEngine`, `Orchestrator`) on AWS.
2. **Zero Execution Latency Impact:** Because the consultant operates out-of-band as an asynchronous deliberation layer, real-time microsecond order execution on AWS remains completely unaffected.
3. **Zero IEEE-754 Float Math:** All mathematical calculations, probability products, fee drags, and alpha metrics are computed using Python `decimal.Decimal`.
4. **Deterministic Formulations:** Conceptual multi-agent debates (Bull vs. Bear vs. Risk) are distilled into closed-form mathematical equations rather than prompt-based LLM chats.

---

## 2. Forensic Evaluation: TradingAgents vs. Kronos

Following our evaluation of the open-source repository `https://github.com/BinqQarenYu/TradingAgents.git`, Kronos distilled its theoretical strengths while rejecting its production liabilities:

| Dimension | TradingAgents Architecture | Kronos Advisory Consultant |
| :--- | :--- | :--- |
| **Execution Reality** | No order routing, no atomic brackets, no exchange connectivity. | Production Binance USDⓈ-M gateway with Mark-Price stop brackets and atomic state machines. |
| **Computational Latency** | 10–15 LLM API calls per bar (~30–60s latency). | Sub-millisecond deterministic evaluation (`< 1ms`) via local pure-Python math. |
| **Financial Mathematics** | IEEE 754 standard floats (subject to precision drift). | Strict `decimal.Decimal` zero-float accounting across all ratios. |
| **Operational Costs** | High credit burning; rapid exhaustion of LLM API quotas. | Zero remote API cost during active trading; 100% local calculation. |
| **Dialectic Synthesis** | Verbose text conversations between Bull and Bear LLM agents. | Mathematical synthesis: Bull Conviction penalised by Bear Resistance and Friction Drag ($ACR$). |
| **Post-Trade Learning** | Unstructured commentary. | Quantitative alpha benchmark ($\alpha = R_{\text{trade}} - R_{\text{BTC}}$) and structured empirical lessons. |

---

## 3. Mathematical Specification: Adversarial Conviction Ratio ($ACR$)

To formalize multi-perspective deliberation without LLM latency, the consultant evaluates candidate trades using the **Tri-Perspective Adversarial Conviction Ratio ($ACR$)**:

$$ACR = \frac{C_{\text{bull}} \times (1 - P_{\text{bear}})}{1 + R_{\text{drag}}}$$

Where:
* $C_{\text{bull}} \in [0.0, 1.0]$ is the **Bullish Alpha Conviction**.
* $P_{\text{bear}} \in [0.0, 1.0]$ is the **Bearish Hazard & Structural Resistance Penalty**.
* $R_{\text{drag}} \ge 0.0$ is the **Frictional Drag Factor** (exchange fees, spread, and adverse execution slippage).

### Component Breakdown

#### 1. Bullish Alpha Conviction ($C_{\text{bull}}$)
Synthesizes order book imbalance ($OBI$), Stoikov volume-weighted micro-price skew, and directional momentum:

$$C_{\text{bull}} = 0.50 + 0.35 \times OBI + 0.15 \times \text{clamp}\left(\frac{P_{\text{micro}} - P_{\text{mid}}}{\text{spread}}, -1.0, 1.0\right)$$

#### 2. Bearish Hazard Penalty ($P_{\text{bear}}$)
Models structural obstacles and adversarial forces that cap upside potential:
* **Volume Profile POC Proximity:** If the current market price is within $0.35\%$ beneath the previous UTC day's Point of Control ($pPOC$), $P_{\text{bear}}$ incurs a $+0.50$ penalty (identifying that the trade is firing straight into heavy institutional resting limit orders).
* **High-Volume Node (HVN) Chop:** If price is stuck inside an HVN consolidation zone, $P_{\text{bear}}$ incurs a $+0.25$ penalty.
* **Negative Funding Drag:** If 8-hour perpetual funding carry opposes the trade direction, $P_{\text{bear}}$ scales upward proportionally.

$$P_{\text{bear}} = \min(1.0, \sum \text{penalties})$$

#### 3. Frictional Drag Factor ($R_{\text{drag}}$)
Measures the barrier of entry created by round-trip transaction costs:

$$R_{\text{drag}} = \frac{\text{Round-Trip Taker Fee} + \text{Half-Spread} + \text{Adverse Slippage Buffer}}{\text{Expected ATR Excursion}}$$

In standard VIP0 Binance USDⓈ-M perpetual trading ($0.05\%$ taker fee each way = $0.10\%$ round trip):

$$R_{\text{drag}} = \frac{0.0010 + 0.0002}{\max(0.0030, ATR\%)} \approx 0.20 \text{ to } 0.40$$

### Decision Calibration Gates
* **$ACR \ge 0.50$:** `RECOMMEND_LONG` (Strong alpha conviction, clear overhead path, friction is negligible).
* **$ACR \le -0.50$:** `RECOMMEND_SHORT` (Short-side consensus).
* **$-0.50 < ACR < 0.50$:** `AVOID` or `ADVERSARIAL_VETO` (Market is neutral, resistance is overhead, or friction drag eliminates positive mathematical expectancy).

---

## 4. Autonomous Post-Trade Reflection & Alpha Settlement

Every closed trade is automatically audited by the Advisory Consultant upon receipt of execution fill telemetry:

### 1. Benchmark-Relative Alpha ($\alpha$)
Raw PnL is decomposed relative to the Bitcoin benchmark over the identical holding period:

$$\alpha = R_{\text{trade}} - R_{\text{BTC}}$$

* If $\alpha > 0$: The strategy captured true idiosyncratic alpha.
* If $\alpha \le 0$ despite positive dollar PnL: The trade was merely carried by broad market beta; edge is non-existent.

### 2. Sweetspot Expiration Audit
The holding duration is checked against the empirical sweetspot ($10\text{--}15\text{m}$ for scalps, $\le 90\text{m}$ for macro). Trades that lingered beyond the sweetspot are flagged for temporal bleed.

### 3. Empirical Lesson Generation
The consultant synthesizes the outcome into a concise, deterministic 2-sentence lesson, saved to `data/consultant_lessons.jsonl`:

```json
{
  "timestamp": "2026-11-19T07:22:15.000Z",
  "symbol": "SOLUSDT",
  "direction": "LONG",
  "net_pnl_pct": "-0.0042",
  "btc_benchmark_return": "0.0012",
  "alpha_pct": "-0.0054",
  "holding_seconds": 920,
  "sweetspot_compliant": false,
  "lesson": "Trade suffered negative alpha (-0.54%) due to overhead POC resistance ceiling. Duration exceeded optimal 720s scalp sweetspot by 200s."
}
```

---

## 5. Portfolio Concurrency Allocation: 3-Position Cap

To prevent margin over-commitment and contain portfolio volatility, Kronos enforces a strict **fleet-wide concurrency cap of 3 open positions**:

$$\text{Total Open Positions} = N_{\text{macro}} + N_{\text{scalp}} \le 3$$

### Slot Distribution Invariant
* **Macro Trades:** Maximum **2 concurrent positions** ($N_{\text{macro}} \le 2$).
* **Lightning Scalp Trades:** Maximum **1 concurrent position** ($N_{\text{scalp}} \le 1$).

### Capital & Slot Arbitration
1. If 2 Macro positions are open and another Macro signal arrives, it is **vetoed** (`CAPACITY_REACHED_MACRO`).
2. If 1 Lightning Scalp is active and another Scalp opportunity triggers, it is **vetoed** (`CAPACITY_REACHED_SCALP`).
3. Total active portfolio margin is capped at **$\le 4.5\%$ of account equity** ($3 \times 1.5\%$ per-trade risk budget), guaranteeing immunity against multi-position liquidation cascades.

---

## 6. 50-Trade Session Quota & Automated Email Alert

To protect against compounding drawdown or catastrophic execution loops during unexpected regime shifts, the engine enforces a strict **50-Trade Session Quota**:

```python
# Session Quota Guard (src/quant/apex_scalper.py & orchestrator.py)
MAX_SESSION_TRADES = 50

if session_trades_count >= MAX_SESSION_TRADES:
    live_trading_enabled = False
    dispatch_quota_email_alert(summary_stats)
    logger.critical("SESSION TRADE QUOTA (50) REACHED - TRADING AUTOMATICALLY PAUSED")
```

### Protocol on Reaching 50 Trades:
1. **Immediate Entry Halt:** All scanning daemons on both AWS and Local PC transition `live_trading_enabled` to `false`. No new orders will be submitted.
2. **Bracket Management Unaffected:** Existing open positions remain fully managed by their exchange-native Take-Profit and Stop-Loss brackets and temporal sweeper.
3. **Automated SMTP Email Dispatch:** Dispatches a structured institutional session debrief directly to the operator's registered email:
   * Total Session PnL (Gross and Net after VIP0 fees).
   * Win / Loss tally and win rate percentage.
   * Average holding duration vs. sweetspot compliance rate.
   * Complete trade manifest and consultant alpha audit summary.

---

## 7. Sweetspot Trade Expirations & Stagnation Defense

Capital must not be held in stagnant, non-performing trades. Capital recycling velocity is prioritized:

| Parameter | Lightning Scalper | Macro Bot |
| :--- | :--- | :--- |
| **Minimum Holding Time** | 60 seconds (prevents fee churn on wicks) | 5 minutes |
| **Stagnation Cutoff Window** | **8 minutes (480 seconds)** | **90 minutes (5,400 seconds)** |
| **Stagnation PnL Threshold** | Unrealized PnL $< +0.15\%$ | Unrealized PnL $< +0.30\%$ |
| **Optimal Sweetspot Target** | **10 to 12 minutes (600–720s)** | **60 to 90 minutes** |
| **Hard Temporal Ceiling** | **15 minutes (900 seconds)** | **4 hours (14,400 seconds)** |
| **Exit Execution Type** | Atomic Taker Market Close | Reduced Limit / Market Sweeper |

### Operational Rationale
* High-frequency scalping alpha decays exponentially after 10–12 minutes. If a scalp has not hit TP within 8 minutes and is hovering near breakeven, it represents dead risk capital and is terminated immediately.
* Macro trades that fail to establish directional velocity within 90 minutes are typically trapped in mean-reverting chop zones; liquidating frees margin for high-conviction entries.

---

## 8. CLI Operational & Verification Commands

### 1. Run Live Multi-Perspective Consultant Audit
To audit current market conditions for any asset using the consultant engine:
```bash
# Audit specific symbol
python scripts/run_consultant_assessment.py --symbol SOLUSDT

# Audit full core universe
python scripts/run_consultant_assessment.py --all
```

### 2. Verify Consultant Math & Unit Tests
```bash
python -m pytest tests/test_advisory_consultant.py -v
```

### 3. Verify System Smoke Tests
```bash
python -m pytest tests/test_smoke.py -q
```
