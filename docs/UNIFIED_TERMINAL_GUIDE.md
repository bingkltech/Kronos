# Kronos Unified Institutional Terminal Guide

> **URL:** `http://localhost:7070`  
> **Architecture:** Single-Page Application (SPA) with Bloomberg/Terminal-Grade Dark Architecture  
> **Engines:** HTML5 High-DPI Retina Canvas + TradingView Pro Lightweight Charts + Plotly.js + REST API  
> **Strategic Copilot:** Google Gemini Free Tier (`gemini-3.8-flash`) Meta-Strategy Arbiter  
> **Baseline Account:** Small-Account Micro-Trading ($200.00 USDT Paper Equity)  
> **Version:** 2.4.0 (Dynamic Institutional Chart, Multi-Pane Workstation & Drag-to-Pan Release)

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

### 2.2 Realistic Paper Trading & Performance Audit Report
Engineered to eradicate false/vanity simulation reports and match real Binance USDⓈ-M Futures execution:
* **Dual-Layer PnL Accounting (Gross vs. Net Realized):**
  * Tracks pure market price motion (`Gross PnL`) and true cash-balance delta (`Net Realized PnL`).
  * Deducts real exchange taker fees (0.05% / $5\text{ bps}$) on aggressive market entries/exits, and maker fees (0.02% / $2\text{ bps}$) on limit Take-Profit executions.
  * **Elimination of False Wins:** Trades with small price appreciation ($< 0.07\%$) that are overwhelmed by round-trip transaction friction are strictly audited and classified as **`LOSS`**, matching real live wallet dynamics.
* **Microstructure Slippage & Adverse Liquidation Modeling:**
  * Market entry orders cross the bid/ask spread with estimated slippage ($0.03\%-0.08\%$).
  * Stop-Loss market liquidations model adverse execution slippage during selloffs ($1.5\text{x}$ baseline).
* **Live Market Temporal Exits:**
  * When a trade lingers past the 12-hour temporal expiry limit without triggering TP or SL, it liquidates at the **live current market price** (with taker fee + slippage), rather than artificially assuming a break-even $0 exit.
* **Perpetual Funding Rate Drag:**
  * Positions crossing 8-hour funding intervals (00:00, 08:00, 16:00 UTC) accumulate realistic funding drag deducted directly from net realized PnL.
* **Test Isolation Protection:**
  * Automated testing suites run in isolated memory containers, guaranteeing unit test fixtures ($10,000 notional mock trades) can never pollute the live paper trading ledger.
* **Live Metrics Panel & Transparent Audit Table:**
  * **Win vs Loss Count:** Win rate percentage computed strictly on Net Realized PnL.
  * **Total Realized PnL & Fee Drag:** Net balance displayed alongside cumulative fees paid ($) and gross PnL.
  * **Audit Log Table:** Displays exact timestamps, symbols, quantities, entry/exit prices, fee drag, gross PnL, net realized PnL, and outcome badges (`WIN` / `LOSS` / `EVEN`).
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

## 3. Workspace 2: Kronos Dynamic Forecast Workstation (`#view-forecaster`)

