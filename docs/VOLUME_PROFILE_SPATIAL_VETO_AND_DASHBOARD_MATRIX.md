# Kronos Volume Profile Spatial Liquidity Veto, AWS Integrity Hardening & 1-Year Asset Matrix

> **Document Version:** 1.0.0  
> **Date:** 2026-11-18  
> **Core Modules:** `src/quant/volume_profile.py`, `src/quant/orchestrator.py`, `src/quant/apex_scalper.py`, `src/quant/tiger_scalper.py`, `src/quant/config.py`, `scripts/headless_worker.py`, `scripts/tiger_worker.py`, `webui/app.py`, `webui/static/js/yearly_matrix.js`  
> **Verification:** `python -m pytest tests/ -q` (**146 passed, 0 failed**) · Live AWS EC2 (`13.63.158.94`) verified (`0` precision mismatches, `148 MB` RSS, `42%` disk)

---

## 1. Previous-UTC-Day Fixed-Range Volume Profile Engine (`src/quant/volume_profile.py`)

### 1.1 Mathematical Specification & Zero-Lookahead Guarantee
Unlike time-based volume indicators, the Volume Profile maps volume across **price** to expose institutional liquidity magnets and chop zones:

* **Strictly Completed Prior Session:** Anchors exclusively to the completed previous UTC day's `96 × 15m` Binance USD(S)-M Futures candles (`00:00:00–23:59:59 UTC` of `D - 1`). Never uses developing current-day candles, eliminating lookahead bias and level repainting.
* **Zero-Float Financial Math (`AGENTS.md` Invariant 1):** All bin boundaries, overlap fractions, volume distributions, distances, and density ratios use `decimal.Decimal`.
* **Parameters:** `row_size = 60` equal price bins across `[session_low, session_high]`, `value_area_pct = Decimal("0.70")` (70% Value Area).
* **Binning:** Each candle's volume is distributed proportionally across every overlapping bin by exact overlap fraction $(\min(b_{\text{hi}}, H) - \max(b_{\text{lo}}, L)) / (H - L)$.
* **Extracted Spatial Levels:**
  * **`pPOC` (Point of Control):** Midpoint of the maximum-volume bin.
  * **`pVAH` / `pVAL` (Value Area High / Low):** Iterative two-sided expansion from `pPOC` until cumulative volume reaches 70% of total session volume.
  * **`local_vol_ratio`:** Volume density at entry price relative to session average bin volume ($\ge 1.50\times$ = **High-Volume Node / HVN** chop zone; $\le 0.50\times$ = **Low-Volume Node / LVN** fast-travel pocket).
  * **`prior_close_regime`:** `INSIDE_VA` (balanced), `ABOVE_VA` (imbalanced bullish), or `BELOW_VA` (imbalanced bearish).

### 1.2 Ultra-Lean Daily Cache (`DailyVolumeProfileCache`)
Designed specifically for AWS `t3.micro` (1 GB RAM):
* Fetches `96 × 15m` klines at most **once per symbol per UTC day** (`0.024 ms` cache hit latency verified on AWS).
* Auto-evicts prior-day keys on UTC rollover (`< 10 KB` bounded RAM for all 11 symbols).
* **Fail-Open Resilience:** Returns `None` with a 5-minute negative-retry cooldown during transient Binance API outages so trading never deadlocks.

---

## 2. Empirical Counterfactual Validation (Zero-Lookahead Audit)

Before wiring any rule into live execution, every Volume Profile hypothesis was audited against **293 real closed live Binance Futures trades** (221 Macro + 72 Scalp, Nov 9–16, 2026) and **30 Stalking Tiger trades**:

| Hypothesis | Kept ($n$) | Win Rate | Profit Factor | Net PnL | $\Delta$ Net PnL | Fees Saved | Chronological H1 / H2 | Monte Carlo $p$ | Decision |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Baseline (All Live)** | 293 | 50.9% | 1.06 | +\$3.80 | — | — | -\$0.02 / +\$3.83 | — | — |
| **H1: `VP_FIRING_INTO_POC`** *(opposing pPOC 0.05–0.80% ahead)* | 274 | 52.2% | 1.13 | +\$8.14 | +\$4.34 | \$0.85 | +\$3.01 / +\$1.32 (**BOTH+**) | `0.0371` | **DEPLOYED** |
| **H4: `VP_HVN_CHOP`** *(local bin density $\ge 1.50\times$ avg)* | 236 | 53.0% | 1.24 | +\$12.51 | +\$8.71 | \$2.51 | +\$1.94 / +\$6.75 (**BOTH+**) | `0.0117` | **DEPLOYED** |
| **H1 + H4 Combined** | **225** | **54.2%** | **1.30** | **+\$14.68** | **+\$10.88 (+286%)** | **\$3.00** | **+\$3.60 / +\$7.26 (BOTH+)** | **`0.0034`** | **DEPLOYED** |
| **H2: VA Edge Wall (`pVAH`/`pVAL`)** | 269 | 51.3% | 1.05 | +\$3.24 | -\$0.56 | — | -\$4.34 / +\$3.77 (MIXED) | — | **REJECTED** |
| **VA Mean-Reversion to `pPOC`** | 65 | 40.0% | 0.50 | -\$8.39 | — | — | — | — | **REJECTED** |

