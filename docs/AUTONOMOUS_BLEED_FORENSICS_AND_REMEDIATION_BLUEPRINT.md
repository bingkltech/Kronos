# Autonomous Bleed Forensics, Truth Verification & Remediation Blueprint (ABFP)

Whenever real-money capital experiences a drawdown, unexpected losses, or win rate deterioration, the orchestrator and all autonomous agents must strictly execute this **6-Phase Blueprint**. No speculative edits or unverified opinions are permitted.

```
 ┌─────────────────────────────────────────────────────────────────────────────┐
 │               AUTONOMOUS BLEED FORENSICS & REMEDIATION PIPELINE            │
 ├─────────────────┬─────────────────┬─────────────────┬───────────────────────┤
 │    PHASE 1      │    PHASE 2      │    PHASE 3      │       PHASE 4-6       │
 │  LEDGER AUDIT   │   TRUTH PROBE   │ COUNTERFACTUAL  │ GATING, ASVL & LESSON │
 ├─────────────────┼─────────────────┼─────────────────┼───────────────────────┤
 │ • Decimal Math  │ • Model Probe   │ • Test on real  │ • Δ PnL > 0 Gate      │
 │ • Payoff Ratio  │ • Code Trace    │   trade ledger  │ • 130 Pytest Suite    │
 │ • Loss Clusters │ • Session Match │ • Isolate delta │ • Stage Lesson in DB  │
 └─────────────────┴─────────────────┴─────────────────┴───────────────────────┘
```

---

## Phase 1: Ledger Forensic Assessment (Zero Float Decimal Precision)
* **Command:** `python scripts/autonomous_bleed_blueprint.py <window_hours>`
* **Mandatory Metrics to Extract:**
  1. **Win Rate ($WR$)** and **Trade Sample Size ($N$)**.
  2. **Gross PnL** vs **Net PnL** and **Fee Drag Ratio** ($\frac{\text{Fees}}{\text{Gross Losses}}$).
  3. **Payoff Ratio ($R:R$)**: $\frac{\text{Average Win}}{\text{Average Loss}}$. If $R:R < 1.0x$ and $WR < 50\%$, system expectancy is mathematically negative.
  4. **Loss Clusters**: Identify rapid consecutive stop-outs within $< 30$ minutes (signals whipsaw or macro regime shock).

---

## Phase 2: Empirical Ground Truth Probing
Never assume why the engine traded; prove it through live system telemetry:
1. **Model Health Probe:** Check `GET http://localhost:7070/api/model-status`. If `loaded == false`, verify if engine fell back to linear extrapolation.
2. **Session Gate Alignment:** Check trade entry timestamps against market sessions (European Morning 08:00–13:30 UTC, US Cash Open 14:00–15:30 UTC, Late-Night Asia 22:00–03:00 UTC).
3. **Execution Mode Check:** Verify whether trades originated from `Macro Swing` or `Lightning Scalper` using `data/scalp_orders.json`.

---

## Phase 3: Re-Assessment & Counterfactual Backtesting
Before writing code or changing configuration, simulate the proposed fix against actual historical fills in `data/live_audit_summary.json`:
* **Script:** `python scripts/test_patch_viability.py`
* **Test Windows:**
  - Active Bleed Window (Last 12 Hours)
  - Preceding 24 Hours
  - Full Lifetime Ledger (All closed real-money trades)

---

## Phase 4: Profitability Gating Rule
A recommendation is **STRICTLY REJECTED** unless it satisfies both:
1. **$\Delta \text{Net PnL} > 0$** across both the bleed window AND full lifetime ledger.
2. **Exchange Fees Saved $\ge 0$** (must reduce or hold friction neutral).

---

## Phase 5: Safeguard Deployment & ASVL Verification
1. Apply targeted atomic code diff.
2. Enforce **Rule-of-2 Circuit Breaker**: Fast smoke check (`python -m pytest tests/test_smoke.py -q`), then targeted test suite, then full suite (`python -m pytest tests/ -q`).
3. If any test fails twice consecutively, **HALT** and escalate.

---

## Phase 6: Institutional Lessons Database Archival
* Record the symptom, root cause, verified fix, and mathematical proof into the institutional guidance engine:
  ```bash
  python scripts/lessons.py stage --category trading --keyword "<keyword>" --symptom "..." --cause "..." --fix "..." --proof "..."
  python scripts/lessons.py promote --id <id>
  ```
