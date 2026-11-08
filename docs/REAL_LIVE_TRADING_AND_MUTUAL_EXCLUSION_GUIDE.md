# Real Live Trading & Mutual Exclusion Guide — Kronos Institutional Workstation

This guide details the complete production architecture for **Real Live Trading** on Binance USD(S)-M Futures within the Kronos quantitative trading platform.

---

## 1. Architectural Philosophy & Quantitative Invariants

To transition safely from paper simulation to real capital execution without endangering the account balance, Kronos enforces five institutional invariants:

1. **Zero Float Financial Math (`AGENTS.md Invariant 1`):**  
   Every balance check, margin ratio calculation, order quantity sizing, stop-loss/take-profit bracket, and realized PnL calculation is executed strictly using `decimal.Decimal`. No IEEE 754 floating-point operations touch real money.
2. **Small-Account Micro-Lot Ceilings:**  
   For small trading accounts ($\le \$2,500$ USDT balance), trade notional sizes are hard-capped between **\$15.00 and \$50.00 USDT per position**. High Kelly fractions are damped to prevent ruin.
3. **Mandatory Isolated Margin (`ISOLATED`):**  
   Before dispatching any live market order, the execution gateway explicitly calls `POST /fapi/v1/marginType` to ensure `ISOLATED` mode. Cross-collateral margin is strictly forbidden, ensuring that a tail event on one coin cannot liquidate the entire wallet.
4. **Leverage Clamping ($\le 5\text{x}$):**  
   Account leverage is clamped to a maximum of $5\text{x}$ (default: $2\text{x} - 3\text{x}$).
5. **Anti-Naked-Position Guard:**  
   When an entry order fills on Binance, simultaneous `STOP_MARKET` and `TAKE_PROFIT_MARKET` brackets are dispatched immediately. If the exchange fails to confirm the stop-loss order within 1,000ms, the engine triggers an automatic market closure (`reduceOnly=true`) to eliminate unhedged exposure.

---

## 2. Dedicated Live Trading Page & Web UI Layout

The Kronos Web UI (`http://127.0.0.1:7070`) features two distinct trading workstations accessible from the top navigation bar:

- **`🤖 Paper Quant Bot` (`#tab-bot` / `#view-bot`):** Simulated execution using paper ledger and local state (`data/paper_trading_state.json`).
- **`🔴 Real Live Trading` (`#tab-live` / `#view-live`):** Authenticated live futures workstation connected directly to Binance USD(S)-M Futures via signed HMAC-SHA256 REST endpoints.

### Real Reports & Live Telemetry
The Live Trading page queries Binance in real time and renders:
1. **Total Futures Wallet Balance (`/fapi/v2/account`):** Live cash collateral in USDT.
2. **Available Margin Collateral:** Capital available for new micro-lot allocations.
3. **Total Unrealized PnL:** Mark-to-market valuation across all live open contracts.
4. **Maintenance Margin Ratio (%):** Live liquidation safety gauge:
   - `< 20%`: **SAFE** (Green badge)
   - `20% - 50%`: **MODERATE** (Amber badge)
   - `> 50%`: **CRITICAL RISK** (Red badge)
5. **BNB Fee Deduction Buffer:** Live audit of BNB balance in the Futures wallet. When balance $\ge 0.001\text{ BNB}$, the system displays `⚡ 10% DISCOUNT ACTIVE`, cutting taker fees by 10%.
6. **Active Live Positions Table (`/fapi/v2/positionRisk`):** Symbol, side, position size, notional value, entry price, live mark price, liquidation price, margin mode (`ISOLATED`), leverage, and individual one-click `[Close]` button.
7. **Live Fill & Trade History (`/fapi/v1/userTrades`):** Real exchange fills, timestamps, order IDs, realized PnL, and exchange commission fees (USDT/BNB).
8. **Anti-Flicker Telemetry & DOM Diffing:** Backend TTL caching (15s trade cache, 3s account cache) combined with frontend signature diffing (`tradesSig`, `posSig`), eliminating browser table flicker and reducing Binance API weight by ~90%.
9. **Emergency Market Flatten (`🛑 EMERGENCY FLATTEN ALL LIVE`):** One-click fail-safe that cancels all active open orders (`DELETE /fapi/v1/allOpenOrders`) and executes market closures (`reduceOnly=true`) across all held positions.

---

## 3. Strict Mutual Exclusion Architecture

### Why Mutual Exclusion is Mandatory
Running paper trading and real live trading concurrently in the same background daemon causes:
- **CPU & GPU Resource Contention:** Duplicate ONNX inference runs and dual market breadth calculations.
- **Binance Rate-Limit Burning:** Exceeding IP request weight limits (1,200 req/min) by redundantly polling candlesticks and orderbooks.
- **Operational & Risk Confusion:** Ambiguity over whether a signal triggered simulated paper equity or real live USDT.

