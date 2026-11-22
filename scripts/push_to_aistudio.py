#!/usr/bin/env python3
"""
scripts/push_to_aistudio.py — Safe Upstream Push to Google AI Studio
Exports updated frontend UI, D3 visualizers, TypeScript services, documentation,
and calibrated bot configs from Kronos (bingkltech/Kronos.git) back to the
Google AI Studio repository (BinqQarenYu/krono.git) without leaking private
API keys, AWS credentials, Python virtual environments, or multi-gigabyte models.
"""

import os
import sys
import shutil
import argparse
import subprocess

WORKSPACE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AI_STUDIO_REMOTE = "https://github.com/BinqQarenYu/krono.git"
WORKTREE_DIR = os.path.join(WORKSPACE_ROOT, "temp", "aistudio_worktree")

# Whitelist of directories and files to sync back to AI Studio
SYNC_ITEMS = [
    # Frontend WebUI
    ("webui/templates", "webui/templates"),
    ("webui/static/css", "webui/static/css"),
    ("webui/static/js", "webui/static/js"),
    ("webui/static/scalper.js", "webui/static/scalper.js"),
    ("webui/README.md", "webui/README.md"),
    # TypeScript Services & Configuration
    ("src", "src"),
    ("server.ts", "server.ts"),
    ("package.json", "package.json"),
    ("metadata.json", "metadata.json"),
    ("tsconfig.json", "tsconfig.json"),
    # Architecture Documentation & Agent Rules
    ("docs", "docs"),
    ("AGENTS.md", "AGENTS.md"),
    ("README.md", "README.md"),
    ("LICENSE", "LICENSE"),
    (".agents", ".agents"),
    # Calibrated Quant Configs (Safe JSON only)
    ("data/neon_config.json", "data/neon_config.json"),
    ("data/neon_ai_assessments.json", "data/neon_ai_assessments.json"),
    ("data/live_audit_summary.json", "data/live_audit_summary.json"),
    ("data/scalper_config.json", "data/scalper_config.json"),
    ("data/tiger_config.json", "data/tiger_config.json"),
    ("data/scalper_distilled_rules.json", "data/scalper_distilled_rules.json"),
    ("data/tiger_distilled_rules.json", "data/tiger_distilled_rules.json"),
    ("data/bot_settings.json", "data/bot_settings.json"),
]

# Strict blacklist of file patterns that MUST NEVER be copied to AI Studio
FORBIDDEN_EXTENSIONS = [
    ".pyc", ".pyd", ".pem", ".key", ".ppk", ".id_rsa", ".db",
    ".log", ".tmp", ".parquet", ".feather", ".h5", ".pth", ".pt", ".bin", ".ckpt"
]

FORBIDDEN_FILES = [
    ".env", ".env.local", ".env.production", "data/aws_trade_quota.json",
    "data/paper_trading_state.json", "data/tiger_radar.json", "data/tiger_state.json",
    "data/storm_state.json", "data/tiger_trades.db", "data/risk_ledger.db",
    "data/trade_autopsies.db"
]


def run_cmd(cmd, cwd=WORKSPACE_ROOT, check=True):
    res = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if check and res.returncode != 0:
        print(f"[ERROR] Command failed with code {res.returncode}")
        print("STDOUT:", res.stdout)
        print("STDERR:", res.stderr)
        sys.exit(res.returncode)
    return res


def is_safe_file(rel_path):
    rel_path_normalized = rel_path.replace("\\", "/")
    for fb in FORBIDDEN_FILES:
        if rel_path_normalized == fb or rel_path_normalized.endswith("/" + fb):
            return False
    for ext in FORBIDDEN_EXTENSIONS:
        if rel_path_normalized.endswith(ext):
            return False
    if "prediction_results" in rel_path_normalized:
        return False
    if "__pycache__" in rel_path_normalized:
        return False
    return True


def copy_asset(src_rel, dst_rel):
    src_full = os.path.join(WORKSPACE_ROOT, src_rel)
    dst_full = os.path.join(WORKTREE_DIR, dst_rel)

    if not os.path.exists(src_full):
        return 0

    if os.path.isfile(src_full):
        if not is_safe_file(src_rel):
            return 0
        os.makedirs(os.path.dirname(dst_full), exist_ok=True)
        shutil.copy2(src_full, dst_full)
        return 1

    copied = 0
    for root, dirs, files in os.walk(src_full):
        # Skip pycache and hidden git dirs
        dirs[:] = [d for d in dirs if d != "__pycache__" and not d.startswith(".git") and d != "prediction_results"]
        for f in files:
            file_src = os.path.join(root, f)
            rel_to_workspace = os.path.relpath(file_src, WORKSPACE_ROOT)
            if not is_safe_file(rel_to_workspace):
                continue
            rel_to_src = os.path.relpath(file_src, src_full)
            file_dst = os.path.join(dst_full, rel_to_src)
            os.makedirs(os.path.dirname(file_dst), exist_ok=True)
            shutil.copy2(file_src, file_dst)
            copied += 1
    return copied


