# Kronos Unified Institutional Terminal Guide

> **URL:** `http://localhost:7070`  
> **Architecture:** Modern Single-Page Application (SPA) with Dark Institutional UI  
> **Engines:** TradingView Pro Lightweight Charts v4.1.3 + Plotly.js + REST API

---

## 1. Overview of the 3-in-1 Workspace

The Kronos Web UI integrates three institutional workstations into a single responsive application:

```
[ Top Navigation Bar: Breadth Pill | Macro Regime Pill | Engine Pill | Navigation Tabs ]
+--------------------------------------------------------------------------------------+
| 1. DASHBOARD VIEW       | 2. FORECASTER VIEW           | 3. BOT CONTROL VIEW         |
| Macro Breadth & VWAP    | TradingView & Plotly Pro     | KEV.ai 6-Point Veto Gate    |
| Funding Carry Radar     | Multi-Asset Horizon Forecast | Active Bracket Positions    |
| News Blackout Shield    | PEPE vs BTC Precision        | 12h Temporal Exit Clock     |
| Brier Learning KPI      | Lookback Buffer Importer     | SQLite Lessons Post-Mortem  |
+--------------------------------------------------------------------------------------+
```

Users can switch between workspaces instantaneously via the topbar tabs (`switchAppView('dashboard')`, `switchAppView('forecaster')`, `switchAppView('bot')`).

---

## 2. Workspace Breakdown

### 2.1 Workspace 1: The Modern Dashboard (`#view-dashboard`)

Designed for institutional portfolio managers and macro risk monitoring.

1. **Composite Breadth & Regime Gauge:**
   * Displays the percentage of core index assets trading above their 24-hour Volume-Weighted Average Price (VWAP).
   * **Regime Badges:**
     * `BULL_EXPANSION` (Green): $>60\%$ of assets above VWAP. Long orders pre-cleared.
     * `BEAR_DISTRIBUTION` (Red): $<40\%$ of assets above VWAP. Short orders pre-cleared.
     * `CHOP_COMPRESSION` (Amber): $40\%-60\%$ breadth. Trading size curtailed or throttled.
2. **24h VWAP Leaderboard:**
   * Live ranking of benchmark coins with spot price, 24h VWAP, distance percentage, and 24h volume.
3. **Perpetual Funding Rate Radar:**
   * Displays 8-hour funding rates, calculated annualized carry yield ($R_{\text{annual}} = R_{8\text{h}} \times 3 \times 365$), and actionable carry direction tags.
4. **Macro News Blackout Shield:**
   * Monitors upcoming macroeconomic releases (FOMC rate decisions, CPI reports, Non-Farm Payrolls).
   * Displays an active countdown clock and a prominent **`BLACKOUT ACTIVE`** alert when within $\pm 30$ minutes of high-impact news.
5. **Bayesian Learning Health (Hero Metric):**
   * Displays the rolling 48-hour Brier score and the live capital throttle multiplier ($0.0\text{x}$ to $1.0\text{x}$).

---

### 2.2 Workspace 2: Neural Forecaster (`#view-forecaster`)

The deep quantitative research and interactive charting environment.

1. **Dual Charting Engine:**
   * **TradingView Pro Lightweight Chart (Default):** Hardware-accelerated Canvas candlestick series with volume histograms, crosshair price tracking, and prediction trajectory markers.
   * **Plotly.js Visualizer:** Provides interactive zoom, box selection, and distribution inspection.
   * Switch between engines with one click via the `TradingView` / `Plotly` toggle.
2. **Asset-Aware Precision & Sub-Penny Formatting:**
   * **Micro-Penny Meme Coins (PEPE):** Automatically configures charts to 7–8 decimal places (`minMove: 0.0000001`, `precision: 8`).
   * **Standard Major Assets (BTC, ETH):** Formats prices to 2 decimal places (`minMove: 0.01`, `precision: 2`).
3. **Forecasting Parameters:**
   * **Lookback:** Context window length (up to 512 bars).
   * **Prediction Length:** Multi-horizon forecast steps (12h, 24h, 72h, 120h).
   * **Temperature & Top-p:** Controls autoregressive sampling dispersion.
4. **Data Ingestion:**
   * Automatically scans `data/` for historical CSV and Feather files.
   * Includes real-time Binance Kline fetcher with automatic `1000PEPEUSDT` futures routing.

---

### 2.3 Workspace 3: Quant Bot Station (`#view-bot`)

The live trading control station and risk oversight cockpit.

1. **Bot Telemetry & Controls:**
   * **Mode:** Paper Trading Simulation vs Live Binance Futures Execution.
   * **Capital & Risk Budget:** Displays account equity, leverage cap (5x max), and base risk budget ($1.5\%$).
   * **Immediate Scan Trigger:** The `Run Immediate Scan` button runs an instant multi-asset scan cycle through the full pipeline.
2. **KEV.ai 6-Point Supreme Veto Gate Audit Table:**
   * Displays every evaluated candidate coin with:
     * Proposed Side (`LONG` / `SHORT`).
     * Approval Status (`APPROVED` / `VETOED`).
     * Veto Gate Trigger (`GATE_1_MACRO`, `GATE_2_FUNDING`, `GATE_3_FEE_HURDLE`, `GATE_4_RR_RATIO`, `GATE_5_KELLY`, `GATE_6_DEVILS_ADVOCATE`).
     * Detailed Veto Reason and Adversarial Devil's Advocate commentary.
3. **Active Bracket Positions Table:**
   * Real-time list of active open bracket positions.
   * Displays: Position ID, Symbol, Side, Entry Price, Stop-Loss, Take-Profit, Size, R:R Ratio.
   * **12-Hour Stale-Trade Countdown Timer:** Displays remaining time before automatic temporal liquidation.
   * **Emergency Flatten Button:** Immediate one-click market close for any position.
4. **SQLite Lessons Console:**
   * Live streaming audit feed from `data/lessons.db`.
   * Displays historical trade outcomes, realized vs predicted price drift, and Brier calibration history.

---

## 3. REST API Reference

| Endpoint | Method | Description | Sample Output Keys |
| :--- | :--- | :--- | :--- |
| `/api/macro/overview` | `GET` | Returns market breadth, 24h VWAP leaderboard, funding rates, and news status. | `breadth_pct`, `macro_regime`, `coins_above_vwap`, `symbols`, `news_blackout` |
| `/api/bot/status` | `GET` | Returns bot operational state, equity, active bracket positions, and calibration status. | `bot_state`, `account_equity`, `active_positions`, `confidence_multiplier` |
| `/api/bot/scan` | `POST` | Evaluates candidate universe, executes KEV.ai veto audit, and dispatches orders. | `success`, `evaluated_count`, `dispatched_count`, `decisions`, `dispatched_trades` |
| `/api/bot/close-position` | `POST` | Manually flattens an active bracket position. | `success`, `position_id`, `symbol`, `realized_pnl` |
| `/api/learning/stats` | `GET` | Retrieves rolling Brier score and past trade post-mortems from SQLite. | `brier_score`, `confidence_multiplier`, `recent_outcomes`, `status` |
| `/api/predict` | `POST` | Generates autoregressive predictions from lookback buffer. | `success`, `prediction_results`, `metrics` |
| `/api/load-model` | `POST` | Loads the Kronos model weights into memory on demand. | `success`, `model_name`, `device` |

---

## 4. Running the Web UI

```bash
# Set UTF-8 encoding (recommended on Windows)
$env:PYTHONIOENCODING="utf-8"

# Start the Web UI server
python -X utf8 webui/app.py
```

Access the interface in your browser at `http://localhost:7070`.
