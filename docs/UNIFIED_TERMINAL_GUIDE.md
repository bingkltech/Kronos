# Kronos Unified Institutional Terminal Guide

> **URL:** `http://localhost:7070`  
> **Architecture:** Single-Page Application (SPA) with Bloomberg/Terminal-Grade Dark Architecture  
> **Engines:** HTML5 High-DPI Retina Canvas + TradingView Pro Lightweight Charts + Plotly.js + REST API  
> **Strategic Copilot:** Google Gemini Free Tier (`gemini-3.8-flash`) Meta-Strategy Arbiter  
> **Baseline Account:** Small-Account Micro-Trading ($200.00 USDT Paper Equity)  
> **Version:** 2.3.0 (Institutional Multi-Panel Workstation & Strategy Optimizer Release)

---

## 1. Overview of the 3-in-1 Unified Platform

The Kronos Web UI seamlessly links three institutional workstations into a single, cohesive, high-performance desktop application:

```
[ Top Navigation Bar: Breadth Pill | Macro Regime Pill | Engine Pill | Navigation Tabs ]
+--------------------------------------------------------------------------------------+
| 1. DASHBOARD VIEW       | 2. KRONOS FORECAST WORKSTATION  | 3. BOT & KEV.AI COCKPIT  |
| Top-10 Composite Breadth| Bloomberg 6-Panel Terminal Grid | KEV.ai 6-Point Veto Gate |
| 24h VWAP Leaderboard    | Market Watch & Multi-Asset Tape | Active Open Positions    |
| Funding Carry Radar     | Candlesticks + EMA 7/21 + VWAP  | 12h Temporal Exit Clock  |
| News Blackout Shield    | Shaded Purple Forecast Corridor | Micro-Trading $200 USDT  |
| Paper Performance Report| Agent Debate + Bull/Bear FIE    | Continuous Autopilot     |
| Win vs Loss / PnL Audit | Execution View + CVD Sub-Panel  | Memory & State Restore   |
| Brier Learning Health   | Monte Carlo Fan (6,000 Paths)   | SQLite Lessons Database  |
|                         | 3D Param Sweep Sharpe Landscape | Emergency Flatten & Reset|
+--------------------------------------------------------------------------------------+
```

Users can switch between workspaces instantaneously via the topbar tabs (`switchAppView('dashboard')`, `switchAppView('forecaster')`, `switchAppView('bot')`). Asset selection is bidirectional: clicking "Analyze in Forecaster" from the Macro Dashboard or Bot Page automatically switches to the Kronos Forecast Workstation and loads that asset's multi-panel context.

---

## 2. Workspace 1: The Macro Dashboard (`#view-dashboard`)

Designed for institutional portfolio managers, macro risk officers, and macro-trend surveillance.

### 2.1 Hero Metrics Grid
1. **Top-10 Composite Breadth:**
   * Percentage of core index assets trading above their 24-hour Volume-Weighted Average Price (VWAP).
   * **Regime Badges:**
     * `BULL_EXPANSION` (Green): $>60\%$ of assets above VWAP. Long orders pre-cleared.
     * `BEAR_DISTRIBUTION` (Red): $<40\%$ of assets above VWAP. Short orders pre-cleared.
     * `CHOP_COMPRESSION` (Amber): $40\%-60\%$ breadth. Trading size curtailed or throttled.
2. **Perpetual Funding Rate Radar:**
   * Real-time 8-hour funding rates and annualized carry yield ($R_{\text{annual}} = R_{8\text{h}} \times 3 \times 365$).
   * Flags high-cost carry drag ($>15\%$ annualized) to prevent long degradation.
3. **Macro News Blackout Shield:**
   * Automated radar tracking FOMC interest rate decisions, US CPI releases, and Non-Farm Payrolls (NFP).
   * Displays active countdown timers and locks trading into a **`BLACKOUT ACTIVE`** veto state within $\pm 30$ minutes of high-impact news.
4. **Bayesian Learning Health:**
   * Displays the rolling 48-hour Brier calibration score and the live capital throttle multiplier ($0.0\text{x}$ to $1.0\text{x}$) derived from `data/lessons.db`.

### 2.2 Paper Trading Performance Audit Report
* **Live Metrics Panel:**
  * **Win vs Loss Count:** Total completed trades, winning trades count, losing trades count, and win rate percentage.
  * **Total Realized PnL:** Net profit/loss displayed in USDT and percentage relative to starting equity ($200.00 USDT).
  * **Profit Factor:** Ratio of gross profits to gross losses.
