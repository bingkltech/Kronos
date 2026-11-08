# Unified Trade Forensics & Post-Mortem Architecture

## Overview
This module (`src/quant/trade_forensics.py`) operationalizes the **46-item Unified Trade Assessment Framework** and institutional post-mortem diagnostics for Kronos.

It provides:
1. `TelemetryRecord`: Strict `Decimal` container for all 46 parameters across Accounting, Bot Intent, Market Snapshot, Microstructure, In-Trade Excursion, and Diagnosis.
2. `TradeForensicsEngine`: Evaluates whether the bot accurately guessed the outcome, separates predictive alpha from execution drag, categorizes failures into deterministic root causes, and applies asymmetric live vs. paper weights.
3. `Post-Mortem Lessons Registry`: Permanent institutional memory persisted in `data/lessons.db` via `scripts/lessons.py`.

---

## 46-Item Unified Trade Telemetry Framework

Every completed trade—whether executed on paper simulation or real live Binance USD(S)-M Futures—is captured across 6 diagnostic dimensions:

| Dimension | Key Parameters | Quant Purpose |
| :--- | :--- | :--- |
| **1. Accounting & Identity** | `trade_id`, `symbol`, `side`, `leverage`, `margin_mode`, `execution_mode`, `entry_time`, `exit_time`, `duration_seconds` | Strict capital tracking, fee tier reconciliation, and duration auditing. |
| **2. Bot Intent & Target** | `forecast_confidence`, `predicted_drift_pct`, `planned_tp`, `planned_sl`, `planned_r_multiple`, `bracket_type` | Validates neural trajectory intent vs. actual price realization. |
| **3. Market Snapshot at Entry** | `macro_regime`, `breadth_pct`, `funding_rate_8h`, `basis_spread_bps`, `volatility_atr_14`, `vwap_distance_bps` | Captures systemic environment at moment of capital commitment. |
| **4. Microstructure & Quality** | `bid_ask_spread_bps`, `orderbook_imbalance_50`, `maker_taker_status`, `entry_slippage_bps`, `exit_slippage_bps`, `commission_paid_usd` | Isolates exchange friction, adverse selection, and fee drag. |
| **5. In-Trade Excursions** | `maximum_favorable_excursion_pct` (MFE), `maximum_adverse_excursion_pct` (MAE), `realized_r_multiple`, `pnl_usd` | Determines if entry was timed correctly and if stops/targets were prematurely hit or left on table. |
| **6. Deterministic Diagnosis** | `outcome_verdict`, `alpha_efficiency_ratio`, `drag_ratio`, `root_cause_category`, `governor_penalty_applied` | Classifies trade outcome, updates Brier calibration scores, and assigns lessons. |

---

## Failure Root Cause Taxonomy

Every sub-optimal trade or scratch is classified into one of seven deterministic failure modes:

1. **`SLIPPAGE_DRAG`**: Prediction was directionally correct, but entry or exit execution friction destroyed the margin.
2. **`REGIME_MISMATCH`**: Bot entered counter to macro breadth or during an unflagged systemic regime rotation.
3. **`VOLATILITY_WHIPSAW`**: Price moved in the intended direction, but wide intra-candle noise triggered the Stop-Loss first (insufficient ATR buffer).
4. **`ALPHA_DECAY`**: Expected momentum failed to materialize; price drifted sideways until small losses accumulated.
5. **`EXECUTION_DESYNC`**: Network lag, Binance API rate-limit delays, or bracket order mismatch caused adverse entry.
6. **`CARRY_EROSION`**: Long or short position held across multiple 8-hour funding intervals where negative funding rate overwhelmed capital gains.
7. **`TEMPORAL_STALE_LOCK`** *(Lesson #17)*: Position held past the model's predictive alpha horizon (>12–24h, reaching 48h+), freezing account collateral while the underlying market regime inverted.

---

## Active Institutional Lesson #17: Temporal Decay & The 2-Day Stale Trade Lock

```
========================================================================================
[CRITICAL #17] temporal_decay_stale_trade_lock
Category: quant_risk / execution_governance
Trigger:  Position Duration > 12 Hours without TP/SL Trigger
Impact:   Freezes Up to 89% Account Collateral, Decays Alpha to Brownian Noise, Exposes to Regime Inversion
========================================================================================
```

### 1. Empirical Incident Summary
During live Binance Futures operations, real live Short positions in `BTCUSDT` (-0.003 BTC) and `XRPUSDT` (-43.0 XRP) were entered during a macro `BEAR_DISTRIBUTION` regime (16.7% breadth). 

Over the subsequent **54 hours** (> 2.2 days):
- Price never reached either the planned Take-Profit or Stop-Loss brackets.
- The positions generated a stagnant PnL drag of **-$1.17 USDT** (-0.6% on total account).
- **$163.41 USDT out of $182.91 USDT (89.34% of account equity)** was locked as margin collateral, leaving only **$19.50 USDT** in free collateral.
- Systemic market regime rotated 180 degrees into **`BULL_EXPANSION` (80.0% breadth)**, turning a trend-following short into an aggressive counter-trend position.
- The Kronos ONNX Neural Trajectory flipped to **Bullish (+0.37% drift)**, while KEV.ai Arbiter strictly vetoed counter-trend shorts.
- The Apex Scalper was completely starved of free margin, unable to deploy into fresh, high-conviction bullish setups.

---

### 2. The Five Quantitative Pillars of Why >48h Holding is Flawed

#### Pillar 1: Alpha Half-Life ($\tau_{1/2}$) Decay to Brownian Motion
Neural trajectory and autoregressive sequence models (such as Kronos with 512-token context lookbacks) are optimized for short-to-medium horizon momentum ($\Delta t = 15\text{m} \text{ to } 4\text{h}$). 

The predictive information coefficient $\rho(t)$ decays exponentially:
$$\rho(t) = \rho_0 \cdot e^{-\lambda t}, \quad \text{where } \lambda = \frac{\ln(2)}{\tau_{1/2}}$$

For high-frequency crypto momentum scalping, empirical $\tau_{1/2} \approx 4\text{ to } 8\text{ hours}$. 
- At $t = 12\text{h}$, $\rho(t) < 0.25 \rho_0$.
- At $t = 48\text{h}$ (2 days), $\rho(t) \approx 0.01 \rho_0 \approx 0$.

At 48+ hours, the model's conditional expected drift $E[\Delta P \mid \mathcal{M}_{t_0}]$ has degenerated into an unconditional random walk:
$$\Delta P_t = \mu \, dt + \sigma \, dW_t$$
Holding the position is no longer executing a mathematical edge; it is taking uncompensated Brownian variance risk.

#### Pillar 2: Macro Regime Inversion
Financial time-series are strictly non-stationary. Macro breadth and liquidity regimes rotate on multi-hour to multi-day cycles:
- **At Entry:** Regime = `BEAR_DISTRIBUTION` (16.7% universe breadth above VWAP). Entering short carried high confluence.
- **At 54 Hours:** Regime = `BULL_EXPANSION` (80.0% universe breadth, 8/10 assets above VWAP, positive net funding, institutional spot accumulation).

Holding a position past the regime cycle converts an asset with a high Sharpe ratio into an unhedged, negative-drift liability fighting institutional orderflow.

#### Pillar 3: Dead Capital Lock & Asymmetric Opportunity Cost
In quantitative trading, total expected portfolio return is the product of **Edge per Trade** and **Capital Velocity**:
$$\text{Portfolio Alpha} = N_{\text{trades}} \cdot E[\text{Edge}] \cdot \text{Capital Utilization}$$

When 89.34% of collateral ($163.41 USDT) is locked in a stagnant position yielding -$1.17 over 54 hours:
- $N_{\text{trades}}$ drops to zero for 89% of the bankroll.
- The opportunity cost of missing 5 to 10 high-conviction intraday setups (each with 1.5%–3.0% expected value) vastly exceeds the -$1.17 scratch exit cost.

#### Pillar 4: Carry Erosion & Liquidation Drift
Perpetual contracts settle funding fees every 8 hours. Holding an underwater short during a bullish expansion subjects the trade to continuous negative carry (funding fee payments deducted directly from wallet balance). Furthermore, prolonged exposure increases susceptibility to tail-risk liquidation spikes during off-hours volatility.

#### Pillar 5: The Disposition Effect
The human psychological impulse is to "wait for price to bounce back to entry price to exit at break-even". In systematic quantitative trading, this is the classic **Disposition Effect** (holding losers too long while cutting winners too quickly). 

A quantitative system must be completely unattached to past sunk costs: if a trade fails to reach its target within its expected alpha window, the correct mathematical decision is an immediate scratch to recycle capital.

---

### 3. The Institutional Invariant: The 12-Hour Temporal Kill-Switch

To eliminate Stale Trade Locks permanently across both Paper and Live execution:

```python
# Invariant: Hard 12-Hour Stale Expiry
MAX_TRADE_DURATION_HOURS = 12

def evaluate_temporal_exit(position, current_time_utc):
    duration = current_time_utc - position.entry_time_utc
    if duration.total_seconds() >= (MAX_TRADE_DURATION_HOURS * 3600):
        # Trigger immediate atomic market flatten
        flatten_position_market(position.symbol)
        # Record outcome as TEMPORAL_EXIT_12H_STALE
        learning_governor.record_outcome(
            exit_reason="TEMPORAL_EXIT_12H_STALE",
            realized_pnl=position.realized_pnl
        )
```

1. **Maximum Holding Horizon:** Intraday positions have a hard lifetime of **12 hours** (maximum upper bound of 24 hours under low-volatility regimes).
2. **Automatic Market Flatten:** If neither Take-Profit nor Stop-Loss has triggered within 12 hours, the engine automatically issues a market flatten (`reduceOnly=true`) and cancels all open conditional orders.
3. **Collateral Recycling:** Margin is immediately restored to available capital, allowing the orchestrator to deploy into active regime-confluent trades.
4. **Learning Governor Feedback:** The exit is recorded with label `TEMPORAL_EXIT_12H_STALE`, allowing the Bayesian governor to adapt bracket widths and entry filters.
