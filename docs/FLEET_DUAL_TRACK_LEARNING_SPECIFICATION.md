# Fleet Dual-Track Learning & Forensic Autopsy Specification

**Document Version:** 1.0.0  
**Effective Date:** 2026-11-15  
**Target Fleet:** Strategy #1 (Headless Kronos / Storm), Strategy #2 (Lightning Scalper), Strategy #3 (Stalking Tiger)  
**Governance:** AGENTS.md Quant Architecture Invariants (Zero Float Math, Base Checkpoint Immutability, ASVL)  

---

## 1. Executive Summary & Epistemological Foundation

In quantitative algorithmic trading, **losses, regime shifts, and execution frictions are not failures to be swept aside; they are the true alpha goldmines.** Static models fit on historical stationary data inevitably decay when deployed into real crypto-asset market microstructure.

However, an unprincipled approach to "learning" introduces two catastrophic failure modes:
1. **The Overfitting Trap:** Tweaking parameters after every paper loss creates a chaotic feedback loop that curve-fits to microscopic noise and spreads paranoia across the fleet.
2. **The Horizon Contamination Flaw:** Universally blacklisting an asset because a 3-minute mean-reversion scalper (Tiger) stopped out during an explosive breakout starves a 4-hour macro trend-following model (Storm) of its highest-yielding momentum runner.

The **Kronos Fleet Dual-Track Learning Engine** resolves this paradox by bifurcating the feedback loop into two structurally decoupled tracks:
- **Track 1: Paper Exploration (The High-Velocity Sandbox)** — Gathers statistical distributions, tests edge parameters, maps microstructure terrain, and identifies hazardous toxic flow with zero risk to capital.
- **Track 2: Live Authority (The P&L Anchor)** — Executes with locked institutional capital, strict risk envelopes, exchange-side bracket orders, and carries **3.0x Bayesian authority weight** in model parameter calibration.

```mermaid
flowchart TD
    subgraph Market [Live Binance Futures Market Flow]
        Ticks[AggTrade & Level-2 Depth]
        OI[Real-Time Open Interest]
    end

    subgraph DualTrack [Dual-Track Execution Engine]
        Paper[Track 1: Paper Exploration Sandbox\nWeight = 1.0x | 90s TTL | Rapid Search]
        Live[Track 2: Live Authority Execution\nWeight = 3.0x | Hard Stops | Capital Risk]
    end

    subgraph ForensicEngine [Forensic Autopsy Engine]
        Taxonomy{Autopsy Classification}
        WIN[WIN_SQUEEZE]
        STALL[STALL_SCRATCH]
        FLUSH[ZERO_MFE_LIQ_FLUSH]
        REV[MFE_REVERSAL]
        OUTLIER[STEAMROLLER_OUTLIER]
        STOP[STOP_OUT]
    end

    subgraph Retention [Institutional Lessons Goldmine]
        DB[(data/tiger_trades.db\nFull Sub-second Telemetry)]
        Quarantine[Temporal Quarantine Registry\n12h Paper / 24h Live Decay]
        Lessons[(data/lessons.db\nCross-Fleet Behavioral Rules)]
        Distilled[(data/tiger_distilled_rules.json\nHot-Reloaded Operational Brackets)]
    end

    Market --> Paper
    Market --> Live
    Paper --> Taxonomy
    Live --> Taxonomy
    Taxonomy --> WIN & STALL & FLUSH & REV & OUTLIER & STOP
    WIN & STALL & FLUSH & REV & OUTLIER & STOP --> DB
    DB --> Quarantine
    DB --> Distilled
    DB --> Lessons
    Quarantine -.->|Shadow Re-qualification >= 66% WR| DualTrack
```

---

## 2. The Forensic Autopsy Taxonomy: 6 Empirical Modes

Every completed trade across the fleet—whether paper or live—is subjected to an automated deterministic autopsy before ledger commitment. Trades are never grouped as simple binary "win" or "loss"; they are diagnosed by their physical market microstructure mechanism:

