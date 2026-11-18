#!/usr/bin/env bash
# ==============================================================================
# Kronos Headless Anti-Bloat Autonomous Maintenance Routine (AWS 24/7)
# Location: scripts/auto_antibloat.sh
# Purpose: Maintain ultra-lean disk & RAM footprints on cloud instances.
#          Safely reclaims dead space without deleting any API keys, configs,
#          active virtualenvs, trade history, or learning governor records.
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

if [ -f "$BOT_DIR/kronos-env/bin/python" ]; then
    PYTHON_BIN="$BOT_DIR/kronos-env/bin/python"
elif [ -f "$BOT_DIR/venv/bin/python" ]; then
    PYTHON_BIN="$BOT_DIR/venv/bin/python"
elif [ -f "$HOME/kronos-env/bin/python" ]; then
    PYTHON_BIN="$HOME/kronos-env/bin/python"
else
    PYTHON_BIN="$(which python3 || echo 'python3')"
fi

LOG_TAG="[KRONOS-ANTIBLOAT]"
echo "$(date -u +'%Y-%m-%dT%H:%M:%SZ') $LOG_TAG Starting autonomous anti-bloat pass on $BOT_DIR..."

# 1. Vacuum Systemd Journal Logs (Enforce hard 50M max cap, 3-day retention)
echo "$LOG_TAG 1/6: Vacuuming systemd journals to <= 50MB..."
sudo journalctl --vacuum-size=50M --vacuum-time=3d > /dev/null 2>&1 || true

# 2. Flush OS package and installer caches
echo "$LOG_TAG 2/6: Cleaning package manager (apt/dnf) & pip caches..."
sudo apt-get clean -q > /dev/null 2>&1 || true
sudo dnf clean all -q > /dev/null 2>&1 || true
rm -rf "$HOME/.cache/pip" /root/.cache/pip > /dev/null 2>&1 || true

# 3. Clean stale /tmp buffers older than 24 hours
echo "$LOG_TAG 3/6: Pruning stale /tmp files older than 24h..."
find /tmp -maxdepth 1 -type f -atime +1 -delete > /dev/null 2>&1 || true

# 4. Execute Core Cross-Platform Python Hygiene Pass (Buffers, K-lines, Logs, SQLite, JSON)
echo "$LOG_TAG 4/6: Executing Kronos System Hygiene Engine..."
if [ -x "$PYTHON_BIN" ] && [ -f "$BOT_DIR/scripts/system_hygiene.py" ]; then
    "$PYTHON_BIN" "$BOT_DIR/scripts/system_hygiene.py" --quiet || true
else
    echo "$LOG_TAG Python binary or system_hygiene.py not found. Running fallback purge..."
    find "$BOT_DIR" -name "*.pyc" -delete > /dev/null 2>&1 || true
    find "$BOT_DIR" -name "__pycache__" -type d -exec rm -rf {} + > /dev/null 2>&1 || true
fi

# 5. Flush Linux Inode & Page Caches (Drop inactive cached RAM back to Free RAM)
echo "$LOG_TAG 5/6: Dropping inactive page/inode memory caches..."
sync
echo 3 | sudo tee /proc/sys/vm/drop_caches > /dev/null 2>&1 || true

# 6. Display Current Storage & Memory Footprint
echo "$LOG_TAG 6/6: Anti-bloat pass complete."
echo "$LOG_TAG Current Storage & Memory Footprint:"
df -h / | tail -n 1
free -m | grep -E "Mem:|Swap:"