def main():
    parser = argparse.ArgumentParser(description="Safely push Kronos updates back to Google AI Studio")
    parser.add_argument("--branch", default="main", help="AI Studio remote branch (default: main)")
    parser.add_argument("-m", "--message", default="feat(sync): push updates and calibrated configs from Kronos",
                        help="Commit message for AI Studio")
    parser.add_argument("--dry-run", action="store_true", help="Inspect staged changes without committing or pushing")
    parser.add_argument("--no-push", action="store_true", help="Commit to local worktree branch but do not push")
    parser.add_argument("--keep-worktree", action="store_true", help="Do not remove temp worktree after completion")
    args = parser.parse_args()

    print("=" * 72)
    print("  KRONOS -> GOOGLE AI STUDIO SAFE REVERSE-SYNC PIPELINE")
    print(f"  Target Remote: {AI_STUDIO_REMOTE} (branch: {args.branch})")
    print("=" * 72)

    # 1. Verify remote 'aistudio'
    remotes = run_cmd(["git", "remote"], check=False).stdout.split()
    if "aistudio" not in remotes:
        print("-> Configuring 'aistudio' remote...")
        run_cmd(["git", "remote", "add", "aistudio", AI_STUDIO_REMOTE])

    # 2. Fetch latest changes from AI Studio
    print("-> Fetching latest branch state from aistudio...")
    run_cmd(["git", "fetch", "aistudio", args.branch])

    # 3. Clean up any stale worktree
    if os.path.exists(WORKTREE_DIR):
        print("-> Removing existing worktree directory...")
        run_cmd(["git", "worktree", "remove", "--force", WORKTREE_DIR], check=False)
        if os.path.exists(WORKTREE_DIR):
            shutil.rmtree(WORKTREE_DIR, ignore_errors=True)

    # 4. Create fresh worktree tracking aistudio/branch
    print(f"-> Preparing isolated worktree at {WORKTREE_DIR}...")
    os.makedirs(os.path.dirname(WORKTREE_DIR), exist_ok=True)
    run_cmd(["git", "worktree", "add", WORKTREE_DIR, f"aistudio/{args.branch}"])

    try:
        # 5. Copy whitelisted assets from Kronos to worktree
        print("-> Selectively transferring whitelisted UI, docs, and quant configs...")
        total_copied = 0
        for src_rel, dst_rel in SYNC_ITEMS:
            count = copy_asset(src_rel, dst_rel)
            if count > 0:
                print(f"   [SYNCED] {src_rel} -> {dst_rel} ({count} file{'s' if count != 1 else ''})")
            total_copied += count

        # 6. Check Git status in the worktree
        status_res = run_cmd(["git", "status", "--porcelain"], cwd=WORKTREE_DIR)
        changes = [line.strip() for line in status_res.stdout.splitlines() if line.strip()]

        if not changes:
            print("\n" + "-" * 72)
            print("[UP TO DATE] Google AI Studio already matches Kronos! Nothing to commit.")
            print("-" * 72)
            return

        print(f"\n-> Found {len(changes)} pending modification(s)/addition(s) for AI Studio:")
        for ch in changes[:20]:
            print(f"   {ch}")
        if len(changes) > 20:
            print(f"   ... and {len(changes) - 20} more.")

        if args.dry_run:
            print("\n[DRY RUN] Dry run requested. Halting before commit and push.")
            return

        # 7. Stage and commit
        print(f"\n-> Staging and committing changes with message: \"{args.message}\"...")
        run_cmd(["git", "add", "."], cwd=WORKTREE_DIR)
        run_cmd(["git", "commit", "-m", args.message], cwd=WORKTREE_DIR)

        # 8. Push to AI Studio
        if args.no_push:
            print("[NO PUSH] Commit created locally in worktree. Skipping remote push.")
        else:
            print(f"-> Pushing to AI Studio ({AI_STUDIO_REMOTE} -> {args.branch})...")
            push_res = run_cmd(["git", "push", "aistudio", f"HEAD:{args.branch}"], cwd=WORKTREE_DIR)
            print(push_res.stdout)
            print("\n" + "=" * 72)
            print(f"  SUCCESS! Kronos updates successfully pushed to Google AI Studio!")
            print(f"  Remote: {AI_STUDIO_REMOTE}")
            print(f"  Branch: {args.branch}")
            print("=" * 72)

    finally:
        # 9. Clean up worktree unless user asked to keep it
        if not args.keep_worktree and os.path.exists(WORKTREE_DIR):
            print("-> Cleaning up isolated worktree...")
            run_cmd(["git", "worktree", "remove", "--force", WORKTREE_DIR], check=False)


if __name__ == "__main__":
    main()