The deep quantitative research and interactive charting environment, rebuilt into the high-performance institutional prop trading suite.

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│ [KRONOS • AGENTS]  ● LIVE STREAMING   [BTC][ETH][SOL][XRP][PEPE]  [15M][1H][4H]  [⚙️ Config]   │
├────────────────────────────────────────────────────────────────────────────────────────┤
│ TOP FRAME: PRIMARY FORECAST CHART (~63% Height, Full Drag-to-Pan & Zoom)               │
│                                                                                        │
│  BTC 1H · 12:00-13:00                                 DOWN · REPLAY vs KRONOS  60.0    │
│  T-50:04                                              EDGE +12.5  kronos 72.5          │
│  WALK-FORWARD 2/5                                     1,000 futures · Kronos-small 24M │
│                                                                                        │
│  | (10-30 outside)      | (10-31 outside)                                              │
│  |                      |                     NOW $77,859                              │
│  |                      |                         ●                        P(up) 0.275 │
│  [White Up Candles]     [Dark Down Candles]       (◎)========\== Golden Fan ============│
│                                                               \================= P(down) 0.725│
│                                                                                        │
│  [⟲ Reset] [+] [-] [◄ Pan] [Pan ►]                                         10-31 11-01 │
├────────────────────────────────────────────────────────────────────────────────────────┤
│ > SIGNAL DOWN 0.725 vs replay 0.600 · edge +12.5 pts · paper · next candle 50:04 [SIGNAL]      │
├========================================================================================┤
│ <--- HORIZONTAL SPLITTER: Drag Up/Down to Resize Top Chart vs Bottom Workstation Panes --->   │
├========================================================================================┤
│ BOTTOM WORKSTATION (~37% Height, Draggable Sub-Panes with Vertical Splitters)          │
│                                 |                                 |                    │
│  01 HEAT MAP                    |  02 FLOW, +buy/-sell 3d         |  * CLAUDE CODE/SIM │
│  21,177 real trades · Binance   |  every trade                    |  opus 5.5 · SIM log│
│  XBT/USD · Market: 10/30/2026   |  [CVD Mountain Area Chart]      |  path 0514 target  │
│  [Liquidity Depth Heat Bands]   |   +205 (Buy Flow, Cyan Area)    |  path 0847 stop    │
│  "Falls $1,509 in 24m"          |    0   ----------------------   |  path 0262 open    │
│  "+$769 back in 7m"             |   -419 (Sell Flow, Orange Area) |  --- 176 shown --- │
│  "121 BTC traded in 1m"         |  ------------------------------ |  path 0571 target  │
│  [Volume Histogram Bars]        |  5+ BTC : ■ 8.1%  | ■ 6.2%      |  path 0999 stop    │
│  (Drag to Pan / Scrub Time)     |  1-5    : ■ 19.0% | ■ 22.3%     |  ----------------- │
│                                 |  <0.05  : ■ 15.7% | ■ 10.6%     |  > place order     │
│  [VERTICAL SPLITTER 1]          |  [VERTICAL SPLITTER 2]          |                    │
└─────────────────────────────────┴─────────────────────────────────┴────────────────────┘
```

### 3.1 Workstation Top Header Banner & Fast Selectors
* **Branding:** Amber `KRONOS • AGENTS` badge paired with a pulsating green `● LIVE STREAMING` status pill.
* **Fast Asset Pills:** Direct selector buttons (`[BTC]`, `[ETH]`, `[SOL]`, `[XRP]`, `[PEPE]`) allowing instant switching of instrument context, order book ladders, CVD flows, and Monte Carlo trajectory projections.
* **Resolution Badges:** Quick timeframe selectors (`15M`, `1H`, `4H`).
* **⚙️ Model & Config Drawer:** Collapsible panel for model reload, PyTorch inference device, lookback slider (100–512), and horizon configurations.

### 3.2 Top Frame: Primary Forecast Chart (Dynamic Drag-to-Pan & Zoom)
* **High-DPI Retina Canvas:** Hardware-accelerated Canvas with `window.devicePixelRatio` scaling.
* **Fluid Drag-to-Pan Interaction:**
  * **Timeline Drag:** Click and drag left or right anywhere across the chart canvas to pan through historical candles and into future forecast horizons.
  * **Price Scale Drag:** Click and drag vertically on the right-margin price axis to scale vertical volatility amplitude.
  * **Mouse Wheel Zoom:** Smooth exponential zoom centered at mouse cursor coordinates.
  * **Touch Support:** Single-touch drag and mobile pan.
  * **Navigation HUD:** Direct buttons for instant control: `⟲ Reset`, `+ Zoom`, `- Zoom`, `◄ Pan`, `Pan ►`.
* **Dark Monochrome Candlesticks:**
  * Bullish candles: Crisp solid white bodies (`#ffffff`) and white wicks.
  * Bearish candles: Deep dark slate bodies (`#090d14`) with light grey borders (`#94a3b8`) and wicks.
* **Red Outside Marker Lines:**
  * `10-30 outside`: Vertical marker line indicating boundary time.
  * `10-31 outside`: Vertical marker line tracking period transitions.
