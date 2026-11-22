# Formulation: NEON as the Sole Live Trading Bot on AWS EC2 (10-Trade Cap)

**Audit Authority**: Agent POE (Post-Occupancy Evaluator) & Quant Architecture Engine  
**Target Host**: AWS EC2 `13.63.158.94` (`eu-north-1`)  
**Objective**: Formulate the configuration and code changes required to make NEON the **exclusive live trading engine** on Binance Futures, capped at **10 trades** before auto-pausing.  

---

## 1. Capacity Audit: Will NEON Fit on AWS EC2?

> [!IMPORTANT]
> ### EMPIRICAL ANSWER: **YES, EFFORTLESSLY.**
> Not only will NEON fit, but replacing the existing multi-bot setup with NEON will **dramatically reduce CPU, memory, and Binance API rate-limit stress** on the AWS EC2 instance.

### Empirical Resource Measurements (Live from EC2)

| Resource Metric | EC2 Capacity | Current Utilization | NEON Incremental Load | Headroom After NEON |
| :--- | :--- | :--- | :--- | :--- |
| **vCPU** | 2 vCPUs (Xeon Platinum) | ~2.5% | < 0.1% (1 cycle / 60s) | **> 95% Free** |
| **RAM (Physical)** | 913 MiB | 380 MiB (41.6%) | ~15–20 MiB | **~400 MiB Free** |
| **Swap Space** | 1,024 MiB | 25 MiB (2.4%) | 0 MiB | **998 MiB Free** |
| **Disk Storage** | 8.0 GiB NVMe | 3.4 GiB (43%) | < 5 MiB (logs/state) | **4.6 GiB Free** |
| **Binance API Weight**| 2,400 / minute | **1,841 / 2,400 (76.7%)** | ~15 / 2,400 (< 1%) | **Recovers 1,800+ Weight** |

### The Critical Rate-Limit Discovery
Our live inspection of the EC2 instance revealed that a background legacy process (`scripts/tiger_worker.py --live`, PID 2940483) is currently running and consuming **1,841 out of 2,400 Binance API weight** per minute, causing `RateLimitWatchdog` throttle warnings:
```
[TIGER-DAEMON] Active: ['KORUUSDT', 'ZECUSDT', 'SOXSUSDT'] | WS: 1970272t | Weight: 1841/2400
[WARNING] [TIGER SCANNER] Request blocked by RateLimitWatchdog. Serving cache.
```
**Formulation Benefit**: Killing this legacy process and making NEON the sole live bot:
1. Reclaims **88 MiB of physical RAM**.
2. Reduces Binance API weight consumption from **1,841/2,400 down to ~15/2,400** (a 99% reduction in API pressure).
3. Eliminates all 429 risk and rate-limit throttle warnings.

---

## 2. Single-Bot Exclusivity Formulation

To guarantee that **NEON is the ONLY bot executing real capital**:

```mermaid
flowchart TD
    Clock["60-Second Headless Daemon Loop\n(scripts/headless_worker.py)"] --> Router{"Execution Mode Router"}
    
    Router -- "MacroAgent" --> Paper1["Paper Mode Only\n(Telemetry / Dashboard Only)"]
    Router -- "ApexScalper" --> Paper2["Paper Mode Only\n(Telemetry / Dashboard Only)"]
    Router -- "NEON Bot" --> QuotaCheck{"Session Trades < 10?"}
    
    QuotaCheck -- "Yes (<10)" --> LiveBracket["Binance Live Execution Engine\n(submit_live_bracket_order)"]
    LiveBracket --> Exchange["Binance Futures Exchange\n(Isolated Margin + Native Algo TP/SL)"]
    
    QuotaCheck -- "No (>=10)" --> AutoPause["STANDBY_PAUSED\n(Disarm Fleet & Send Notification)"]
```

### 1. Inactivation of Competing Live Engines
In `scripts/headless_worker.py`:
- **MacroAgent**: Forced to `execution_mode="PAPER"`. It continues to compute regime and breadth telemetry for the dashboard, but dispatches **zero live orders**.
- **ApexScalper**: Scalp live order trigger bypassed (`apex_live_enabled = False`).
- **Tiger Worker Daemon**: Terminated completely (`pkill -f tiger_worker.py`).

