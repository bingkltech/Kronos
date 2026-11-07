#!/usr/bin/env bash
# ==============================================================================
# deploy/aws_setup.sh — Automated Headless Setup for AWS EC2 Free Tier (t2.micro / t3.micro)
# ==============================================================================

set -e

echo "=============================================================================="
echo ">> [Kronos AWS Setup] Initializing Headless Production Environment..."
echo "=============================================================================="

# 1. Configure 2 GB Swap File (Prevents OOM during pip installations and transient bursts)
if [ ! -f /swapfile ]; then
    echo ">> [1/6] Allocating 2 GB swapfile for memory protection..."
    sudo fallocate -l 2G /swapfile
    sudo chmod 600 /swapfile
    sudo mkswap /swapfile
    sudo swapon /swapfile
    echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
    echo ">> [1/6] Swapfile configured successfully."
else
    echo ">> [1/6] Swapfile already present. Skipping."
fi

# 2. Update System Packages
echo ">> [2/6] Installing Linux core dependencies (Python 3, Git, venv)..."
sudo apt-get update -y
sudo apt-get install -y python3 python3-pip python3-venv git curl

# 3. Create Dedicated Python Virtual Environment
VENV_PATH="$HOME/kronos-env"
if [ ! -d "$VENV_PATH" ]; then
    echo ">> [3/6] Creating isolated Python virtual environment at $VENV_PATH..."
    python3 -m venv "$VENV_PATH"
else
    echo ">> [3/6] Virtual environment already exists at $VENV_PATH."
fi

source "$VENV_PATH/bin/activate"
pip install --upgrade pip setuptools wheel --no-cache-dir

# 4. Install CPU-Only PyTorch & Lean Dependencies (Zero CUDA bloat)
echo ">> [4/6] Installing CPU-optimized PyTorch (< 150 MB disk, 0 GPU overhead)..."
pip install torch --index-url https://download.pytorch.org/whl/cpu --no-cache-dir

echo ">> [4/6] Installing lean quantitative dependencies..."
pip install -r deploy/requirements_lean.txt --no-cache-dir

# 5. Preheat Foundation Model Cache (NeoQuasar/Kronos-small & Tokenizer)
echo ">> [5/6] Pre-downloading Kronos-small foundation checkpoints from Hugging Face..."
python -c "
from huggingface_hub import snapshot_download
print('Downloading Tokenizer...')
snapshot_download(repo_id='NeoQuasar/Kronos-Tokenizer-base', allow_patterns=['*.json', '*.txt', '*.bin', '*.safetensors'])
print('Downloading Kronos-small weights...')
snapshot_download(repo_id='NeoQuasar/Kronos-small', allow_patterns=['*.json', '*.txt', '*.bin', '*.safetensors'])
print('Model cache successfully preheated.')
"

# 6. Ensure log directory and install Systemd Service
echo ">> [6/6] Installing systemd daemon (kronos.service)..."
mkdir -p "$HOME/Kronos/logs"
mkdir -p "$HOME/Kronos/data"

sudo cp deploy/kronos.service /etc/systemd/system/kronos.service
sudo systemctl daemon-reload
sudo systemctl enable kronos

echo "=============================================================================="
echo ">> [Kronos AWS Setup] SUCCESS! Headless Worker is Ready."
echo "=============================================================================="
echo ""
echo "Next steps:"
echo "1. Verify or create your .env in ~/Kronos/.env with your API keys:"
echo "   BINANCE_FUTURES_API_KEY=your_key"
echo "   BINANCE_FUTURES_SECRET_KEY=your_secret"
echo "   GEMINI_API_KEY=your_gemini_key"
echo "   KRONOS_INSTANCE_TAG=AWS"
echo ""
echo "2. Start the 24/7 background service:"
echo "   sudo systemctl start kronos"
echo ""
echo "3. Check live service status:"
echo "   sudo systemctl status kronos"
echo "   python scripts/status.py"
echo ""
echo "4. On your Local PC (.env), set the coordinator link so PC becomes passive observer:"
echo "   AWS_COORDINATOR_URL=http://<YOUR_AWS_PUBLIC_IP>:7070"
echo "=============================================================================="
