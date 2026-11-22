# Kronos Two-Repository Architecture & AI Studio Synchronization Guide

**Author**: Antigravity Quant & Systems Architecture  
**Subject**: Harmonizing Google AI Studio (`BinqQarenYu/krono.git`) with Kronos Production (`bingkltech/Kronos.git`)  
**Status**: Fully Implemented & Automated  

---

## 1. The Core Dilemma: Why Two Repositories Exist

You have two separate Git repositories serving two completely different, complementary purposes:

```mermaid
flowchart LR
    A["Google AI Studio Repo\n(BinqQarenYu/krono.git)\n\n• Rapid UI Prototyping\n• D3 Candlestick Visualizers\n• Monte Carlo Win Simulators\n• Strategy Conception"] -->|Selective Auto-Sync\n(scripts/sync_aistudio.py)| B["Kronos Production Engine\n(bingkltech/Kronos.git)\n\n• 214,000+ Lines of Python Quant Core\n• Decimal Zero-Float Math\n• Live Binance Futures API Execution\n• AWS EC2 24/7 Systemd Daemons\n• Strict Risk Engines & Trade Quotas"]
    B -->|Deploys Live To| C["AWS EC2 Cloud Instance\n(13.63.158.94)\n• Real-Capital Overnight Execution\n• 8-Trade Live Safety Cap"]
```

### Repository Roles & Capabilities

| Attribute | Google AI Studio Repo (`BinqQarenYu/krono`) | Kronos Production Repo (`bingkltech/Kronos`) |
| :--- | :--- | :--- |
| **Primary Role** | **Innovation & Visual Prototyping Lab** | **Execution Core & Risk Vault** |
| **Environment** | Web Browser TypeScript/Node Sandbox | 24/7 AWS EC2 Cloud Linux Instance |
| **Tech Stack** | TypeScript, Vite/Bun, Express, D3.js | Python 3.11, `Decimal` Math, PyTorch, Flask, Binance SDK |
| **Strengths** | Fast iteration on UI widgets, visual charts, win simulations, prompt tuning | Real capital order dispatch, hard stop-losses, live websockets, bank-grade safety invariants |
| **Limitations** | Sandboxed; cannot hold live Binance API keys or run AWS systemd daemons | Modifying complex frontend UI inside Python files is slower |

---

## 2. The Danger of a Blind Merge (Why We Must Separate Them)

> [!CAUTION]
> **CRITICAL RULE**: Never perform a raw `git pull` or blunt file overwrite from AI Studio directly into your master branch.
> 
> *Google AI Studio creates a standalone web project.* If you do a blunt git merge, Git will see that AI Studio does not have the 214,000+ lines of Python (`src/quant/`, `risk_engine/`, `tests/`, `scripts/`) and will attempt to **delete your entire Python execution engine**, crashing your AWS live trading daemon.

---

## 3. The Solution: The "Upstream Lab -> Downstream Engine" Architecture

To keep both repos permanently organized and in sync:
1. **Develop freely in Google AI Studio**:
   - Build new UI buttons, adjust D3 equity curves, design candlestick scanners, or test win simulation scenarios.
   - Commit and push from AI Studio to `https://github.com/BinqQarenYu/krono.git`.
2. **Pull selectively into Kronos Production**:
   - Kronos treats AI Studio as an upstream feature branch (`aistudio/main`).
   - Only the frontend assets, D3 visualizers, CSS, and TypeScript simulation engines are merged.
   - The Python live risk engine, Binance order router, and AWS headless daemons remain **100% untouched and protected**.

---

## 4. The 1-Command Automated Sync Tool (`scripts/sync_aistudio.py`)

We have created an automated synchronization pipeline in your repository:  
📄 **[scripts/sync_aistudio.py](file:///f:/012D_TRADE/Kronos/scripts/sync_aistudio.py)**

Whenever you make updates in Google AI Studio, simply run this one command in terminal (or ask me to run it):

```bash
python scripts/sync_aistudio.py
```

### What This Command Does Automatically:
1. **Fetches Upstream**: Pulls the latest commits from `https://github.com/BinqQarenYu/krono.git`.
2. **Selectively Syncs Assets**:
   - `webui/templates/index.html` (Latest terminal layout & tabs)
   - `webui/static/css/terminal.css` (Updated styling)
   - `webui/static/js/neon_candlesticks.js` (Candlestick radar)
   - `webui/static/js/neon_win_sim.js` (Win simulator D3 visualizer)
   - `webui/static/js/neon_strategy.js` (Dynamic controls & event handlers)
   - `src/server/` (TypeScript simulation & candlestick engines)
3. **Protects the Python Core**: Guarantees zero deletions to `src/quant/`, `risk_engine/`, or tests.
4. **Runs Verification**: Automatically runs `pytest tests/test_smoke.py tests/test_neon_strategy.py -q` to guarantee zero regressions.

---

## 6. The Reverse Sync: Pushing Kronos Updates Back to Google AI Studio

When you or Antigravity enhance the trading bots, optimize strategy configurations, write architectural documentation, or tune UI layouts inside Kronos, you can push those improvements back to Google AI Studio (`BinqQarenYu/krono.git`) with a single command.

### The 1-Command Reverse Sync:
```bash
python scripts/push_to_aistudio.py
```
*(Or double-click `push_to_aistudio.bat`, or run `npm run push:aistudio`)*

### How Reverse Sync Operates Safely:
1. **Isolated Git Worktree**: Creates an isolated worktree tracking `aistudio/main` in a temporary folder. The live Kronos Python environment, running Flask WebUI, and AWS connection are **never touched or interrupted**.
2. **Strict Whitelist Export**: Copies only approved assets:
   - Frontend UI (`webui/templates/index.html`, `webui/static/css/*`, `webui/static/js/*`)
   - TypeScript engines & server (`src/`, `server.ts`, `package.json`, `metadata.json`)
   - Quant Strategy Configurations (`data/neon_config.json`, `data/bot_settings.json`, `data/scalper_config.json`, `data/tiger_config.json`)
   - Full Architectural & Forensic Documentation (`docs/*.md`, `AGENTS.md`)
3. **Ironclad Credential & Bloat Shield**:
   - **NEVER** touches `.env` or any file containing private API keys or SSH credentials.
   - **NEVER** uploads heavy Python model checkpoints (`*.pth`, `*.pt`, `*.bin`), live databases (`*.db`), virtual environments (`.venv`), or multi-megabyte prediction results.
4. **Direct Push to AI Studio**:
   - Commits cleanly on `aistudio/main` and pushes directly to `https://github.com/BinqQarenYu/krono.git`.
   - Google AI Studio automatically pulls this commit, giving you all the latest documents, calibrated configs, and UI tools inside your AI Studio browser environment!

---

## 7. Quick Reference: Two-Way Sync Cheat Sheet

| Direction | Purpose | Command | Shortcut |
| :--- | :--- | :--- | :--- |
| **Downstream**<br>(AI Studio ➔ Kronos) | Pull new visual prototypes, charts, & TypeScript code from AI Studio into Kronos | `python scripts/sync_aistudio.py` | `sync_aistudio.bat`<br>`npm run sync:aistudio` |
| **Upstream**<br>(Kronos ➔ AI Studio) | Push updated bot configs, docs, and UI refinements back to AI Studio | `python scripts/push_to_aistudio.py` | `push_to_aistudio.bat`<br>`npm run push:aistudio` |

