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
| **[7. Incident Post-Mortem: Ground Truth & Anti-Lookahead](file:///F:/012D_TRADE/Kronos/docs/INCIDENT_POSTMORTEM_TIME_MACHINE_AND_GROUND_TRUTH.md)** | Quant Flaw Post-Mortem & Lessons | $200 -> $949k Lookahead Analysis, Stale CSV Elimination, Almgren-Chriss Sizing Bounds, Vibe-Trading Swarm Assessment, Active Lesson #11. |
| **[8. Real Live Trading & Mutual Exclusion Guide](file:///F:/012D_TRADE/Kronos/docs/REAL_LIVE_TRADING_AND_MUTUAL_EXCLUSION_GUIDE.md)** | Production Live Execution | Binance USD(S)-M Live Workstation, Strict Mutual Exclusion Loop, Real Telemetry, Shared ONNX Brain, 2.5x Live Bayesian Weighting. |
| **[9. Quant-Grade Deployment Checklist & Operational Audit](file:///F:/012D_TRADE/Kronos/docs/QUANT_GRADE_DEPLOYMENT_CHECKLIST_AND_AUDIT.md)** | Institutional Deployment Standard | 6 Pillars, 18 Deployment Gates, Zero Ruin Risk, Automated CLI Verification Suite (`verify_deployment_readiness.py`). |
| **[10. Standalone 24/7 Deployment & Service Guide](file:///F:/012D_TRADE/Kronos/docs/STANDALONE_24_7_DEPLOYMENT_GUIDE.md)** | Production 24/7 Daemon & Service | Decoupled Background Supervisor, Auto-Restart Watchdog, Scheduled Task Auto-Start, One-Click Controls, Multi-IP Whitelisting. |
| **[11. Agentic Memory Architecture & Evaluation](file:///F:/012D_TRADE/Kronos/docs/AGENTIC_MEMORY_ARCHITECTURE.md)** | 7 Types of Agent Memory | Working, Semantic, Episodic, Procedural, Retrieval, Parametric, Prospective. Active Lean Production Memories vs. Deferred Bloat Analysis. |
| **[12. Unified Trade Forensics Framework](file:///F:/012D_TRADE/Kronos/docs/TRADE_FORENSICS.md)** | Trade Post-Mortems & Telemetry | 46-Item Assessment Framework, MAE/MFE Excursion Tracking, 6 Deterministic Failure Modes, Predictive Alpha vs. Execution Drag. |

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

### Running Empirical Verification & Quant Sanity Audits
```bash
# Fast Smoke Check (<4 seconds)
python -m pytest tests/test_smoke.py -q

# Run Quant Flaw & Sanity Auditor (Vibe-Trading Enhanced)
python scripts/audit_quant_flaws.py

# Full Regression Suite
python -m pytest tests/ -q
```