### The Mutual Exclusion Daemon Loop
In [`webui/app.py`](file:///F:/012D_TRADE/Kronos/webui/app.py), the background autopilot worker implements strict priority routing:

```python
while True:
    with live_account_lock:
        live_active = live_trading_enabled
        live_int = live_trading_interval
    with bot_autopilot_lock:
        paper_active = bot_autopilot_enabled
        paper_int = bot_autopilot_interval

    # Strict Mutual Exclusion: If LIVE trading is enabled, PAPER is forced paused!
    if live_active:
        for _ in range(int(live_int)):
            if not live_trading_enabled:
                break
            time.sleep(1)

        if live_trading_enabled:
            _execute_live_bot_cycle()

    elif paper_active:
        for _ in range(int(paper_int)):
            if not bot_autopilot_enabled or live_trading_enabled:
                break
            time.sleep(1)

        if bot_autopilot_enabled and not live_trading_enabled:
            _execute_quant_bot_cycle()
    else:
        time.sleep(2)
```

### Bidirectional Toggle Safeguards
- Activating Real Live Trading (`POST /api/live/toggle`) automatically sets `bot_autopilot_enabled = False` and persists the state to `data/bot_settings.json`.
- Resuming Paper Trading (`POST /api/bot/autopilot/toggle`) automatically sets `live_trading_enabled = False`, ensuring real capital is never dispatched accidentally while running simulations.

---

## 4. Shared Brain vs Partitioned Learning (User Clarification)

> **User Inquiry:** *"The brains, and onnx, learning is shared between paper and live real trade (comment in this if wrong)"*

### Quantitative Verdict: **CORRECT — Unified Intelligence with Partitioned Calibration**

1. **The Shared Neural Brain (Unified):**
   - The deep sequence ONNX model weights (`models/`), feature extractors, 24h VWAP volume profile, and systemic market breadth calculators are **100% shared and universal**.
   - The KEV.ai 6-Point Supreme Veto Gate enforces identical institutional standards across both modes:
     - **Gate 1:** Macro News Blackout Shield (CPI, FOMC, NFP protection).
     - **Gate 2:** Macro Breadth Index ($>60\%$ bullish regime alignment).
     - **Gate 3:** Net Expected Edge Hurdle ($\ge 0.50\%$ after commission).
     - **Gate 4:** Funding Rate Drag ($\le 0.03\%$ 8h carry cost).
     - **Gate 5:** Pairwise Correlation Ceiling ($\rho < 0.85$ to prevent concentration).
     - **Gate 6:** Reward-to-Risk Hurdle ($R:R \ge 1.50$).

2. **The Partitioned Bayesian Learning Engine (`data/lessons.db`):**
   - While paper simulations provide high-frequency statistical observations, **real live executions carry real slippage, liquidity queues, and cash exchange fees**.
   - To reflect this empirical reality, the `LearningGovernor` in [`src/quant/learning_governor.py`](file:///F:/012D_TRADE/Kronos/src/quant/learning_governor.py) partitions trade records by `execution_mode`:
     ```python
     # Live capital outcomes receive 2.5x priority weighting
     weight = Decimal("2.5") if outcome.execution_mode == "LIVE" else Decimal("1.0")
     ```
   - When calculating the Brier calibration score and dynamic sizing confidence multiplier:
     - Real live wins and losses shape future Kelly sizing **$2.5\times$ more aggressively** than paper trades.
     - A live loss due to exchange slippage immediately reins in live sizing multipliers without waiting for dozens of paper trades.

---

## 5. REST API Reference

| Endpoint | Method | Description |
| :--- | :--- | :--- |
| `/api/live/status` | `GET` | Returns live account balance, margin ratio, active positions, and autopilot status |
| `/api/live/toggle` | `POST` | Toggles live trading on/off; automatically forces paper autopilot off when enabled |
| `/api/live/scan` | `POST` | Triggers an immediate universe scan and evaluates live candidates against KEV gates |
| `/api/live/flatten` | `POST` | Cancels all open orders and emergency market flattens all live positions on Binance |
| `/api/live/trades` | `GET` | Fetches recent real trade executions with realized PnL and exchange fees |
| `/api/live/place-order` | `POST` | Dispatches a manual micro-lot bracket order with isolated margin validation |

---

## 6. Pre-Live Verification Checklist

Before toggling Real Live Trading to `ON`:
1. [x] **API Permissions:** Confirm Binance API key has **Futures Trading ENABLED** and **Withdrawals DISABLED**.
2. [x] **IP Whitelisting:** For institutional security, bind the API key to your static IP address in Binance API Management.
3. [x] **Margin Mode Check:** Confirm collateral currency is USDT (USD(S)-M Futures wallet).
4. [x] **Quant Flaw Audit:** Run `python scripts/audit_quant_flaws.py` to verify zero math flaws or lookahead anomalies.
5. [x] **ASVL Smoke Verification:** Run `python -m pytest tests/test_smoke.py -q`.

---

## 7. Live Temporal Sweeper & Stale Trade Protection (Lesson #17)

To prevent collateral dead-lock and protect against alpha decay and macro regime inversion:
- **Automatic 12-Hour Expiry:** The live orchestrator continuously inspects `updateTime` on open Binance positions via `sweep_live_temporal_exits()`.
- **Market Flattening:** Any position open for $\ge 12\text{ hours}$ without triggering its Take-Profit or Stop-Loss bracket is automatically market-flattened (`reduceOnly=true`).
- **Collateral Recycling:** Margin is instantly returned to free collateral, enabling the engine to trade active regime-aligned setups.
- **Post-Mortem Documentation:** See [`docs/INCIDENT_POSTMORTEM_STALE_TRADE_LOCK_AND_TEMPORAL_DECAY.md`](file:///F:/012D_TRADE/Kronos/docs/INCIDENT_POSTMORTEM_STALE_TRADE_LOCK_AND_TEMPORAL_DECAY.md) for complete mathematical proofs and empirical findings.
