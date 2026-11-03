# Kronos Quantitative Systems — Master Documentation Suite

Welcome to the institutional documentation repository for **Kronos**, an autonomous, multi-agent quantitative trading and forecasting system built for crypto perpetual futures and spot universe execution.

---

## 📚 Core Documentation Index

| Document | Primary Focus | Key Topics Covered |
| :--- | :--- | :--- |
| **[1. System Architecture](file:///F:/012D_TRADE/Kronos/docs/ARCHITECTURE.md)** | End-to-End System Design | Foundation Model, KEV.ai 6-Point Veto Gate, Learning Governor, Micro-Trading Budget, Failsafe Brackets, 24/7 Autopilot. |
| **[2. Dynamic Chart & Multi-Pane Workstation](file:///F:/012D_TRADE/Kronos/docs/DYNAMIC_INSTITUTIONAL_CHART_SYSTEM.md)** | Neural Forecaster Workstation | Drag-to-Pan 2D Physics, Golden Monte Carlo Fan (1,000 Futures), EMA 7/21 & VWAP Overlays, Heat Map Depth, CVD Flow, Agent Sim Log, One-Click Order Dispatch. |
| **[3. Realistic Paper Trading & 24/7 Operations](file:///F:/012D_TRADE/Kronos/docs/REALISTIC_PAPER_TRADING_AND_24_7_OPERATIONS.md)** | Realistic Execution & Memory | Maker/Taker Fees (VIP0), Entry & Adverse SL Slippage, 12h Temporal Expiry, 8h Funding Drag, State Persistence Across Restarts. |
| **[4. Gemini Free Tier Quota & Rate Limit Guide](file:///F:/012D_TRADE/Kronos/docs/GEMINI_FREE_TIER_RATE_LIMITS_AND_QUOTA_GUIDE.md)** | Strategic AI Copilot Governance | 1,500 RPD / 15 RPM Free Tier Math, Architectural Separation (Local Execution vs Remote Meta-Strategy), Zero Disruption Fallback. |
| **[5. Unified Terminal Operator Guide](file:///F:/012D_TRADE/Kronos/docs/UNIFIED_TERMINAL_GUIDE.md)** | Web UI Operations (`:7070`) | Single-Page Application (SPA), Dashboard Telemetry, Forecaster Navigation, Bot & Arbiter Cockpit, Multi-Asset Switching. |
| **[6. Binance Futures Bot Engineering Guide](file:///F:/012D_TRADE/Kronos/docs/KRONOS_BINANCE_FUTURES_BOT_GUIDE.md)** | Quantitative Execution Core | Binance USDⓈ-M Futures REST/WS Gateway, Precision Quantization, Atomic State Machine, Stale-Trade Mitigation. |

---

## 🏛️ Kronos Architectural Invariants

Every subsystem and component in Kronos is strictly bound by these foundational quant invariants:

1. **Zero Float Financial Math:**
   - IEEE 754 floating-point math (`float` / `number`) is strictly forbidden for financial calculations, order sizes, account balances, fees, or execution PnL.
   - All monetary values utilize `decimal.Decimal` (e.g. `Decimal(str(price))`).
2. **Context Slicing Contract:**
   - Context lookbacks fed to `KronosPredictor` or `KronosTokenizer` are tail-sliced (`df.iloc[-512:].copy()`), guaranteeing recent price action is never dropped.
3. **Base Checkpoint Immutability:**
   - Pre-trained Hugging Face checkpoints (`NeoQuasar/Kronos-mini`, `NeoQuasar/Kronos-small`, `NeoQuasar/Kronos-base`, `NeoQuasar/Kronos-Tokenizer-base`) are strictly read-only.
4. **Autonomous Self-Verification Loop (ASVL) & Rule-of-2:**
   - No speculative assumptions; all logic is validated via empirical CLI test suites (`python -m pytest tests/test_smoke.py -q` and `python -m pytest tests/ -q`).
5. **Zero Credit Burning & Token Hygiene:**
   - Local high-frequency model execution runs on local hardware/ONNX. Remote LLM calls are reserved solely for high-level meta-strategy governance, preserving 98%+ of free tier daily quotas.

---

## 🚀 Quick Start Guide

### Launching the Unified Terminal & 24/7 Autopilot
```bash
# Activate environment
cd F:\012D_TRADE\Kronos

# Start the Web UI and background autopilot daemon
python -X utf8 webui/app.py
```
Open your browser to:
👉 **`http://localhost:7070`**

### Running Empirical Verification
```bash
# Fast Smoke Check (<4 seconds)
python -m pytest tests/test_smoke.py -q

# Full Regression Suite (58 unit & integration tests)
python -m pytest tests/ -q
```
