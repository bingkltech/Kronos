# Kronos Headless Cloud Deployment Guide (AWS Free Tier)

This guide walks you through deploying **Kronos Headless** on an **AWS EC2 Free Tier (`t2.micro` or `t3.micro`)** instance with **100% code and mathematical parity** with your local PC installation.

---

## Architecture & Distributed Multi-Instance Guard

```
                      +-----------------------------+
                      |   Binance USD(S)-M Futures   |
                      +--------------+--------------+
                                     ^
                                     |
               +---------------------+---------------------+
               |                                           |
    [LIVE Orders: LIVE_AWS_...]                 [PASSIVE Observer: No Orders]
               |                                           |
+--------------+--------------+             +--------------+--------------+
|     AWS EC2 (Free Tier)     |             |      Local PC Workstation   |
|   Headless 24/7 Worker      |<--Heartbeat-|    webui/app.py Dashboard   |
|     (Port 7070 API)         |  (Port 7070)|  AWS_COORDINATOR_URL active |
|   RAM: ~280 MB / 1 GB       |             |   Trades suppressed if AWS  |
|  KRONOS_INSTANCE_TAG=AWS    |             |   is ONLINE and trading     |
+-----------------------------+             +-----------------------------+
```

### The Fail-Safe Rule
- When **AWS is ONLINE and ACTIVE**: Local PC automatically detects AWS via `AWS_COORDINATOR_URL`, switches to **PASSIVE OBSERVER** mode, displays all live positions and telemetry on your local screen, but **never places conflicting orders**.
- When **AWS is OFFLINE or STOPPED**: Local PC automatically resumes active primary authority.
- All Binance orders are forensically tagged: `LIVE_AWS_<symbol>_<timestamp>` vs `LIVE_PC_<symbol>_<timestamp>`.

---

## Step 1: Launch an AWS EC2 Free Tier Instance

1. Log into your **AWS Management Console** and navigate to **EC2**.
2. Click **Launch Instance**:
   - **Name:** `kronos-quant-worker`
   - **OS Image (AMI):** `Ubuntu Server 24.04 LTS` (or `22.04 LTS`) - 64-bit (x86_64).
   - **Instance Type:** `t2.micro` (or `t3.micro` in eligible regions) - Free tier eligible (1 vCPU, 1 GB RAM).
   - **Key Pair:** Create or select your existing `.pem` key pair for SSH access.
   - **Storage:** Configure `30 GB` gp3 (Free tier allows up to 30 GB EBS).
3. **Network Settings (Security Group):**
   - Allow **SSH (Port 22)** from `My IP`.
   - Allow **Custom TCP (Port 7070)** from `My IP` (for your local PC to connect and check health).
4. Click **Launch Instance**.

---

## Step 2: Connect to Your AWS Instance

From your local PC (PowerShell or Terminal):
```bash
ssh -i "path/to/your-key.pem" ubuntu@<YOUR_AWS_PUBLIC_IP>
```

---

## Step 3: Clone Repository & Configure Environment

On the AWS terminal:
```bash
# Clone the repository
git clone https://github.com/bingkltech/Kronos.git
cd Kronos

# Create your .env file
cat << 'EOF' > .env
BINANCE_FUTURES_API_KEY=your_binance_api_key_here
BINANCE_FUTURES_SECRET_KEY=your_binance_secret_key_here
GEMINI_API_KEY=your_gemini_api_key_here
KRONOS_INSTANCE_TAG=AWS
PORT=7070
EOF
```

---

## Step 4: Run the One-Click Setup Script

```bash
chmod +x deploy/aws_setup.sh
bash deploy/aws_setup.sh
```

This automated script performs:
1. Allocates a **2 GB swapfile** so the 1 GB instance never exhausts memory.
2. Installs Python 3 venv and dependencies.
3. Installs CPU-optimized PyTorch (< 150 MB disk, 0 GPU overhead).
4. Preheats the Hugging Face model cache with `NeoQuasar/Kronos-small` and tokenizer.
5. Installs the `kronos.service` systemd daemon with automatic restart on reboot.

---

## Step 5: Start & Monitor the 24/7 Cloud Worker

```bash
# Start the service
sudo systemctl start kronos

# Check service status
sudo systemctl status kronos

# View live streaming logs
tail -f logs/kronos_headless.log
```

You can also run the console status tool on AWS at any time:
```bash
~/kronos-env/bin/python scripts/status.py
```

---

## Step 6: Link Your Local PC (Passive Observer Mode)

On your **Local PC**, open `F:\012D_TRADE\Kronos\.env` and add:
```ini
AWS_COORDINATOR_URL=http://<YOUR_AWS_PUBLIC_IP>:7070
```

1. Run `python scripts/status.py` on your PC:
   ```text
   Engine State    : ACTIVE
   Instance Role   : PC [PASSIVE_OBSERVER]
   Cloud Guard     : [!] Remote AWS Cloud instance at http://<AWS_IP>:7070 is ONLINE & ACTIVE.
   Execution Mode  : REAL LIVE TRADING (BINANCE FUTURES)
   ```
2. Open your local Web UI at `http://localhost:7070`. You can monitor all live positions, balances, and PnL in real time, while the AWS cloud instance safely executes trades 24/7.
