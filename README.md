<div align="center">
  <h2><b>Kronos: A Foundation Model for the Language of Financial Markets </b></h2>
</div>


<div align="center">

</a> 
<a href="https://huggingface.co/NeoQuasar"> 
<img src="https://img.shields.io/badge/🤗-Hugging_Face-yellow" alt="Hugging Face"> 
</a> 
<a href="https://shiyu-coder.github.io/Kronos-demo/"> <img src="https://img.shields.io/badge/🚀-Live_Demo-brightgreen" alt="Live Demo"> </a>
<a href="https://github.com/shiyu-coder/Kronos/graphs/commit-activity"> 
<img src="https://img.shields.io/github/last-commit/shiyu-coder/Kronos?color=blue" alt="Last Commit"> 
</a> 
<a href="https://github.com/shiyu-coder/Kronos/stargazers"> 
<img src="https://img.shields.io/github/stars/shiyu-coder/Kronos?color=lightblue" alt="GitHub Stars"> 
</a> 
<a href="https://github.com/shiyu-coder/Kronos/network/members"> 
<img src="https://img.shields.io/github/forks/shiyu-coder/Kronos?color=yellow" alt="GitHub Forks"> 
</a> 
<a href="./LICENSE"> 
<img src="https://img.shields.io/github/license/shiyu-coder/Kronos?color=green" alt="License"> 
</a>

</div>

<div align="center">
  <!-- Keep these links. Translations will automatically update with the README. -->
  <a href="https://zdoc.app/de/shiyu-coder/Kronos">Deutsch</a> | 
  <a href="https://zdoc.app/es/shiyu-coder/Kronos">Español</a> | 
  <a href="https://zdoc.app/fr/shiyu-coder/Kronos">Français</a> | 
  <a href="https://zdoc.app/ja/shiyu-coder/Kronos">日本語</a> | 
  <a href="https://zdoc.app/ko/shiyu-coder/Kronos">한국어</a> | 
  <a href="https://zdoc.app/pt/shiyu-coder/Kronos">Português</a> | 
  <a href="https://zdoc.app/ru/shiyu-coder/Kronos">Русский</a> | 
  <a href="https://zdoc.app/zh/shiyu-coder/Kronos">中文</a>
</div>

<p align="center">

<img src="./figures/logo.png" width="100">

</p>

> Kronos is the **first open-source foundation model** for financial candlesticks (K-lines), 
> trained on data from over **45 global exchanges**.


</div>