* **Audit Log Table:**
  * Historical record of all closed paper trades with Ticket ID, Symbol, Side, Entry Price, Exit Price, Realized PnL ($ / %), and Exit Reason (`BRACKET_TAKE_PROFIT`, `BRACKET_STOP_LOSS`, `TEMPORAL_EXIT_12H`, `MANUAL_CLOSE`).
* **One-Click Account Reset:**
  * A reset button triggers a modal dialog allowing operators to re-initialize equity back to $200.00 USDT and archive historical trade records.

### 2.3 Gemini Free Tier Meta-Strategy Advisory Engine (CIO Copilot)
Located directly on the Macro Dashboard, this card acts as the Senior Supervisory Portfolio Strategist / Chief Investment Officer:
* **The Sweetspot Matrix:** Displays real-time quantitative target parameters:
  * **Reward/Risk Hurdle:** Dynamic minimum take-profit to stop-loss ratio ($1.40\text{x}-2.20\text{x}$).
  * **Net Fee Hurdle:** Dynamic minimum edge required above exchange maker/taker fees ($0.35\%-0.75\%$).
  * **Risk Budget %:** Dynamic capital allocation percentage per trade ($0.8\%-1.5\% \le \$3.00$ on small accounts).
  * **Fast & Slow EMA:** Dynamic momentum lookback windows ($10-25$ and $45-80$).
* **Regime Diagnosis & Conviction:** Automatically tags the market into institutional regimes (`TRENDING_EXPANSION`, `MEAN_REVERTING_RANGE`, `HIGH_VOLATILITY_TURBULENCE`, `REGIME_UNCERTAIN`) alongside a strategic confidence score ($0\%-100\%$).
* **Synthesized Intelligence:** Combines inputs from The Learning Governor (Brier score & trade history), ONNX Trajectory Engine, KEV.ai Risk Arbiter, and Bot Settings.
* **Autonomous Auto-Apply vs Manual Control:**
  * Toggle **Auto-Apply Sweetspot** to dynamically adopt new parameter hurdles directly into KEV.ai veto gates upon assessment completion.
  * Click **⚡ Run Assessment Now** to trigger an on-demand strategic reasoning pass via `gemini-3.8-flash`.
  * Click **Apply Sweetspot** to manually commit the latest recommendations.
* **Persistent Settings:** Sweetspot parameters and Auto-Apply preferences are automatically saved in `data/bot_settings.json` and restored on startup.

---

## 3. Workspace 2: Kronos Forecast Workstation (`#view-forecaster`)

The deep quantitative research and interactive charting environment, rebuilt into the institutional Bloomberg/Terminal-style 6-panel workstation layout.

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│ [KRONOS • AGENTS]  ● LIVE STREAMING   BTCUSDT • 15M      KRONOS FORECAST WORKSTATION   INDEX 83,280.2 (+0.73%) │
├──────────────────────┬─────────────────────────────────────────────────┬───────────────┤
│ MARKET WATCH         │ KRONOS FORECAST WORKSTATION (MAIN CHART)        │ TIME & SALES  │
│ • BTCUSDT (Amber)    │ • Candlesticks + EMA 7 / EMA 21 / VWAP          │ • Stream Tape │
│ • ETH, SOL, BNB,     │ • Purple Forecast Corridor: NEXT 15 BARS        │ • Bid/Ask Col │
│   DOGE, PEPE, SUI... │ • P(up) = 69% pill + OHLC box + Pink Price Tag  │ • Venues/Time │
├──────────────────────┼─────────────────────────────────────────────────┴───────────────┤
│ AGENT DEBATE (FIE)   │ BTCUSDT - EXECUTION VIEW & CVD                                  │
│ • Specialist Pills   │ • Horizontal Volume Profile + POC (Point of Control) line       │
│ • Bull/Bear Diverge  │ • Execution fills badge + TP / SL bracket levels                │
│ • Consensus Verdict  │ • Cumulative Volume Delta (CVD) sub-panel                       │
├──────────────────────┴───────────────────────────┬─────────────────────────────────────┤
│ MONTE CARLO - KRONOS SAMPLED PATHS               │ PARAM SWEEP - SHARPE (FAST/SLOW) 3D │
│ • 6,000 Fan/Ribbon Trajectory Paths (Teal/Cyan)  │ • 3D Isometric Wireframe Landscape  │
│ • P90, P55, P50, P5 percentile envelopes         │ • Glowing Amber/Gold Contours       │
│ • Terminal Return Distribution Histogram         │ • Peak Sharpe 1.32 @ 17/65 Reticle  │
│ • Risk Sidebar: Exp Return, VaR 95, CVaR 95      │ • Fast / Slow Parameter Axes        │
└──────────────────────────────────────────────────┴─────────────────────────────────────┘
```

### 3.1 Workstation Top Header Banner
* **Branding:** Amber `KRONOS • AGENTS` badge paired with a pulsating green `● LIVE STREAMING` status pill.
* **Context Display:** Active asset and resolution (`BTCUSDT • 15M • LIVE`), central uppercase workstation header, composite index benchmark (`INDEX 83,280.2 (+0.73%)`), and live UTC clock.
* **⚙️ Model & Config Drawer:** A collapsible drawer containing all advanced neural inference parameters (model selection, execution device, lookback slider, prediction horizon, temperature, top-p, and custom dataset loaders).

### 3.2 Panel 1: Market Watch (Top-Left)
* **High-Density Watchlist Table:**
  * Pre-loaded with top liquid crypto assets: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT`, `DOGEUSDT`, `XRPUSDT`, `AVAXUSDT`, `SUIUSDT`, `PEPEUSDT`, `NEARUSDT`, `1000PEPEUSDT`, `LINKUSDT`.
  * Columns: `SYMBOL | LAST | NET CHG | VOL`.
  * **Dynamic Sub-Penny Precision:** Automatically quantizes prices according to asset volatility (e.g. 8 decimals on `PEPEUSDT`, 6 decimals on `1000PEPEUSDT`, 4 decimals on `DOGEUSDT`, 2 decimals on `BTCUSDT`).
  * **Interactive Multi-Asset Switching:** Clicking any row highlights it with an amber accent bar (`#f59e0b`) and automatically synchronizes all 6 panels to that asset's order flow, price scale, and forecast trajectories.