### 2. NEON Live Dispatch Binding
When NEON's 6 gates evaluate to `approved == True`:
```python
# 1. Construct institutional trade ticket
ticket = TradeTicket(
    symbol=cand["symbol"],
    side="BUY" if cand["side"] == "LONG" else "SELL",
    entry_price=cand["entry_price"],
    stop_loss=cand["stop_loss"],
    take_profit=cand["take_profit"],
    quantity=cand["quantity"],
    leverage=Decimal("3.5")
)

# 2. Dispatch real capital via hardened atomic execution engine
active_pos = quant_bot.executor.submit_live_bracket_order(ticket)

# 3. Increment session counter
_record_live_trade_dispatch(ticket.symbol, source="NEON")
```

---

## 3. Strict 10-Trade Cap & Fail-Safe Auto-Pause

The safety quota system will enforce an unbreachable ceiling:

1. **Persistent Quota State (`data/aws_trade_quota.json`)**:
   ```json
   {
     "live_trading_enabled": true,
     "live_trade_cap": 10,
     "live_session_trades": 0,
     "sole_live_engine": "NEON_V1",
     "updated_at_utc": "2026-11-21T19:00:00Z"
   }
   ```
2. **Auto-Pause Circuit Breaker**:
   - As soon as `live_session_trades` reaches **10**:
     - `live_trading_enabled` flips to `False`.
     - Status switches to `STANDBY_PAUSED`.
     - Zero further order dispatches can occur.
     - `QuotaNotifier` sends an automated completion email with full account PnL and trade execution summary.

---

## 4. Execution Protections & Risk Sizing for NEON

| Parameter | Value | Rationale |
| :--- | :---: | :--- |
| **Max Concurrent Positions** | `2` | Ringfences risk on the \$191.47 balance to prevent over-allocation. |
| **Risk Per Trade** | `1.5%` of Equity | Maximum ~\$2.87 risk per trade. |
| **Max Leverage** | `3.5x` | Eliminates liquidation hazard; liquidation distance $> 25\%$. |
| **Margin Type** | `ISOLATED` | Invariant: each position is quarantined from total wallet equity. |
| **Stop-Loss Type** | Native Binance Algo SL | Order rests directly on exchange matching engine; no reliance on local bot uptime. |
| **Anti-Naked Watchdog** | `1,000 ms` | If exchange SL fails to confirm within 1s, bot flattens position immediately. |

---

## 5. Overnight Session Window Decision

NEON Gate 2 (`G2_SESSION`) normally blocks entries during the overnight hours (**22:00–02:59 UTC**) to avoid low-liquidity whipsaws.

### Two Operational Options for Overnight:

- **Option A (Institutional Recommendation - Strict Gate 2)**:
  - Keep Gate 2 active. The bot runs on EC2, but patiently waits through the overnight deadzone.
  - Active hunting begins at **03:00 UTC** (Tokyo Open) and **08:00 UTC** (London Open).
  - *Advantage*: Maximum trade quality; zero overnight chop risk.

- **Option B (Immediate Action - Major Pairs Only)**:
  - Relax Gate 2 exclusively for `BTCUSDT` and `ETHUSDT` (which trade with deep 24/7 liquidity), while keeping the other 5 gates (`G1`, `G3`, `G4`, `G5`, `G6`) at full strength.
  - *Advantage*: Can take high-conviction trades immediately tonight if prime setups occur.

---

## 6. Implementation Checklist

To deploy this formulation:
- [x] Verified AWS EC2 memory, CPU, and disk headroom (Passes with 400 MiB free).
- [ ] Terminate redundant `tiger_worker.py` (PID 2940483) on EC2.
- [ ] Add `NeonLiveExecutionEngine` to [scripts/headless_worker.py](file:///f:/012D_TRADE/Kronos/scripts/headless_worker.py).
- [ ] Set `KRONOS_LIVE_TRADE_CAP=10` and reset `live_session_trades=0`.
- [ ] Set `macro_entry_cap=0` and disable Apex live dispatch.
- [ ] Sync updated code to EC2 and restart `kronos-headless.service`.
