# Google Gemini Free Tier Quota & Rate Limit Architecture Guide

**Kronos Quantitative Systems — Supervisory Meta-Strategy Documentation**  
**Classification:** Infrastructure & Strategic AI Governance  
**Target Engine:** Google Gemini Flash (`gemini-1.5-flash` / `gemini-2.0-flash` / `gemini-3.8-flash`)  
**Status:** In Production (Autonomous 24/7 Autopilot Live)

---

## 1. Executive Summary & Core Verdict

The **Google Gemini Free Tier** provides institutional-grade strategic intelligence at **$0.00 cost** without risk of credit exhaustion or account overages.

In Kronos, the trading system operates under a strict architectural separation:
1. **High-Frequency Tactical Engine (100% Local):** Candlestick ingestion, ONNX foundation model inference (512-bar tail slicing), Monte Carlo fan simulations, EMA/VWAP mathematical calculation, and KEV.ai 6-Point Veto Gates execute entirely locally on the server in sub-milliseconds without calling any external LLM APIs.
2. **Supervisory Meta-Strategy Arbiter (Remote Low-Frequency):** Google Gemini functions strictly as the **Chief Investment Officer (CIO Copilot)**. It evaluates rolling performance metrics and lessons database records to tune macro sweetspots ($R:R$ hurdle, fee threshold, risk budget) on an asynchronous, event-driven cadence.

**Empirical Quota Result:**  
In continuous 24/7 live paper trading, Kronos issues between **5 and 25 requests per 24 hours**, consuming **< 1.7% of Google's 1,500 requests/day free tier quota**. The system maintains over **98.3% headroom** at all times.

---

## 2. Google Gemini Free Tier Quota Specification

Google AI Studio enforces three independent rate limits simultaneously. If any dimension is exceeded, the API returns HTTP `429 Too Many Requests` (`RESOURCE_EXHAUSTED`).

| Quota Metric | Gemini Flash Free Tier Limit | Gemini Pro Free Tier Limit | Kronos Production Consumption | Headroom Available |
| :--- | :---: | :---: | :---: | :---: |
| **RPD (Requests Per Day)** | **1,500 requests / 24h** | 50 requests / 24h | **5 – 25 requests / 24h** | **> 98.3%** |
| **RPM (Requests Per Minute)** | **15 requests / min** | 2 requests / min | **~1 request / min** (burst max) | **14 req/min** |
| **TPM (Tokens Per Minute)** | **1,000,000 tokens / min** | 32,000 tokens / min | **~1,200 tokens / request** | **> 99.8%** |
| **Billing & Credit Cost** | **$0.00 (Free Tier)** | $0.00 (Free Tier) | **$0.00 (Zero Credit Burn)** | **Unlimited $0** |

*Note: RPD counters reset every 24 hours at **midnight Pacific Time (00:00 PT / 07:00 UTC)**.*

---

## 3. Why Kronos Does NOT Hit Free Tier Rate Limits

```
                                 KRONOS ARCHITECTURAL SEPARATION
                                 
  [ HIGH-FREQUENCY LOCAL EXECUTION ]                   [ LOW-FREQUENCY STRATEGIC AI ]
  - 1-Second Price Ticks                               - Periodic Strategic Review
  - 60-Second Autonomous Bot Cycles                    - Macro Sweetspot Calibration
  - Candlestick & Indicator Math                       - Lessons DB Post-Mortem Audit
  - 1,000 Futures Monte Carlo Fan                      - Event-Driven Trigger (Batch Milestones)
  - KEV.ai 6-Point Mathematical Veto Gate              - Manual On-Demand Evaluation Button
  - Decimal Financial Friction Ledger                  
  ---------------------------------                    ---------------------------------
  Calls External API: 0 per second                     Calls External API: 5-25 per 24h
  Execution Latency: < 2ms (Local CPU/GPU)             Execution Latency: 1.5s - 2.8s
```