| Autopsy Code | Structural Mechanism | Mathematical Trigger Condition | Strategic Lesson / Prescription |
| :--- | :--- | :--- | :--- |
| **`WIN_SQUEEZE`** | Orderflow trapped opposing traders; rapid price expansion into liquidity target. | `is_win == True` | Reinforces wick ratio and CVD delta thresholds for current regime. |
| **`STALL_SCRATCH`** | Momentum failed to expand within 12 minutes. Position scratched near breakeven. | `exit_reason in ("STALL_SCRATCH", "RATCHET_BE")` and $\text{Net PnL} \ge -\$0.20$ | **Capital preserver.** Confirms 12m temporal decay ladder prevented adverse reversal. |
| **`ZERO_MFE_LIQ_FLUSH`** | Instant stop-out with zero favorable movement ($0.00\%$ MFE). Classic stop run. | `is_win == False` and $\text{MFE} == 0.00\%$ | Identifies liquidation sweep with negative $\Delta\text{OI}$. Activates $\Delta\text{OI} \ge +0.01\%$ filter. |
| **`MFE_REVERSAL`** | Position surged significantly into profit ($\text{MFE} \ge +0.50\%$) but reversed to stop. | `is_win == False` and $\text{MFE} \ge +0.50\%$ | Indicates greedy target distance or tardy velocity ratcheting. Lowers TP distance. |
| **`STEAMROLLER_OUTLIER`** | Loss exceeded $1.5\times$ base risk ($\le -\$2.25$) due to extreme gap or cascade. | $\lvert\text{Net PnL}\rvert > 1.5 \times \text{Initial Risk}$ | Indicates freight-train momentum. Enforces immediate 24h quarantine and tightening sieve. |
| **`STOP_OUT`** | Normal statistical variance stop within expected risk envelope ($\le \$1.50$). | Default unclassified loss | Absorbed within standard portfolio expectancy. |

---

## 3. Dual-Track Bayesian Authority Weighting

Model parameter distillation does not treat simulated clicks and real money equally. Real-money executions experience live exchange matching engine priority, queue position, slippage, and real liquidity consumption.

### Mathematical Formulation
Let:
- $N_{\text{paper}}$ be the count of closed paper trades, with $W_{\text{paper}}$ wins.
- $N_{\text{live}}$ be the count of closed live trades, with $W_{\text{live}}$ wins.
- $\omega_{\text{paper}} = 1.0$ (Exploratory baseline weight).
- $\omega_{\text{live}} = 3.0$ (Empirical authority weight).

The **Effective Bayesian Fleet Win Rate** is computed as:
$$\text{WR}_{\text{effective}} = \frac{\omega_{\text{paper}} W_{\text{paper}} + \omega_{\text{live}} W_{\text{live}}}{\omega_{\text{paper}} N_{\text{paper}} + \omega_{\text{live}} N_{\text{live}}} \times 100\%$$

### Adaptive Dynamic Threshold Calibration:
1. **Wick Ratio Adaptation:**
   - If $\text{WR}_{\text{effective}} < 50.0\% \implies \text{Absorption Wick Threshold} = 0.48$ (demands higher-conviction wicks).
   - If $\text{WR}_{\text{effective}} \ge 70.0\% \implies \text{Absorption Wick Threshold} = 0.42$ (allows fluid signal flow).
2. **CVD Z-Score Adaptation:**
   - If $\text{WR}_{\text{effective}} < 50.0\% \implies \text{CVD Divergence Threshold} = 2.4\sigma$ (suppresses marginal signals).
   - Otherwise $\implies \text{CVD Divergence Threshold} = 2.0\sigma$.
3. **Bracket Distance Adaptation:**
   - If Average MFE $< 0.80\% \implies \text{Slow TP} = 0.80\%, \text{Slow SL} = 0.55\%$ (compresses bracket to capture smaller mean-reverting excursions).

---

## 4. Temporal Quarantine Decay & Shadow Re-qualification

Permanent blacklisting creates dead capital and permanent blind spots. If a cryptocurrency stops out during an aggressive liquidation wave, it may settle into high-conviction mean-reverting orderflow hours later.

### Quarantine Lifecycle Rules:
1. **Quarantine Triggers:**
   - **Live Loss:** 1 live trade loss triggers an immediate **24-hour quarantine**.
   - **Paper Loss:** $\ge 2$ paper losses or cumulative loss $\le -\$1.00$ within a rolling 24-hour window triggers a **12-hour quarantine**.
2. **Temporal Decay (Automatic Expiration):**
   - Every distillation cycle audits active quarantines against current wall-clock time:
     $$\text{If } t_{\text{now}} \ge t_{\text{expiry}} \implies \text{Status} \leftarrow \text{"GRADUATED"}$$
   - The symbol is automatically returned to the candidate pool without human intervention.
