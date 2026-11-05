# Institutional Incident Post-Mortem & Quant Lessons Learned

**Incident Reference:** `INC-2026-11-05-LOOKAHEAD-FLYING-EQUITY`  
**Severity:** CRITICAL SIMULATION ARTIFACT (Zero Capital Loss — Paper Trading Mode)  
**System Component:** `webui/app.py`, `src/quant/binance_execution.py`, `src/quant/kev_risk_arbiter.py`  
**Status:** RESOLVED & PERMANENTLY REMEDIATED ([Commit `fb59a6a`](https://github.com/bingkltech/Kronos/commit/fb59a6a))  
**Registered Lesson:** Active Lesson #11 in [`data/lessons.db`](file:///F:/012D_TRADE/Kronos/data/lessons.db)

---

## 1. Incident Overview & Symptom Profile

### The Symptom
Within ~24 hours of autonomous background paper trading, the simulated account equity displayed:
$$\$200.00 \text{ USDT} \longrightarrow \$949,618.31 \text{ USDT} \quad (+474,709\%)$$
- **Total Trades:** 446
- **Wins vs Losses:** 419 Wins vs 23 Losses (**93.9% Win Rate**)
- **Profit Factor:** **19,827.75x**
- **Average Trade Duration:** **63 seconds**

### The Intuition Check
In institutional quantitative finance, any strategy reporting a **>90% win rate** on 1-minute trades with a 1.6:1 Reward-to-Risk ratio and 19,000x profit factor is **empirically impossible**. Real-world high-frequency directional alpha typically operates between **52% and 58% win rate** with profit factors between **1.35x and 1.85x**. The result was an artificial simulation loop.

---

## 2. Root Cause Analysis (The 4 Compounding Faults)

```
+-----------------------------------------------------------------------------------------------+
|                                      THE INCIDENT PIPELINE                                    |
+-----------------------------------------------------------------------------------------------+
| 1. Stale Lookback CSV (Oct 31)   --> Kronos generates BUY ETH @ $2,247.79                    |
|                                      Dynamic Take-Profit set @ $2,283.07                      |
|                                                                                               |
| 2. Execution Engine              --> Assumes instant fill at stale $2,247.79                  |
|                                                                                               |
| 3. 60 Seconds Later              --> Orchestrator queries LIVE Binance API                    |
|                                      Live ETH spot price is $2,390.46                         |
|                                                                                               |
| 4. Bracket Evaluation            --> Is Live ($2,390.46) >= TP ($2,283.07)?                   |
|                                      YES! Instant TAKE_PROFIT_TRIGGERED win!                  |
|                                                                                               |
| 5. Kelly Flywheel                --> Micro-lot protection deactivates past $1,000. Sizing     |
|                                      balloons to 633 ETH ($1.42M notional) compounding daily. |
+-----------------------------------------------------------------------------------------------+
```

### Fault 1: The "Time Machine" Desynchronization
In [`webui/app.py`](file:///F:/012D_TRADE/Kronos/webui/app.py#L1128-L1138), the autopilot daemon passed static CSV files (`data/binance_ETHUSDT_1h.csv`, frozen at October 31 with ETH at \$2,247.12) to the prediction engine.
The model forecasted an upward swing and placed a Take-Profit target at **\$2,283.07**.
However, in [`src/quant/orchestrator.py`](file:///F:/012D_TRADE/Kronos/src/quant/orchestrator.py#L111-L115), open positions were evaluated using `self.index_engine.evaluate_universe()`, which fetched **live Binance API prices** (where ETH was trading at **\$2,390.46**).
Because the live price (\$2,390.46) was **already higher than the take-profit target (\$2,283.07) before the order was placed**, the condition:
```python
if curr_price >= pos.take_profit:
    pos.close_reason = "TAKE_PROFIT_TRIGGERED"
```
evaluated to `True` on the very next 60-second cycle for every single BUY order!

### Fault 2: Stale Fill Hallucination
The simulator treated a BUY order submitted in November as having filled at the historical price (\$2,247.79) without validating whether that quote existed on the live Binance Futures order book. On a real exchange, a BUY limit at \$2,247.79 would sit unfilled \$140 below market, while a market order would fill at \$2,390.50 with zero initial profit.

### Fault 3: Compounding Flywheel & Micro-Mode Deactivation
In [`src/quant/kev_risk_arbiter.py`](file:///F:/012D_TRADE/Kronos/src/quant/kev_risk_arbiter.py#L292-L295), the `small_account_threshold_usd` was set to \$1,000.
Once the first few artificial wins pushed simulated equity above \$1,000, micro-lot protections turned off.
Fractional Kelly sizing took over:
$$\text{Risk Budget} = \text{Account Equity} \times 0.015$$
$$\text{Position Notional} = \text{Risk Budget} \times \frac{\text{Price}}{\text{Entry} - \text{Stop Loss}}$$
By trade #440, with equity at \$900k+, single-order sizing exploded to **633.9 ETH (\$1,424,501 Notional Value)**!

### Fault 4: Machine Learning Contamination (`data/lessons.db`)
Because the orchestrator recorded every closed trade into SQLite [`data/lessons.db`](file:///F:/012D_TRADE/Kronos/data/lessons.db), 418 false wins corrupted the Brier calibration table, causing the Learning Governor to believe the model was omniscient (Brier score `0.0900`), locking confidence at `1.00x`.

---

## 3. Institutional Lessons Learned (Registered as Lesson #11)

Active Lesson #11 is permanently recorded in Kronos guidance:
```bash
python scripts/lessons.py query --category trading --search "time_machine"
```

### Core Invariants Established:
1. **Never Mix Asynchronous Time Horizons:** Lookback candles, order generation, and bracket execution MUST originate from the same real-time timestamp.
2. **Inverted Bracket Rejection:** A BUY bracket order where $\text{Take-Profit} \le \text{Entry}$ or $\text{Stop-Loss} \ge \text{Entry}$ is mathematically invalid and must be rejected at submission.
3. **Small Account Hard Ceilings:** Accounts $\le \$2,500$ must never exceed micro-notional limits (\$50 USDT max per trade) regardless of simulated equity.
4. **Empirical Health Verification:** Automated test scripts (`scripts/audit_quant_flaws.py`) must continuously audit win rates and notional sizes.

---

## 4. Assessment of Vibe-Trading (`BinqQarenYu/Vibe-Trading`)

We conducted an architectural assessment of [`BinqQarenYu/Vibe-Trading`](https://github.com/BinqQarenYu/Vibe-Trading) (HKUDS Vibe-Trading framework):

### Strengths & Capabilities Observed:
- **75 Specialized Skills:** In-depth coverage across market microstructure, execution modeling, perpetual funding rates, and risk analysis.
- **29 Multi-Agent Swarm Presets:** Pre-configured desks including `Quant Strategy Desk`, `Risk Committee`, and `Crypto Trading Desk`.
- **Execution & Microstructure Models:** Rigorous implementations of Almgren-Chriss square-root market impact:
  $$\text{Impact} = \eta \cdot \sigma \cdot \sqrt{\frac{V}{\text{ADV}}}$$
- **Backtest Diagnosis Taxonomy:** Clear error classifications for lookahead bias, capital under-utilization, and pre-triggered exits.

### Strategic Decision: Extract vs. Integrate
- **Do NOT import the monolithic package:** `vibe-trading-ai` is a heavy package (1,200+ files, external A-share APIs like Tushare, and multi-model LLM wrappers). Importing the full repository would introduce bloat and violate Kronos' core invariants of zero IEEE float financial math and sub-millisecond execution.
- **DO extract the crucial quantitative logic:** We surgically extracted and built the following native Kronos components inspired by Vibe-Trading:
  1. [`src/quant/quant_flaw_auditor.py`](file:///F:/012D_TRADE/Kronos/src/quant/quant_flaw_auditor.py): Native Kronos Quant Flaw Auditor.
  2. [`scripts/audit_quant_flaws.py`](file:///F:/012D_TRADE/Kronos/scripts/audit_quant_flaws.py): Command-line audit tool enforcing Almgren-Chriss impact and sanity bounds.
  3. [`tests/test_quant_flaw_auditor.py`](file:///F:/012D_TRADE/Kronos/tests/test_quant_flaw_auditor.py): Unit test suite ensuring zero-tolerance for vanity metrics.

---

## 5. Verification & Operational Health Check

- **Smoke Suite:** `python -m pytest tests/test_smoke.py -q` $\to$ **4 passed in 3.47s**
- **Quant Auditor Suite:** `python -m pytest tests/test_quant_flaw_auditor.py -q` $\to$ **4 passed in 0.15s**
- **Sanity Audit:** `python scripts/audit_quant_flaws.py` $\to$ **PASS (Certified realistic)**
- **Live Account Status:** Reset to ground truth **\$200.00 USDT**, 0 wins, 0 losses.
- **Live Background Server:** Active on `http://127.0.0.1:7070` (Task `task-4080`).