* **Dynamic Floating Beacon (`NOW $77,859`):**
  * Anchored directly to active candle close with a concentric gold/white target reticle.
  * Floating price callout with dynamic sub-penny precision and dark halo shadow.
* **Luminous Golden Monte Carlo Trajectory Fan (1,000 Futures):**
  * Originates at current candle close, radiating into the 30-bar forecast horizon.
  * **Upper Outliers (Cool Grey / Cyan):** 16 paths fanning upward with probability tag `P(up) = 0.275`.
  * **Downward Cluster (Glowing Gold / Amber):** 52 high-density Bézier trajectories with opacity gradient ($\alpha \in [0.18, 0.65]$) and probability tag `P(down) = 0.725`.

### 3.3 Mid-Divider Signal Ribbon
* Monospace ticker banner: `> SIGNAL DOWN 0.725 vs replay 0.600 · edge +12.5 pts · paper · next candle 50:04`.
* Gold accented `[SIGNAL]` trigger button for instant model signal inspection.

### 3.4 Horizontal Resizable Splitter
* High-visibility resizable divider (`#ws-h-splitter`, cursor `row-resize`) between Top Chart and Bottom Workstation.
* Drag up or down to adjust relative frame heights smoothly at 60 FPS.

### 3.5 Bottom Workstation: 3 Modular Draggable Panes

#### Pane 1: `01 HEAT MAP`
* **Real-Time Liquidity Depth Ladder:** Step-like amber/orange heat bands around order book resting limit density.
* **Stepped Transaction Line:** White stepped trace tracking discrete executions.
* **Empirical Callout Annotations:**
  * `00:43  76,860  6.0 BTC`
  * `+$769 back in 7 minutes` (pointing to upward recovery bounce)
  * `Falls $1,509 in 24 minutes` (pointing to sharp drop)
  * `121 BTC traded in one minute` (pointing to volume spike)
* **Interactive Drag-to-Pan:** Click and drag left/right inside Heat Map to scrub historical liquidity.

#### Pane 2: `02 FLOW, +buy/-sell 3d`
* **Dual Cumulative Volume Delta (CVD) Mountain Chart:**
  * Buy Flow: Layered cyan area chart above zero line (`+205`, `+100`, `+50`, `0`).
  * Sell Flow: Layered orange area chart below zero line (`0`, `-50`, `-100`, `-419`).
  * Net Delta Line: Solid white line tracking cumulative delta trajectory.
  * Day markers: `Fri`, `Sat`, `Sun`.
* **Multi-Tier Order Flow Breakdown Table:**
  * `5+ BTC` : `■ 8.1%` buy | `■ 6.2%` sell
  * `1-5` : `■ 19.0%` buy | `■ 22.3%` sell
  * `0.25-1` : `■ 31.0%` buy | `■ 34.2%` sell
  * `0.05-0.25` : `■ 26.2%` buy | `■ 26.7%` sell
  * `<0.05 BTC` : `■ 15.7%` buy | `■ 10.6%` sell
  * Footer: `— raw hourly · 7,978 BTC   +126 -138`.
* **Interactive Drag-to-Pan:** Click and drag left/right inside Flow to pan through time.

#### Pane 3: `* CLAUDE CODE / AGENT SIM LOG`
* **Monospace Monte Carlo Simulation Path Stream:** Real-time color-coded path execution outcomes:
  * Green (`target`): `path 0514  target  h+10  +2.0 % pnl`
  * Red (`stop`): `path 0847  stop    h+17  -1.0 % pnl`
  * Cyan (`open`): `path 0262  open    h+48  +1.2 % pnl`
  * Summary line: `176 shown · target 19.3% · stop 29.8%`
* **Interactive `> place the paper order` Button:**
  * One-click automated dispatch button.
  * Calls `/api/bot/place-order`, executes against background realistic friction engine, appends execution path directly into the stream, and triggers visual confirmation toast!

### 3.6 Vertical Resizable Splitters
* `ws-v-splitter-1` (between Pane 1 and Pane 2, cursor `col-resize`).
* `ws-v-splitter-2` (between Pane 2 and Pane 3, cursor `col-resize`).
* Drag left/right to widen or shrink any pane dynamically.

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