3. **Shadow Paper Re-qualification (Early Graduation):**
   - Quarantined symbols continue to generate **Shadow Signals** in the background without allocating active risk slots or capital.
   - If a quarantined symbol records $\ge 3$ consecutive shadow evaluations with a win rate $\ge 66.7\%$ ($2/3$ or $3/3$ wins), it qualifies for **Early Graduation**:
     $$\text{Early Graduation Trigger} \iff N_{\text{shadow}} \ge 3 \land \frac{W_{\text{shadow}}}{N_{\text{shadow}}} \ge 0.667$$
   - The symbol status updates to `"GRADUATED"` with reason `"SHADOW_REQUALIFIED"`.

---

## 5. Strategy-Regime Segregation (Preventing Horizon Contamination)

A fundamental law of multi-strategy quant architecture is:
$$\text{Asset Quarantine}(\text{Strategy}_i) \neq \text{Asset Quarantine}(\text{Strategy}_j) \quad \forall i \neq j$$

### Horizon Separation Table:
| Strategy Name | Regime Horizon | Order Type | Optimal Condition | Hazard Condition |
| :--- | :--- | :--- | :--- | :--- |
| **Strategy #1: Storm (Kronos Headless)** | 4-Hour / Macro | Market / Post-Only | Runaway momentum, sustained breakout trends. | Choppy, low-volume mean-reverting ranges. |
| **Strategy #2: Lightning Scalper** | 15-Minute / Swing | Aggressive Limit | Clean volatility bands, predictable liquidity cycles. | Illiquid gap openings, erratic orderbooks. |
| **Strategy #3: Stalking Tiger** | 1-Minute / Micro | Passive Limit Sniper | Exhaustion wicks, trapped liquidations, mean reversion. | Runaway unexhausted freight trains. |

**The Architectural Rule:**
- Quarantines logged in `data/tiger_trades.db` apply **exclusively to Strategy #3**.
- Strategy #1 (Storm) and Strategy #2 (Lightning) maintain their own independent asset sieves based on their respective mathematical objective functions.
- Only systemic structural lessons (e.g. rate limit budgets, Decimal precision, anti-burst cooldowns, exchange API quirks) are elevated to `data/lessons.db` for universal fleet adoption.

---

## 6. Implementation Ledger & Schema

### Table: `tiger_trades`
```sql
CREATE TABLE IF NOT EXISTS tiger_trades (
    trade_id TEXT PRIMARY KEY,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    entry_price TEXT NOT NULL,
    exit_price TEXT NOT NULL,
    notional_usd TEXT NOT NULL,
    net_pnl_usd TEXT NOT NULL,
    net_pnl_pct TEXT NOT NULL,
    duration_seconds INTEGER NOT NULL,
    exit_reason TEXT NOT NULL,
    is_win INTEGER NOT NULL,
    mfe_pct TEXT NOT NULL,
    mae_pct TEXT NOT NULL,
    wick_ratio TEXT NOT NULL,
    cvd_zscore TEXT NOT NULL,
    is_slow_regime INTEGER NOT NULL,
    created_at_utc TEXT NOT NULL,
    closed_at_utc TEXT NOT NULL,
    execution_mode TEXT NOT NULL DEFAULT 'PAPER',
    autopsy_code TEXT NOT NULL DEFAULT 'NORMAL'
);
```

### Table: `tiger_quarantines`
```sql
CREATE TABLE IF NOT EXISTS tiger_quarantines (
    symbol TEXT PRIMARY KEY,
    quarantined_at_utc TEXT NOT NULL,
    expiry_utc TEXT NOT NULL,
    reason TEXT NOT NULL,
    strike_count INTEGER NOT NULL,
    execution_mode TEXT NOT NULL,
    status TEXT NOT NULL
);
```

### Table: `tiger_shadow_evals`
```sql
CREATE TABLE IF NOT EXISTS tiger_shadow_evals (
    eval_id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    timestamp_utc TEXT NOT NULL,
    is_win INTEGER NOT NULL,
    mfe_pct TEXT NOT NULL
);
```

---

## 7. Verification & Operational Directives
- **Verification Suite:** `tests/test_tiger_scalper.py` (`test_tiger_forensics_autopsy_taxonomy_and_migration`, `test_tiger_quarantine_temporal_decay_and_shadow_graduation`, `test_tiger_dual_track_bayesian_weighting`).
- **Telemetry Visualizer:** Real-time forensics, active quarantines, and autopsy distributions are broadcast via `data/tiger_radar.json` to the unified WebUI (`http://localhost:7070/scalper`).
- **Active Lesson:** Preserved in `data/lessons.db` under **Active Lesson #34** (`fleet_dual_track_bayesian_learning_and_autopsy`).