## 📰 News
*   🚩 **[2025.11.10]** Kronos has been accpeted by AAAI 2026.
*   🚩 **[2025.08.17]** We have released the scripts for fine-tuning! Check them out to adapt Kronos to your own tasks.
*   🚩 **[2025.08.02]** Our paper is now available on [arXiv](https://arxiv.org/abs/2508.02739)!

<p align="center">

## 📜 Introduction

**Kronos** is a family of decoder-only foundation models, pre-trained specifically for the "language" of financial markets—K-line sequences. Unlike general-purpose TSFMs, Kronos is designed to handle the unique, high-noise characteristics of financial data. It leverages a novel two-stage framework: 
1. A specialized tokenizer first quantizes continuous, multi-dimensional K-line data (OHLCV) into **hierarchical discrete tokens**. 
2. A large, autoregressive Transformer is then pre-trained on these tokens, enabling it to serve as a unified model for diverse quantitative tasks.

<p align="center">
    <img src="figures/overview.png" alt="" align="center" width="700px" />
</p>

## ✨ Live Demo 
We have set up a live demo to visualize Kronos's forecasting results. The webpage showcases a forecast for the **BTC/USDT** trading pair over the next 24 hours. 

**👉 [Access the Live Demo Here](https://shiyu-coder.github.io/Kronos-demo/)** 

## 📦 Model Zoo 
We release a family of pre-trained models with varying capacities to suit different computational and application needs. All models are readily accessible from the Hugging Face Hub.

| Model        | Tokenizer                                                                       | Context length | Params  | Open-source                                                               |
|--------------|---------------------------------------------------------------------------------| -------------- | ------ |---------------------------------------------------------------------------|
| Kronos-mini  | [Kronos-Tokenizer-2k](https://huggingface.co/NeoQuasar/Kronos-Tokenizer-2k)     | 2048           | 4.1M   | ✅ [NeoQuasar/Kronos-mini](https://huggingface.co/NeoQuasar/Kronos-mini)  |
| Kronos-small | [Kronos-Tokenizer-base](https://huggingface.co/NeoQuasar/Kronos-Tokenizer-base) | 512            | 24.7M  | ✅ [NeoQuasar/Kronos-small](https://huggingface.co/NeoQuasar/Kronos-small) |
| Kronos-base  | [Kronos-Tokenizer-base](https://huggingface.co/NeoQuasar/Kronos-Tokenizer-base) | 512            | 102.3M | ✅ [NeoQuasar/Kronos-base](https://huggingface.co/NeoQuasar/Kronos-base)   |
| Kronos-large | [Kronos-Tokenizer-base](https://huggingface.co/NeoQuasar/Kronos-Tokenizer-base) | 512            | 499.2M | ❌                                                                         |

## ⚡ Institutional Quant Terminal & Multi-Agent Futures Platform

Kronos has been extended into a complete **Institutional Multi-Agent Algorithmic Trading Platform** designed for Binance USDⓈ-M Perpetual Futures and Spot markets.

### Key Capabilities

* **Unified Multi-Speed Trading Cockpits (http://localhost:7070):**
  * **Macro Dashboard (/):** Real-time composite market breadth ($>60\%$ Bull Expansion, $<40\%$ Bear Distribution), 24h VWAP leaderboard, perpetual funding carry radar, macroeconomic news blackout shield (FOMC/CPI event protection), Paper Performance Audit Report, and the **1-Year Rolling Monthly Asset Activity & Profitability Matrix** (Bought/Sold counts per asset per month, intensity-scaled green when profitable, across Live, Tiger, and Paper sources).
* **Previous-UTC-Day Volume Profile Spatial Veto & AWS Live Quota Guard (`src/quant/volume_profile.py`):**
  * Pure-`Decimal` zero-lookahead Fixed-Range Volume Profile (`pPOC`, `pVAH`, `pVAL`, HVN/LVN density) cached once per UTC day (`< 10 KB` RAM on AWS `t3.micro`).
  * Empirically validated on 293 real closed Binance Futures trades (`p = 0.0034`, `+286%` counterfactual net PnL): blocks entries firing directly into opposing `pPOC` (`VP_FIRING_INTO_POC`) or High-Volume Node chop zones (`VP_HVN_CHOP`), plus `VP_FADING_BREAKOUT` protection in Stalking Tiger.
  * Persistent live trade-quota auto-pause circuit breaker on AWS (`POST /api/live/toggle` with `trade_cap`). See [`docs/VOLUME_PROFILE_SPATIAL_VETO_AND_DASHBOARD_MATRIX.md`](docs/VOLUME_PROFILE_SPATIAL_VETO_AND_DASHBOARD_MATRIX.md).
  * **Kronos Forecast Workstation (/workstation):** Institutional Bloomberg-style 6-panel workstation with Market Watch, Main Chart + Shaded Purple Forecast Corridor (NEXT 15 BARS, (\text{up}) = 69\%$), streaming Time & Sales tape, Agent Debate (Bull vs Bear FIE), Execution View with Volume Profile & CVD, Monte Carlo Fan (6,000 Sampled Paths), and 3D Param Sweep Sharpe terrain.
  * **Quant Bot Control Cockpit (/bot):** Small-account micro-trading engine (.00 USDT equity baseline, 1.5% max risk budget), continuous autonomous background scanning daemon, full state persistence across restarts (data/paper_trading_state.json and data/bot_settings.json), live KEV.ai 6-point veto gate audits, and rolling Brier learning memory.
  * **Dedicated Lightning Scalper Cockpit (/scalper):** Autonomous high-frequency microstructural execution engine with independent rules, strategies, and guardrails. Scans the Whole-Binance perpetual universe (300+ pairs) via array streams (!forceOrder@arr), executing 3 alpha edges (Liquidation Vacuum, Lead-Lag Delta, Stoikov Micro-Price) with .00 ringfenced isolated margin (4x), 15-minute post-exit quarantine, and institutional two-tier profit ratchets.
* **Asymmetric Compute & Distillation Pipeline (PC-to-AWS):**
  * **Heavy Research on PC:** 46-item microstructural TCA decomposition (MFE, MAE, Realization Tax Drag bps), deterministic root-cause diagnosis, and Bayesian parameter recalibration run on Local PC.
  * **Lean Execution on AWS EC2:** AWS node (13.63.158.94) runs ultra-lean (<105MB RAM, zero heavy ML loops) and hot-reloads distilled decision rules (data/scalper_distilled_rules.json) on the fly with zero service restarts and zero downtime.
  * **CLI Distillation Engine:** python scripts/distill_scalper_learning.py --sync-aws.
* **Tsunami Storm Adaptive Protocol (Rough Seas & Black Swan Defense):**
  * **3-Phase Adaptive State Machine:** Automatically detects violent shocks (BTC 5m velocity $\ge 2\%$, 5m range $\ge 3\%$, market breadth collapse $<15\%$ or $>85\%$, or macroeconomic news catalysts) and triggers protective protocol.
  * **Phase 1 Shock Pause (First 15m):** Strict VETO on all new entries. Lets falling knives and sudden liquidation wicks clear without catching wicks.
  * **Phase 2 Focused Caution (Minutes 15-60):** Fleet capacity is strictly clamped to **1 Macro Position and 1 Scalp Position** (down from 6 Macro / 3 Scalp), elevating win probability requirement to $\ge 75.0\%$ with Mark-Price stops.
  * **Phase 3 Calm Water Auto-Recovery:** Automatically reverts to expanded fleet capacity (6 Macro / 3 Scalp) after 60 minutes once turbulence normalizes (zero restarts required).
  * **Exchange-Native Mark-Price Anti-Wick Protection:** Stop-Loss brackets dispatch with `workingType: "MARK_PRICE"`, protecting isolated stops against single-exchange needle wicks while preserving contract price Take-Profits.
  * **Interactive Cockpit Telemetry:** Live topbar indicator (`#topbar-storm-pill`) displaying ocean state, countdown timers, and instant manual override capability (`🌊 CALM WATERS (6M / 3S)`).
* **Specialized Advisory Consultant & Tri-Perspective ACR (`src/quant/advisory_consultant.py`):**
  * **Adversarial Conviction Ratio ($ACR$):** Pure `Decimal` mathematical formulation synthesizing multi-perspective analysis:
    $$ACR = \frac{C_{\text{bull}} \times (1 - P_{\text{bear}})}{1 + R_{\text{drag}}}$$
  * **Decoupled Out-of-Band Audit:** Runs completely asynchronously without adding execution latency to the 24/7 AWS worker loop.
  * **Multi-Perspective Cross-Examination:** Cross-examines Bullish Conviction ($C_{\text{bull}}$: OBI, Stoikov micro-price skew) against Bearish Hazard ($P_{\text{bear}}$: Volume Profile $pPOC$ ceilings, funding drag) and Frictional Drag ($R_{\text{drag}}$: VIP0 taker fees + slippage).
  * **Autonomous Post-Trade Reflection:** Decomposes realized trade returns against the Bitcoin benchmark ($\alpha = R_{\text{trade}} - R_{\text{BTC}}$) and records structured 2-sentence empirical lessons to `data/consultant_lessons.jsonl`.
  * **CLI Consultant Engine:** `python scripts/run_consultant_assessment.py --symbol SOLUSDT` or `--all`.
* **Portfolio Concurrency Allocation & Discretionary Owner Overrides:**
  * **Expanded Fleet Ceiling (Max 9 Trades):** Up to **6 concurrent Macro positions + 3 Scalp positions** (Tiger + Apex) across the entire universe, with total active margin exposure bounded and managed via `RiskEngine` atomic ledger reservations.
  * **Discretionary Owner Manual Sell Override (1-Hour Lockout):** When the owner manually closes or sells an active position (e.g. BTC/ETH on Binance or WebUI) to reallocate capital to other opportunities, an automatic **60-minute post-exit quarantine** (`OWNER_MANUAL_CAPITAL_ROTATION`) locks out all bots from re-entering, preventing algorithmic amnesia and preserving 100% of liberated margin.
  * **50-Trade Session Quota:** Hard session circuit breaker automatically halts new entries upon the 50th completed trade and dispatches an automated SMTP summary email to the operator.
  * **24/7 Anti-Bloat Engine & AWS Headless Tap:** Dynamic RSS monitoring (AWS $<180\text{MB}$, PC $<750\text{MB}$), automatic log truncation (>4MB to 2,500 lines), orphaned buffer cleanup, and SQLite WAL compaction, coupled with zero-whitelist PC dashboard telemetry over an encrypted SSH tunnel.
  * **Joined Scalping Fetch & Binance Depth Quantization:** Sub-second top-5 OBI and Stoikov skew with strict Binance depth snapping `[5, 10, 20, 50, 100]`, candle-boundary TTL invalidation, and 3000ms WebSocket freshness fallback.
  * **Sweetspot Trade Expirations:** Scalps bounded to 10–12m sweetspot with an 8m stagnation cutoff (if unrealized PnL $< +0.15\%$); macro trades bounded to 90m stagnation cutoff (4h maximum duration).
* **Role-Specialized Multi-Agent Architecture:**
  * **Macro Specialists:** Asynchronous event catalyst shield + 8-hour crypto carry monitor.
  * **Tactical Core & Dual-Regime Volatility Adapters:** 12-hour autoregressive trajectory engine with dynamic regime brackets:
    * **Normal / High Volatility (ATR-14 $\ge 1.0\%$):** Target $+1.90\%$ price ($+9.1\%$ Net ROI at 5x), Stop-Loss capped at $-1.10\%$ price ($-5.5\%$ max ROI, RR $1.73:1$).
    * **Slow Volatility / Compression (ATR-14 $< 1.0\%$):** Target $+1.01\%$ price ($+4.65\%$ Net ROI after fees at 5x), Stop-Loss scaled relative to TP at $-0.66\%$ price ($-3.30\%$ Net ROI, RR $1.53:1$) with a hard noise floor to prevent spread choke.
  * **KEV.ai Risk Arbiter & Supreme Veto Gate:** 6-point mathematical veto gate enforcing macro alignment, carry economics, fee hurdles ($0.04\%$), reward/risk $\ge 2.0$, Fractional Kelly dollar sizing, and adversarial Bull/Bear Devil's Advocate stress-tests.
  * **The Learning Governor:** Rolling 48-hour Brier calibration scoring ($0.0\text{x}$ to $1.0\text{x}$ dynamic capital throttle) with persistent SQLite post-mortem logging in `data/lessons.db`.
  * **Atomic Bracket Execution:** Entry limit orders paired with native SL/TP brackets, Anti-Naked-Position Guard (<1,000ms SL confirmation timeout), and 12-hour temporal stale-trade auto-expiry.
* **Rigorous Institutional Invariants:** Strictly adheres to Zero-Float Financial Math (`decimal.Decimal` throughout), Context Slicing Contracts (`tail-sliced df.iloc[-512:]`), and Base Checkpoint Immutability.

### Quickstart

1. **Launch the Unified Trading Terminal:**
   ```bash
   $env:PYTHONIOENCODING="utf-8"  # Windows PowerShell
   python -X utf8 webui/app.py
   ```
   Open your browser at `http://localhost:7070`.

2. **Run Empirical Self-Verification Suite:**
   ```bash
   python -m pytest tests/ -q
   ```

3. **Simulate Tsunami Shock & High-Wave Adaptation:**
   ```bash
   python scripts/simulate_tsunami_shock.py
   ```

### Documentation Links
* 🐅 [Stalking Tiger Scalping Architecture Manual](docs/TIGER_SCALPER_ARCHITECTURE.md)
* 🛡️ [Institutional Microstructure Risk & Champion Selection Manual](docs/INSTITUTIONAL_MICROSTRUCTURE_RISK_AND_CHAMPION_SELECTION.md)
* 🚪 [Portfolio Concurrency Expansion (6M/3S) & Discretionary Owner Manual Sell Manual](docs/PORTFOLIO_CONCURRENCY_EXPANSION_AND_OWNER_OVERRIDE.md)
* 🧠 [Specialized Advisory Consultant & Tri-Perspective ACR Manual](docs/ADVISORY_CONSULTANT_AND_TRI_PERSPECTIVE_ACR.md)
* 🌊 [Tsunami Storm Adaptive Protocol Manual](docs/TSUNAMI_STORM_ADAPTIVE_PROTOCOL.md)
* 📊 [Previous-UTC-Day Volume Profile Spatial Veto Manual](docs/VOLUME_PROFILE_SPATIAL_VETO_AND_DASHBOARD_MATRIX.md)
* ⚡ [Lightning Scalper Architecture & Distillation Manual](docs/LIGHTNING_SCALPER_ARCHITECTURE.md)
* 📘 [Quant Architecture Specification](docs/ARCHITECTURE.md)
* 🖥️ [Unified Terminal User Guide](docs/UNIFIED_TERMINAL_GUIDE.md)
* 📑 [Master Binance Futures Bot Guide](docs/KRONOS_BINANCE_FUTURES_BOT_GUIDE.md)


## 🚀 Getting Started

### Installation

1. Install Python 3.10+, and then install the dependencies:

```shell
pip install -r requirements.txt
```

### 📈 Making Forecasts

Forecasting with Kronos is straightforward using the `KronosPredictor` class. It handles data preprocessing, normalization, prediction, and inverse normalization, allowing you to get from raw data to forecasts in just a few lines of code.

**Important Note**: The `max_context` for `Kronos-small` and `Kronos-base` is **512**. This is the maximum sequence length the model can process. For optimal performance, it is recommended that your input data length (i.e., `lookback`) does not exceed this limit. The `KronosPredictor` will automatically handle truncation for longer contexts.

Here is a step-by-step guide to making your first forecast.

#### 1. Load the Tokenizer and Model

First, load a pre-trained Kronos model and its corresponding tokenizer from the Hugging Face Hub.

```python
from model import Kronos, KronosTokenizer, KronosPredictor

# Load from Hugging Face Hub
tokenizer = KronosTokenizer.from_pretrained("NeoQuasar/Kronos-Tokenizer-base")
model = Kronos.from_pretrained("NeoQuasar/Kronos-small")
```

#### 2. Instantiate the Predictor

Create an instance of `KronosPredictor`, passing the model, tokenizer, and desired device.

```python
# Initialize the predictor
predictor = KronosPredictor(model, tokenizer, max_context=512)
```

#### 3. Prepare Input Data

The `predict` method requires three main inputs:
-   `df`: A pandas DataFrame containing the historical K-line data. It must include columns `['open', 'high', 'low', 'close']`. `volume` and `amount` are optional.
-   `x_timestamp`: A pandas Series of timestamps corresponding to the historical data in `df`.
-   `y_timestamp`: A pandas Series of timestamps for the future periods you want to predict.

```python
import pandas as pd

# Load your data
df = pd.read_csv("./data/XSHG_5min_600977.csv")
df['timestamps'] = pd.to_datetime(df['timestamps'])

# Define context window and prediction length
lookback = 400
pred_len = 120

# Prepare inputs for the predictor
x_df = df.loc[:lookback-1, ['open', 'high', 'low', 'close', 'volume', 'amount']]
x_timestamp = df.loc[:lookback-1, 'timestamps']
y_timestamp = df.loc[lookback:lookback+pred_len-1, 'timestamps']
```

#### 4. Generate Forecasts 

Call the `predict` method to generate forecasts. You can control the sampling process with parameters like `T`, `top_p`, and `sample_count` for probabilistic forecasting.

```python
# Generate predictions
pred_df = predictor.predict(
    df=x_df,
    x_timestamp=x_timestamp,
    y_timestamp=y_timestamp,
    pred_len=pred_len,
    T=1.0,          # Temperature for sampling
    top_p=0.9,      # Nucleus sampling probability
    sample_count=1  # Number of forecast paths to generate and average
)

print("Forecasted Data Head:")
print(pred_df.head())
```

The `predict` method returns a pandas DataFrame containing the forecasted values for `open`, `high`, `low`, `close`, `volume`, and `amount`, indexed by the `y_timestamp` you provided.

For efficient processing of multiple time series, Kronos provides a `predict_batch` method that enables parallel prediction on multiple datasets simultaneously. This is particularly useful when you need to forecast multiple assets or time periods at once.

```python
# Prepare multiple datasets for batch prediction
df_list = [df1, df2, df3]  # List of DataFrames
x_timestamp_list = [x_ts1, x_ts2, x_ts3]  # List of historical timestamps
y_timestamp_list = [y_ts1, y_ts2, y_ts3]  # List of future timestamps

# Generate batch predictions
pred_df_list = predictor.predict_batch(
    df_list=df_list,
    x_timestamp_list=x_timestamp_list,
    y_timestamp_list=y_timestamp_list,
    pred_len=pred_len,
    T=1.0,
    top_p=0.9,
    sample_count=1,
    verbose=True
)

# pred_df_list contains prediction results in the same order as input
for i, pred_df in enumerate(pred_df_list):
    print(f"Predictions for series {i}:")
    print(pred_df.head())
```

**Important Requirements for Batch Prediction:**
- All series must have the same historical length (lookback window)
- All series must have the same prediction length (`pred_len`)
- Each DataFrame must contain the required columns: `['open', 'high', 'low', 'close']`
- `volume` and `amount` columns are optional and will be filled with zeros if missing

The `predict_batch` method leverages GPU parallelism for efficient processing and automatically handles normalization and denormalization for each series independently.

#### 5. Example and Visualization

For a complete, runnable script that includes data loading, prediction, and plotting, please see [`examples/prediction_example.py`](examples/prediction_example.py).

Running this script will generate a plot comparing the ground truth data against the model's forecast, similar to the one shown below:

<p align="center">
    <img src="figures/prediction_example.png" alt="Forecast Example" align="center" width="600px" />
</p>

Additionally, we provide a script that makes predictions without Volume and Amount data, which can be found in [`examples/prediction_wo_vol_example.py`](examples/prediction_wo_vol_example.py).


## 🔧 Finetuning on Your Own Data (A-Share Market Example)

We provide a complete pipeline for finetuning Kronos on your own datasets. As an example, we demonstrate how to use [Qlib](https://github.com/microsoft/qlib) to prepare data from the Chinese A-share market and conduct a simple backtest.

> **Disclaimer:** This pipeline is intended as a demonstration to illustrate the finetuning process. It is a simplified example and not a production-ready quantitative trading system. A robust quantitative strategy requires more sophisticated techniques, such as portfolio optimization and risk factor neutralization, to achieve stable alpha.

The finetuning process is divided into four main steps:

1.  **Configuration**: Set up paths and hyperparameters.
2.  **Data Preparation**: Process and split your data using Qlib.
3.  **Model Finetuning**: Finetune the Tokenizer and the Predictor models.
4.  **Backtesting**: Evaluate the finetuned model's performance.

### Prerequisites

1.  First, ensure you have all dependencies from `requirements.txt` installed.
2.  This pipeline relies on `qlib`. Please install it:
    ```shell
      pip install pyqlib
    ```
3.  You will need to prepare your Qlib data. Follow the [official Qlib guide](https://github.com/microsoft/qlib) to download and set up your data locally. The example scripts assume you are using daily frequency data.

### Step 1: Configure Your Experiment

All settings for data, training, and model paths are centralized in `finetune/config.py`. Before running any scripts, please **modify the following paths** according to your environment:

*   `qlib_data_path`: Path to your local Qlib data directory.
*   `dataset_path`: Directory where the processed train/validation/test pickle files will be saved.
*   `save_path`: Base directory for saving model checkpoints.
*   `backtest_result_path`: Directory for saving backtesting results.
*   `pretrained_tokenizer_path` and `pretrained_predictor_path`: Paths to the pre-trained models you want to start from (can be local paths or Hugging Face model names).

You can also adjust other parameters like `instrument`, `train_time_range`, `epochs`, and `batch_size` to fit your specific task. If you don't use [Comet.ml](https://www.comet.com/), set `use_comet = False`.

### Step 2: Prepare the Dataset

Run the data preprocessing script. This script will load raw market data from your Qlib directory, process it, split it into training, validation, and test sets, and save them as pickle files.

```shell
python finetune/qlib_data_preprocess.py
```

After running, you will find `train_data.pkl`, `val_data.pkl`, and `test_data.pkl` in the directory specified by `dataset_path` in your config.

### Step 3: Run the Finetuning

The finetuning process consists of two stages: finetuning the tokenizer and then the predictor. Both training scripts are designed for multi-GPU training using `torchrun`.

#### 3.1 Finetune the Tokenizer

This step adjusts the tokenizer to the data distribution of your specific domain.

```shell
# Replace NUM_GPUS with the number of GPUs you want to use (e.g., 2)
torchrun --standalone --nproc_per_node=NUM_GPUS finetune/train_tokenizer.py
```

The best tokenizer checkpoint will be saved to the path configured in `config.py` (derived from `save_path` and `tokenizer_save_folder_name`).

#### 3.2 Finetune the Predictor

This step finetunes the main Kronos model for the forecasting task.

```shell
# Replace NUM_GPUS with the number of GPUs you want to use (e.g., 2)
torchrun --standalone --nproc_per_node=NUM_GPUS finetune/train_predictor.py
```

The best predictor checkpoint will be saved to the path configured in `config.py`.

### Step 4: Evaluate with Backtesting

Finally, run the backtesting script to evaluate your finetuned model. This script loads the models, performs inference on the test set, generates prediction signals (e.g., forecasted price change), and runs a simple top-K strategy backtest.

```shell
# Specify the GPU for inference
python finetune/qlib_test.py --device cuda:0
```

The script will output a detailed performance analysis in your console and generate a plot showing the cumulative return curves of your strategy against the benchmark, similar to the one below:

<p align="center">
    <img src="figures/backtest_result_example.png" alt="Backtest Example" align="center" width="700px" />
</p>

### 💡 From Demo to Production: Important Considerations

*   **Raw Signals vs. Pure Alpha**: The signals generated by the model in this demo are raw predictions. In a real-world quantitative workflow, these signals would typically be fed into a portfolio optimization model. This model would apply constraints to neutralize exposure to common risk factors (e.g., market beta, style factors like size and value), thereby isolating the **"pure alpha"** and improving the strategy's robustness.
*   **Data Handling**: The provided `QlibDataset` is an example. For different data sources or formats, you will need to adapt the data loading and preprocessing logic.
*   **Strategy and Backtesting Complexity**: The simple top-K strategy used here is a basic starting point. Production-level strategies often incorporate more complex logic for portfolio construction, dynamic position sizing, and risk management (e.g., stop-loss/take-profit rules). Furthermore, a high-fidelity backtest should meticulously model transaction costs, slippage, and market impact to provide a more accurate estimate of real-world performance.

> **📝 AI-Generated Comments**: Please note that many of the code comments within the `finetune/` directory were generated by an AI assistant (Gemini 2.5 Pro) for explanatory purposes. While they aim to be helpful, they may contain inaccuracies. We recommend treating the code itself as the definitive source of logic.

## 🏛️ Institutional System Documentation

Comprehensive architecture, quantitative risk invariants, and deployment guides are maintained in the [`docs/`](./docs) directory:
* **[Master Documentation Index](./docs/INDEX.md)**: Master portal to all 11 quantitative subsystem guides.
* **[System Architecture (v2.5.0)](./docs/ARCHITECTURE.md)**: End-to-end design, foundation models, KEV.ai 7-point veto gates, and learning governor.
* **[Real Live Trading & Mutual Exclusion Guide](./docs/REAL_LIVE_TRADING_AND_MUTUAL_EXCLUSION_GUIDE.md)**: Binance USD(S)-M Futures live execution, isolated margin, BNB fee discount, and anti-flicker telemetry.
* **[Standalone 24/7 Deployment Guide](./docs/STANDALONE_24_7_DEPLOYMENT_GUIDE.md)**: Decoupled supervisor daemon, Windows Task Scheduler auto-start, and one-click controls.
* **[Agentic Memory Architecture & Evaluation](./docs/AGENTIC_MEMORY_ARCHITECTURE.md)**: The 7 types of agent memory, 4 active lean production memories, and deferred bloat evaluation.

## 📖 Citation

If you use Kronos in your research, we would appreciate a citation to our [paper](https://arxiv.org/abs/2508.02739):

```
@misc{shi2025kronos,
      title={Kronos: A Foundation Model for the Language of Financial Markets}, 
      author={Yu Shi and Zongliang Fu and Shuo Chen and Bohan Zhao and Wei Xu and Changshui Zhang and Jian Li},
      year={2025},
      eprint={2508.02739},
      archivePrefix={arXiv},
      primaryClass={q-fin.ST},
      url={https://arxiv.org/abs/2508.02739}, 
}
```

## 📜 License 
This project is licensed under the [MIT License](./LICENSE).