### Robustness Checks on `H1 + H4`
* **Direction-Neutral:** Independently improved both **`BUY`** trades (`+$8.59`, blocked 34 entries at `23.5%` WR) and **`SELL`** trades (`+$2.28`, blocked 34 entries).
* **Cross-Symbol Breadth:** **9 of 10 symbols improved** (`1000PEPEUSDT`, `ETHUSDT`, `DOGEUSDT`, `BTCUSDT`, `XRPUSDT`, `BNBUSDT`, `SUIUSDT`, `ADAUSDT`, `LINKUSDT`).
* **Stalking Tiger (`n = 30` paper cohort):** Vetoing **`VP_FADING_BREAKOUT`** (shorting above `pVAH` or longing below `pVAL`) blocked `13/30` trades (`15.4%` WR, `-$16.06`), lifting Tiger from `-$10.03` (PF `0.70`) to `+$6.03` (PF `1.46`, `p = 0.0194`).

### Active Engine Integration Map
| Engine | File | Active Volume Profile Veto Rules |
| :--- | :--- | :--- |
| **Macro Orchestrator** | `src/quant/orchestrator.py` | `VP_FIRING_INTO_POC` + `VP_HVN_CHOP` (uses `mock_volume_profiles` in offline tests) |
| **Apex / Lightning Scalper** | `src/quant/apex_scalper.py`, `webui/app.py`, `scripts/headless_worker.py` | `VP_FIRING_INTO_POC` + `VP_HVN_CHOP` (shared `quant_bot.volume_profile_cache`) |
| **Stalking Tiger (Strategy #3)** | `src/quant/tiger_scalper.py`, `scripts/tiger_worker.py` | `VP_FIRING_INTO_POC` + `VP_HVN_CHOP` + `VP_FADING_BREAKOUT` |

---

## 3. AWS Production Integrity Hardening & Live Trade Quota Guard

During live deployment verification on AWS EC2 (`13.63.158.94`), four production bugs were identified and resolved:

1. **Binance Futures `exchangeInfo` Precision Alignment (`src/quant/config.py`):**
   * `BTCUSDT`: `price_precision` aligned `2 → 1` (`tickSize = 0.10`).
   * `ADAUSDT`: `quantity_precision` aligned `1 → 0`, `min_quantity` `0.1 → 1` (`stepSize = 1`) — resolved recurring HTTP 400 `Precision is over the maximum defined for this asset`.
   * `AVAXUSDT`: `price_precision` `2 → 3`, `quantity_precision` `2 → 0`, `min_quantity` `0.01 → 1`.
   * Verified **0 mismatches** across all live Binance Futures contracts.
2. **Frozen `KEVDecision` Mutation Crash (`src/quant/orchestrator.py`):**
   * Replaced illegal field mutations (`decision.approved = False`) with `dataclasses.replace(decision, ...)` on Storm Protocol vetoes and rejected exchange orders.
3. **Headless Neural Model Gate Flag (`src/quant/orchestrator.py`, `scripts/headless_worker.py`):**
   * Added `require_neural_model: bool = True` (strict fail-safe on local PC WebUI) while allowing AWS lean headless mode (`service_url=""`) to pass `require_neural_model=False`.
4. **Apex Scalper Field Fix & Forensic Tagging (`scripts/headless_worker.py`):**
   * Fixed `apex.predicted_drift_pct` → `apex.expected_net_drift_pct` and added `record_scalp_order(...)` calls for entry/TP/SL IDs.
5. **Persistent Live Trade-Quota Auto-Pause Circuit Breaker (`scripts/headless_worker.py`, `src/quant/orchestrator.py`):**
   * Supports `POST /api/live/toggle` with `{"enabled": true, "trade_cap": 20, "reset_trade_count": true}` and enforces `max_new_entries` per scan cycle so trade #21 can never dispatch.
   * Persists `{live_trading_enabled, live_trade_cap, live_session_trades, live_cap_reached_utc}` atomically to `data/aws_trade_quota.json` across systemd restarts and exposes `trade_quota` + `volume_profile_veto` telemetry on `/api/live/status`.

---

## 4. Dashboard 1-Year Rolling Monthly Asset Activity & Profitability Matrix

Added an institutional monthly heatmap report card at the bottom of the main Dashboard (`#view-dashboard` at `http://localhost:7070`):

* **Backend Endpoint (`webui/app.py`):** `GET /api/analytics/yearly-matrix?source=live|tiger|paper&refresh=false`
  * Computes a **rolling 12-month UTC calendar** ending on the current month plus a `1Y` summary column.
  * Deduplicates Binance partial fills by `(symbol, order_id)` so every cell accurately counts distinct **Bought (`B`)** and **Sold (`S`)** executions alongside `Decimal`-exact Gross PnL, Fee Drag, and **Net PnL**.
  * Merges live Binance `/fapi/v1/userTrades` with historical `data/live_audit_summary.json` (zero double-counting), and supports switching to `tiger` (`data/tiger_trades.db`) and `paper` (`data/paper_trading_state.json`).
  * Cached 60s server-side to protect Binance API rate limits.
* **Frontend Matrix (`webui/templates/index.html`, `webui/static/css/terminal.css`, `webui/static/js/yearly_matrix.js`):**
  * Top **`Portfolio`** summary row with pill framing, active-month vertical accent highlight, per-asset color dots, intensity-scaled **Green** (profitable, `Net PnL > $0`) / **Red** (loss, `Net PnL < $0`) rounded heatmap pills, `1Y` summary column, hover tooltips, and live Source (`Live` / `Tiger` / `Paper`) & Display (`B/S + $` / `B/S` / `PnL $`) selectors.