### 3.3 Panel 2: Main Candlestick Chart (Top-Center)
* **High-Definition Canvas Renderer:** Hardware-accelerated Canvas with `window.devicePixelRatio` scaling.
* **Technical Overlays:**
  * `EMA 7` (Cyan `#22d3ee`): Fast trend indicator.
  * `EMA 21` (Amber `#f59e0b`): Intermediate swing indicator.
  * `VWAP` (Yellow `#eab308`): Intraday institutional benchmark.
* **Future Shaded Purple Forecast Corridor (`KRONOS - NEXT 15 BARS`):**
  * Translucent purple fill (`rgba(168, 85, 247, 0.14)`) extending 15 bars forward into the future horizon.
  * Top and bottom dashed boundary lines with center predicted trajectory line (`#c084fc`).
  * Header badge: `KRONOS - NEXT 15 BARS` with green probability badge: `P(up) = 69%`.
  * **OHLC Box Summary Overlay:** Semi-transparent HUD displaying predicted Open, High, Low, and Close at the horizon.
* **Live Price Badge:** Bright pink/magenta pill tag (`#ec4899`) tracking live tick price on the right vertical price scale.
* **Volume Histogram:** Candlestick-colored volume bars with an overlaid moving average line.

### 3.4 Panel 3: Time & Sales Tape (Top-Right)
* **Real-Time Streaming Tape:**
  * Columns: `PRICE | SIZE | BID | ASK | VENUE / TIME`.
  * Streaming order flow generated with sub-second frequency matching the active asset's price and liquidity characteristics.
  * **Color Differentiation:**
    * Green text for Ask-hit aggressive market buys.
    * Red text for Bid-hit aggressive market sells.
  * Venues tracked: `BINANCE`, `COINBASE`, `BYBIT`, `OKX`, `KRAKEN`.

### 3.5 Panel 4: Agent Debate - Bull vs Bear (Middle-Left)
* **Specialist Pillar Badges:**
  * Eight multi-agent scores: `Fundamentals (+0.36)`, `Sentiment (-0.55)`, `News (-0.26)`, `Technical (+0.35)`, `BULL (+0.38)`, `BEAR (-1.00)`, `TRADER (-0.26)`, `RISK (-0.66)`.
* **Diverging Vertical Bar Chart:**
  * Midline zero axis separating bullish forces from bearish forces.
  * Positive forces rise above the midline in cyan/green (`BULL`, `BULL`, `BULL`, `RISK BULL`).
  * Negative forces drop below the midline in red/coral (`BEAR`, `BULL RISK`, `RISK`, `RISK -0.66`).
