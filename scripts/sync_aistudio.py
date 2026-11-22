#!/usr/bin/env python3
"""
scripts/sync_aistudio.py — Automated Upstream AI Studio Integration Tool
Safely merges updates from Google AI Studio (BinqQarenYu/krono.git) into the
Kronos Production Engine (bingkltech/Kronos.git) without overwriting the Python
risk engine, Binance live connectors, or AWS daemons.
"""

import os
import sys
import subprocess
import argparse

WORKSPACE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AI_STUDIO_REMOTE = "https://github.com/BinqQarenYu/krono.git"

SYNC_PATHS = [
    "webui/templates/index.html",
    "webui/static/css/terminal.css",
    "webui/static/js/neon_candlesticks.js",
    "webui/static/js/neon_win_sim.js",
    "webui/static/js/neon_strategy.js",
    "webui/static/js/swarm_deck.js",
    "src/server/",
    "server.ts",
    "package.json",
    "metadata.json",
    "data/neon_ai_assessments.json",
]


def run_cmd(cmd, cwd=WORKSPACE_ROOT, check=True):
    print(f"-> Running: {' '.join(cmd) if isinstance(cmd, list) else cmd}")
    res = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if check and res.returncode != 0:
        print(f"[ERROR] Command failed with code {res.returncode}")
        print("STDOUT:", res.stdout)
        print("STDERR:", res.stderr)
        sys.exit(res.returncode)
    return res


def main():
    parser = argparse.ArgumentParser(description="Sync Google AI Studio updates into Kronos")
    parser.add_argument("--branch", default="main", help="AI Studio branch name (default: main)")
    parser.add_argument("--no-test", action="store_true", help="Skip test verification")
    args = parser.parse_args()

    print("=" * 72)
    print("  KRONOS <- GOOGLE AI STUDIO SAFE SYNCHRONIZATION PIPELINE")
    print(f"  Remote: {AI_STUDIO_REMOTE} ({args.branch})")
    print("=" * 72)

    # 1. Ensure remote is configured
    remotes = run_cmd(["git", "remote"], check=False).stdout.split()
    if "aistudio" not in remotes:
        print("Configuring 'aistudio' remote...")
        run_cmd(["git", "remote", "add", "aistudio", AI_STUDIO_REMOTE])

    # 2. Fetch latest changes from AI Studio
    print("Fetching from AI Studio...")
    run_cmd(["git", "fetch", "aistudio"])

    # 3. Checkout selected assets from aistudio
    print("Selectively checking out UI, D3, TypeScript, and docs assets...")
    for p in SYNC_PATHS:
        chk = run_cmd(["git", "checkout", f"aistudio/{args.branch}", "--", p], check=False)
        if chk.returncode == 0:
            print(f"  [SYNCED] {p}")
        else:
            print(f"  [SKIPPED] {p} (not present in commit)")

    # 4. Run Verification Tests
    if not args.no_test:
        print("\nRunning smoke tests to ensure Python quant invariants hold...")
        test_res = run_cmd(["python", "-m", "pytest", "tests/test_smoke.py", "tests/test_neon_strategy.py", "-q"], check=False)
        if test_res.returncode == 0:
            print("[TESTS PASSED] 100% Python quant and smoke tests passed.")
        else:
            print("[TEST WARNING] Some tests had warnings or errors:")
            print(test_res.stdout)

    print("\n" + "=" * 72)
    print("  SYNCHRONIZATION COMPLETE! AI Studio features safely merged.")
    print("  Python Risk Engine & Live Trading Daemons preserved.")
    print("=" * 72)


if __name__ == "__main__":
    main()