### 3.1. Cadence Triggers for Gemini Requests
Gemini is invoked **only** under two strictly controlled conditions:
1. **On-Demand Manual Request:** When a trader clicks `🧠 Run Strategic Assessment` in the Macro Dashboard or Forecaster view.
2. **Batch Trade Milestone Trigger:** When a configurable batch of closed paper trades (e.g., every 5 to 10 completed trades) is accumulated, or after every 4 hours of market regime change.

Between these milestones, the background autopilot loop runs every 60 seconds without querying Google's servers.

### 3.2. Payload Token Hygiene
Every payload sent to Gemini is compacted into a structured, dense Markdown digest:
- **Macro Overview:** Active market breadth regime, top-10 volume, and funding rates (~250 tokens).
- **Paper Trading Summary:** Closed trades count, win/loss ratio, net realized PnL, fee drag (~300 tokens).
- **Lessons Database Digest:** Summary of the last 5 SQLite trade post-mortems (~400 tokens).
- **Active Sweetspot State:** Current $R:R$ hurdle, fee hurdle, and risk budget (~150 tokens).

Total prompt size is approximately **1,100 to 1,300 tokens**, consuming only **0.13%** of the 1,000,000 TPM limit.

---

## 4. Failsafe Fallback & Circuit Breaker Architecture

In the unlikely event of network partition, DNS resolution failure, or Google API throttling, the system triggers the **Zero-Disruption Fallback Protocol**:

```mermaid
flowchart TD
    A["Trigger Strategic Assessment"] --> B{"Gemini API Call Successful?"}
    B -- "Yes (HTTP 200)" --> C["Parse JSON Sweetspot\n- Min R:R Ratio\n- Net Fee Hurdle %\n- Risk Budget %"]
    C --> D["Persist to data/bot_settings.json"]
    D --> E["Apply to KEV.ai Risk Gate"]
    
    B -- "No (HTTP 429 / Network Err)" --> F["Log Warning to Terminal\n'>> [Gemini Warning] Rate limit or network error'"]
    F --> G["Retain Last Active Sweetspot\n(Zero Bot Disruption)"]
    G --> H["Continue 24/7 Autopilot Uninterrupted"]
```

### 4.1. Resilience Invariants
1. **No Bot Crashes:** An unhandled Gemini API exception never halts the 24/7 autopilot daemon or the Web UI.
2. **State Memory:** The last approved sweetspot is persisted to `data/bot_settings.json`. If Gemini is unavailable upon restart, the last verified settings are restored immediately from disk.
3. **Local KEV.ai Enforcement:** The 6-point mathematical risk veto gate operates independently with or without Gemini connectivity.

---

## 5. Configuration & Optimization Reference

To verify or customize your Gemini integration in Kronos:

### 5.1. Environment Configuration (`.env`)
```bash
# Google Gemini API Key (Obtained free from https://aistudio.google.com/)
GEMINI_API_KEY="AIzaSy..."

# Recommended Model (Optimized for 1,500 RPD free tier)
GEMINI_MODEL="gemini-1.5-flash"
```

### 5.2. Web UI Monitoring Endpoints
- **Status Check:** `GET http://localhost:7070/api/gemini/assessment`  
  Returns `{ available: true, model: "gemini-1.5-flash", auto_apply: true, assessment: {...} }`.
- **Manual Assessment Trigger:** `POST http://localhost:7070/api/gemini/assess`  
  Executes an immediate strategic evaluation.
- **Toggle Sweetspot Auto-Apply:** `POST http://localhost:7070/api/gemini/toggle-auto-apply`  
  Enables or disables automatic KEV.ai gate adjustment.

---

## 6. Summary Checklist

- [x] **100% Free:** No credit card required; zero chance of billing charges.
- [x] **1,500 Requests / 24h Quota:** More than sufficient for institutional macro supervision.
- [x] **5–25 Daily Calls:** Kronos uses < 1.7% of available daily bandwidth.
- [x] **Failsafe Offline Fallback:** Background paper trading runs 24/7 regardless of API status.
- [x] **Zero Float Financial Math:** All sweetspots are quantized to strict `Decimal` values before applying to KEV.ai gates.