* **Consensus Verdict Banner:**
  * Aggregated consensus pill displaying stance and confidence (e.g. `CONSENSUS: CAUTIOUS BULL [P(up) = 69%]`).

### 3.6 Panel 5: Execution View & CVD (Middle-Center)
* **Horizontal Volume Profile (Left 16%):**
  * Displays volume distribution across 18-20 price bins.
  * Prominent red/orange horizontal line marking the Point of Control (POC).
  * Value Area High (VAH) and Value Area Low (VAL) brackets.
* **Candlestick Execution View (Center/Right 84%):**
  * Candlestick chart showing simulated and live execution fills.
  * `FILLS` callout tag with arrow pointing to the executed candle.
  * Green dashed Take-Profit (TP) line and red dashed Stop-Loss (SL) line.
* **Cumulative Volume Delta (CVD) Sub-Panel (Bottom 30%):**
  * Zero baseline with `CVD` / `-CVD` markings.
  * Vertical delta bars: glowing green/cyan when buyer aggression dominates, red/magenta when seller aggression dominates.
  * Cumulative net delta polyline overlaid on top.

### 3.7 Panel 6: Monte Carlo - Sampled Paths (Bottom-Left)
* **6,000 Fan/Ribbon Trajectory Paths:**
  * Probabilistic future paths simulated via geometric Brownian motion with stochastic drift and empirical volatility.
  * Rendered as radiant glowing ribbons (cyan `#06b6d4` and teal `#22d3ee`) fanning out 15 bars forward from current price.
  * **Key Percentile Envelopes:**
    * `P90 +0.16%` (Green upper boundary).
    * `P55 +0.8%` (Cyan upper corridor).
    * `P50 +0.06` (Gold median trajectory).
    * `P5 -0.66%` (Red lower boundary).
* **Terminal Return Distribution Histogram (Right Side):**
  * Horizontal bar distribution curve at the 15-bar horizon.
  * Green bars indicate positive returns; red bars indicate negative returns.
* **Quantitative Risk Sidebar:**
  * Displays horizon duration (`+11.3M`), Expected Return (`+1.63%`), Value at Risk 95 (`VaR 95: -4.05%`), Conditional Value at Risk 95 (`CVaR 95: -1.95%`), Probability of Upward Drift (`P(UP): 89.00`), and Target Price Levels (P50, P95, P5).

### 3.8 Panel 7: 3D Param Sweep Sharpe Landscape (Bottom-Right)
* **Isometric Wireframe Surface:**
  * 3D wireframe mesh modeling the Sharpe ratio surface over Fast EMA periods (5..30) vs Slow EMA periods (30..100).
  * Glowing gold/amber gradient lines (`#f59e0b` to `#fbbf24`) with depth shading.
* **Peak Sharpe Targeting Reticle:**
  * Prominent crosshair reticle with pulsing concentric radar rings placed directly over the global maximum coordinate: `peak Sharpe 1.32 @ 17/65`.
  * Dynamic animation loop ensures smooth visual depth and shimmer without impacting CPU usage.

---

## 4. Workspace 3: Quant Bot Station (`#view-bot`)

The live trading control station, autonomous execution supervisor, and risk oversight cockpit.

### 4.1 Small-Account Micro-Trading Engine ($200 USDT)
* **Equity Baseline:** Initialized to **$200.00 USDT** for safe, controlled paper trading and small-account bootstrapping.
* **Micro-Lot Sizing:**
  * Maximum risk budget per trade: **1.5%** of equity ($\le \$3.00$ per trade).
  * Leverage capped at **5x** maximum.
  * Position size quantized to exchange lot step sizes via `Decimal` arithmetic.
* **Positive Expectancy Hurdle:**
  * Enforces dynamic Take-Profit targets providing a minimum Reward/Risk ratio of **$\ge 1.60:1$**.
  * Net fee hurdle check ensures minimum expected return exceeds round-trip maker/taker exchange fees by $\ge 0.50\%$.

### 4.2 Autonomous Autopilot Daemon
* **Continuous Background Execution:**
  * A daemon worker thread runs autonomously every 60 seconds (configurable from 15s to 300s).
  * Evaluates candidates across the universe, runs KEV.ai veto audits, submits bracket orders, and evaluates temporal exits.
* **Persistent Configuration Memory (`data/bot_settings.json`):**
  * Remembers autopilot state (`enabled: true/false`) and scan interval (`interval_seconds: 60`).
  * Restores settings automatically upon server restart.
