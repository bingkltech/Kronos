# Standalone 24/7 Deployment & Service Architecture

This guide details how to run the **Kronos Autonomous Quantitative Trading Engine** as an independent, resilient 24/7 background service on Windows, completely decoupled from Antigravity, IDE sessions, or open terminal windows.

---

## 1. Architectural Overview

```
+------------------------------------------------------------------------+
| Windows Operating System (Boot / Logon)                                |
|                                                                        |
|  [Windows Task Scheduler / start_standalone.bat]                      |
|                         |                                              |
|                         v                                              |
|  [scripts/standalone_daemon.py] <----- Supervisor Watchdog             |
|       |                     |                                          |
|       |-- PID Tracking      |-- Log Rotation (logs/kronos_standalone.log)
|       |-- Port Pre-Flight   |-- Auto-Restart on Crash (Backoff Guard)  |
|       |                                                                |
|       v                                                                |
|  [webui/app.py] (Port 7070) <--------- Flask Web UI & REST Gateway     |
|       |                                                                |
|       +--> [_autopilot_daemon_loop] <- 24/7 Autonomous Trader Thread   |
|                 |                                                      |
|                 v                                                      |
|         [Binance Futures REST API / Algo Order Service]                |
+------------------------------------------------------------------------+
```

### Core Invariants & Fail-Safes
1. **Independent Process Tree:** The supervisor and trading engine run as detached Windows processes. Closing Antigravity, VS Code, or your browser will **not** terminate the trading bot.
2. **Auto-Restart Watchdog:** If `webui/app.py` encounters an unhandled OS exception or network crash, the supervisor automatically catches it and re-spawns the process in 3 seconds.
3. **Log Rotation (Cap 10 MB):** Console outputs and trading cycles are redirected to `logs/kronos_standalone.log` with automatic rotation to prevent unbounded disk growth.
4. **Exchange-Level Bracket Safety:** Stop-Loss and Take-Profit orders are lodged directly on Binance's matching engine via `/fapi/v1/algoOrder`. Even if the local PC loses power or internet, the exchange protects your positions.

---

## 2. One-Click Control Scripts

In the project root directory (`F:\012D_TRADE\Kronos`), the following batch scripts provide instant control:

| Script | Purpose | Action Performed |
| :--- | :--- | :--- |
| **`start_standalone.bat`** | **Start Service** | Launches supervisor in the background, waits for port 7070, opens browser dashboard. |
| **`stop_standalone.bat`** | **Stop Service** | Gracefully terminates supervisor and child process via PID and releases port 7070. |
| **`status.bat`** | **Check Health** | Prints instant console telemetry: wallet balance, active positions, PnL, and IP status. |
| **`install_autostart_task.bat`** | **Enable Boot Autostart** | Registers `Kronos247TradingBot` in Windows Task Scheduler to start on every PC reboot. |
| **`uninstall_autostart_task.bat`**| **Disable Autostart** | Unregisters the task from Windows Task Scheduler. |

---

## 3. Step-by-Step Standalone Deployment

### Step A: Verify Windows Power Settings (Crucial for 24/7)
If Windows goes into **Sleep** or **Hibernate**, the CPU suspends and network sockets close.
1. Open **Windows Settings $\to$ System $\to$ Power & Battery**.
2. Under **Screen and sleep**:
   * Set *"When plugged in, put my device to sleep after"* to **"Never"**.
   * *(You can set "Turn off my screen after" to 5–10 minutes to save power/monitor life without affecting background trading).*

### Step B: Multi-IP Whitelisting on Binance
If your internet provider uses Carrier-Grade NAT (CGNAT) or dynamic IP rotation, your outbound IP might alternate between multiple IPs (e.g., `37.186.52.17` and `37.186.53.65`).
1. Go to **Binance $\to$ API Management $\to$ Edit API Key**.
2. In the **IP Access Restriction** box:
   * Enter both IPs separated by a space:
     ```text
     37.186.52.17 37.186.53.65
     ```
   * Click **Save** and verify with 2FA.

### Step C: Launch Standalone Mode
Double-click **`start_standalone.bat`** or run in PowerShell:
```powershell
.\start_standalone.bat
```
The browser will automatically open to `http://localhost:7070`.

### Step D: Check Status Anytime
Double-click **`status.bat`** to get an instant console printout of your balances, margin ratio, and open trades without opening a browser.

---

## 4. Boot Persistence (Survive PC Reboots)

To ensure Kronos starts automatically whenever your computer boots up:
1. Right-click **`install_autostart_task.bat`** $\to$ **Run as Administrator**.
2. Windows Task Scheduler will register `Kronos247TradingBot`.
3. Whenever you reboot or log into Windows, Kronos will start in the background on `http://localhost:7070`.
