# Kronos Tsunami Storm Adaptive Protocol — High-Wave Crisis Governance

> **Institutional Quantitative Risk Specification**  
> **Status:** Production Deployed (Local PC & AWS EC2 Stockholm `13.63.158.94`)  
> **Associated Lesson:** [Lesson #24: tsunami_storm_adaptive_protocol](file:///f:/012D_TRADE/Kronos/data/lessons.db)  
> **Simulation Suite:** [scripts/simulate_tsunami_shock.py](file:///f:/012D_TRADE/Kronos/scripts/simulate_tsunami_shock.py)  
> **Test Suite:** [tests/test_storm_protocol.py](file:///f:/012D_TRADE/Kronos/tests/test_storm_protocol.py)

---

## 1. Executive Summary & The "Batten Down the Hatches" Philosophy

In high-frequency crypto derivative markets, the primary cause of portfolio drawdowns is not flawed baseline directional models; it is **correlated multi-asset liquidation during extreme market dislocations** ("tsunami waves").

When an unforeseen high-impact catalyst hits (such as an emergency rate shock, sudden regulatory enforcement, or a cascading multi-thousand-dollar BTC liquidation wick), market makers withdraw liquidity, correlations across all altcoins spike toward $1.0$, and bid-ask spreads blow out.

Naive trading systems attempt to continue normal multi-position operations or "catch falling knives," resulting in simultaneous stop-outs across multiple positions.

The **Tsunami Storm Adaptive Protocol** solves this by implementing an autonomous dynamic shock-absorber:
1. **Normal Waters:** Expanded fleet capacity (**6 Macro Positions, 3 Scalp Positions**, Total = 9).
2. **When Tsunami Hits:** Batten down the hatches:
   - **Phase 1 (First 15 Minutes):** Mandatory **Shock Pause** (freeze all new entries; let falling knives and liquidation wicks exhaust).
   - **Phase 2 (Minutes 15 to 60):** Clamps maximum portfolio exposure to strictly **1 Macro Position and 1 Scalp Position**, enforces an elevated conviction gate ($\ge 75.0\%$), and activates exchange Mark-Price anti-wick stops.
   - **Phase 3 (After 60 Minutes):** **Calm Water Auto-Recovery** automatically restores normal capacity (6 Macro / 3 Scalp) once the storm elapses and volatility cools down.

---

## 2. The 3-Phase Adaptive State Machine

```
                      [ NORMAL WATERS ]
              • Macro Book: Up to 6 positions (Was 2-3)
              • Scalper: Up to 3 positions (Tiger + Apex)
              • Stop Orders: Binance Mark-Price Protected
                             │
     TSUNAMI DETECTED! ──────┼────── (Violent BTC dump >2% in 5m, 
                             │        FOMC/CPI News Shock, or Manual UI Toggle)
                             ▼
              [ 🌊 TSUNAMI STORM PROTOCOL ]
                  (Default: 60-Minute Horizon)
                             │
       ┌─────────────────────┴─────────────────────┐
       ▼                                           ▼
 [ PHASE 1: SHOCK PAUSE ]               [ PHASE 2: FOCUSED CAUTION ]
 (First 15 Minutes)                     (Minutes 15 to 60)
 • Strict VETO on all new entries.      • CAPACITY STRICTLY CLAMPED:
 • Do not catch falling knives.           - Max 1 Macro Position
 • Let initial liquidation wave clear.    - Max 1 Scalp Position
 • Existing positions protected by      • ELEVATED CONVICTION GATE:
   Mark-Price brackets.                   - Requires ≥75.0% Win Probability
                                          - Mark-Price Anti-Wick Stops
                                                   │
                             ┌─────────────────────┘
                             │  After 60 minutes AND 
                             │  volatility normalizes...
                             ▼
              [ 🔄 CALM WATER AUTO-RECOVERY ]
              • Macro capacity restored to 6 positions
              • Scalp capacity restored to 3 positions
              • Standard thresholds restored
              • Fully automatic recovery (Zero restarts)
```

---

## 3. High-Wave & News Shock Detection Triggers

The system transitions from `NORMAL_WATERS` to `TSUNAMI_STORM_MODE` autonomously via four quantitative sensors:

| Trigger Mechanism | Quantitative Condition | Real-World Event Simulated |
| :--- | :--- | :--- |
| **1. Macro News Blackout** | High-impact economic event within window ($\pm 30\text{m}$) | FOMC Rate Decision, CPI, Non-Farm Payrolls, SEC rulings |
| **2. BTC Violent Velocity Shock** | BTC 5m velocity $\ge 2.0\%$ OR 5m candle range $\ge 3.0\%$ | Unscheduled flash dump, cascading exchange liquidation cascade |
| **3. Market Breadth Collapse** | Composite Advance/Decline breadth $< 15\%$ or $> 85\%$ | Systemic market dislocation where all pairs move in lockstep |
| **4. Cluster Stop-Outs** | $\ge 5$ consecutive stop-outs within $30\text{ minutes}$ | Severe chop, whipsaw sea, or regime breakdown |
| **5. Captain's UI Override** | Manual toggle via Cockpit topbar (`#topbar-storm-pill`) | Breaking headline news on social feeds before exchange prints |

---

## 4. In-Storm Trading Rules & The 1M / 1S Clamp

During active storms, the engine enforces strict defense:

### A. The Capacity Clamp (Strictly 1 Macro, 1 Scalp)
- **Macro Book:** Clamped from standard 3 positions down to **1 position**. If 1 macro position is currently held, all further macro candidates are strictly vetoed.
- **Scalper Lane:** Clamped to **1 position**. If 1 scalp is currently open, further scalp triggers are vetoed.
- **Result:** Total account exposure during a high wave is restricted to a maximum of 2 positions, preventing correlated multi-coin bleed.

### B. Elevated Conviction Gate ($\ge 75.0\%$)
- In normal markets, trades pass at $\ge 65.0\%$ confidence.
- In storm mode, candidates below $75.0\%$ are instantly rejected. The engine only trades high-conviction, flight-to-safety setups.

### C. Exchange-Native Mark-Price Anti-Wick Protection
- In `src/quant/binance_execution.py`, Stop-Loss conditional brackets dispatch with:
  ```python
  "workingType": "MARK_PRICE"
  ```
- **Quantitative Defense:** Mark Price is the volume-weighted median of 8 major global spot exchanges. Transient 200–500ms needle wicks on the Binance perpetual contract cannot trigger the stop-loss unless the global spot market actually breaches the level.

---

## 5. Empirical Stress Test Verification

The complete lifecycle was tested via `scripts/simulate_tsunami_shock.py` and `tests/test_storm_protocol.py`:

```text
==============================================================================
🌊 KRONOS TSUNAMI STORM PROTOCOL — EMPIRICAL ADAPTIVE TEST
   Testing High Waves, Flash Dumps & Unforeseen News Shockwaves
==============================================================================

[STAGE 1: Calm Waters / Standard Regime]
  • Ocean State:               NORMAL_WATERS
  • Macro Capacity Limit:      3 positions
  • Scalper Capacity Limit:    1 position (N=1)
  • Min Confidence Hurdle:     65.0%
  • Macro Trade #2 (65% prob): ACCEPTED -> Permitted (Normal Waters)

[STAGE 2: Unforeseen Tsunami Hits! BTC Dumps -3.2% in 5m]
  🚨 High-Wave Wave Detector:  TRIGGERED!
  • Reason:                    Violent BTC Volatility Spike (Ocean Wave Out of Control)
  • Metric:                    BTC 5m Velocity: 3.19% | 5m Range: 3.33%
  • Active Phase:              PHASE_1_SHOCK_PAUSE
  • Duration:                  60 minutes
  • Shock Pause Window:        15 minutes

[STAGE 3: Phase 1 Shock Pause (T+5m) — Falling Knives & Liquidation Churn]
  • Current Phase:             PHASE_1_SHOCK_PAUSE (10m remaining)
  • Macro Entry Attempt:       VETOED -> VETO: Storm Protocol Phase 1 (Shock Pause active)
  • Scalper Entry Attempt:     VETOED -> VETO: Storm Protocol Phase 1 (Shock Pause active)

[STAGE 4: Phase 2 Focused Caution (T+25m) — Waves High, Trading with Extreme Caution]
  • Current Phase:             PHASE_2_FOCUSED_CAUTION (35m remaining)
  • Macro Capacity Clamp:      Strictly 1 Position
  • Scalp Capacity Clamp:      Strictly 1 Position
  • Required Conviction Gate:  ≥75.0%
  • Candidate A (68% prob):    VETOED -> VETO: Storm Mode requires ≥75.0% confidence
  • Macro Position #1 (78%):   ACCEPTED -> Permitted (Storm Mode Focused Caution: 1 Macro)
  • Macro Position #2 (85%):   VETOED -> VETO: Storm Mode clamps Macro to strictly 1 position (1/1 occupied)
  • Scalp Position #1 (80%):   ACCEPTED -> Permitted (Storm Mode Focused Caution: 1 Scalp)
  • Scalp Position #2 (92%):   VETOED -> VETO: Storm Mode clamps Scalp to strictly 1 position (1/1 occupied)

[STAGE 5: Phase 3 Calm Water Auto-Recovery (T+61m) — 1hr Storm Ended]
  • Ocean State:               NORMAL_WATERS
  • Is Storm Active?           False
  • Macro Capacity Restored:   3 positions
  • Scalp Capacity Restored:   1 position
  • Standard Confidence Gate:  65.0%
  • Normal Macro Entry (65%):  ACCEPTED -> Permitted (Normal Waters)

==============================================================================
✅ TSUNAMI PROTOCOL ADAPTIVE TEST: 100% SUCCESS
```

---

## 6. Web Cockpit & User Interface Operations

In the Kronos Web Cockpit ([http://localhost:7070](http://localhost:7070)):
- **Status Indicator (Top Navigation Bar):**
  - Normal Waters: `🌊 CALM WATERS (3M / 1S)` (Cyan pill).
  - Shock Pause: `🌊 STORM: PAUSE (14m) · 1M/1S` (Pulsing Red pill).
  - Focused Caution: `🌊 STORM: ACTIVE (38m) · 1M/1S` (Pulsing Gold pill).
- **Interactive Captain's Control:**
  - Clicking the `#topbar-storm-pill` displays an instant confirmation modal allowing the operator to manually arm or disarm the 60-minute storm protocol at any millisecond.
- **REST Endpoints:**
  - `GET /api/storm/status`: Returns active phase, time remaining, and capacity clamps.
  - `POST /api/storm/toggle`: Triggers or cancels storm protocol with instant cross-process sync.