* **Full Position & Trade History Persistence (`data/paper_trading_state.json`):**
  * Open bracket positions are serialized with full precision (`entry_price`, `size`, `stop_loss`, `take_profit`, `entry_time`).
  * Closed trade history and equity curves survive application restarts without loss of data.

### 4.3 KEV.ai 6-Point Supreme Veto Gate Audit Table
Displays every evaluated candidate coin with:
1. Proposed Side (`LONG` / `SHORT`).
2. Approval Status (`APPROVED` / `VETOED`).
3. Veto Gate Trigger:
   * `GATE_1_MACRO`: Directional trend alignment with composite index breadth.
   * `GATE_2_FUNDING`: Annualized carry cost drag.
   * `GATE_3_FEE_HURDLE`: Net fee hurdle check ($\ge 0.50\%$).
   * `GATE_4_RR_RATIO`: Reward/Risk ratio hurdle ($\ge 1.60:1$).
   * `GATE_5_KELLY`: Dollar risk budgeting (1.5% max).
   * `GATE_6_DEVILS_ADVOCATE`: Adversarial multi-agent contradiction check.
4. Detailed Veto Reason and Adversarial Commentary.

### 4.4 Active Bracket Positions & Temporal Liquidation
* Real-time list of active open bracket positions.
* **12-Hour Stale-Trade Countdown Timer:** Displays remaining time before automatic temporal liquidation.
* **Emergency Flatten:** One-click manual market liquidation for individual positions or the entire portfolio.

---

## 5. REST API Reference

| Endpoint | Method | Description | Sample Output Keys |
| :--- | :--- | :--- | :--- |
| `/api/macro/overview` | `GET` | Returns market breadth, 24h VWAP leaderboard, funding rates, news status, and paper trading summary. | `breadth_pct`, `macro_regime`, `symbols`, `news_blackout`, `paper_report` |
| `/api/binance/fetch-klines` | `POST` | Fetches live market candles directly from Binance public API with fallback. | `success`, `data_info.candles`, `price_range` |
| `/api/bot/status` | `GET` | Returns bot operational state, equity, active bracket positions, and calibration status. | `bot_state`, `account_equity`, `active_positions`, `confidence_multiplier` |
| `/api/bot/scan` | `POST` | Evaluates candidate universe, executes KEV.ai veto audit, and dispatches orders. | `success`, `evaluated_count`, `dispatched_count`, `decisions`, `dispatched_trades` |
| `/api/bot/close-position` | `POST` | Manually flattens an active bracket position. | `success`, `position_id`, `symbol`, `realized_pnl` |
| `/api/bot/paper-report` | `GET` | Returns comprehensive paper trading performance audit metrics and closed trade logs. | `success`, `report.win_rate`, `report.total_pnl_usdt`, `report.closed_trades` |
| `/api/bot/paper-reset` | `POST` | Resets paper trading equity back to $200.00 USDT and archives trade history. | `success`, `message`, `report` |
| `/api/bot/autopilot/toggle` | `POST` | Enables/disables autonomous background scanning daemon. | `success`, `autopilot_enabled`, `interval_seconds` |
| `/api/learning/stats` | `GET` | Retrieves rolling Brier score and past trade post-mortems from SQLite. | `brier_score`, `confidence_multiplier`, `recent_outcomes`, `status` |
| `/api/predict` | `POST` | Generates autoregressive predictions from lookback buffer. | `success`, `prediction_results`, `metrics` |
| `/api/load-model` | `POST` | Loads the Kronos model weights into memory on demand. | `success`, `model_name`, `device` |
| `/api/gemini/assessment` | `GET` | Returns latest Gemini strategic meta-assessment, active sweetspot, and auto-apply status. | `available`, `model`, `auto_apply`, `assessment`, `active_sweetspot` |
| `/api/gemini/assess` | `POST` | Triggers an immediate strategic reasoning pass via Gemini Free Tier. | `success`, `assessment` |
| `/api/gemini/apply-sweetspot` | `POST` | Manually applies the recommended sweetspot parameters to live KEV.ai gates. | `success`, `message` |
| `/api/gemini/toggle-auto-apply` | `POST` | Toggles automatic sweetspot adoption upon background assessment completion. | `success`, `auto_apply` |

---

## 6. Running the Web UI

```bash
# Set UTF-8 encoding (recommended on Windows)
$env:PYTHONIOENCODING="utf-8"

# Start the Web UI server
python -X utf8 webui/app.py
```

Access the interface in your browser at `http://localhost:7070`.

To run the automated verification test suite:
```bash
python -m pytest tests/ -q
```
