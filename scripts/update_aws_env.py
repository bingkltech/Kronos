#!/usr/bin/env python3
"""Update .env and quota on AWS."""
import json
import os

env_path = "/home/ec2-user/kronos-bot/.env"
quota_path = "/home/ec2-user/kronos-bot/data/aws_trade_quota.json"

updates = {
    "KRONOS_INSTANCE_TAG": "AWS",
    "KRONOS_LIVE_TRADE_CAP": "50",
    "KRONOS_MAX_CONCURRENT_POSITIONS": "3",
    "KRONOS_MAX_MACRO_POSITIONS": "2",
    "ALERT_EMAIL_TO": "",
    "SMTP_HOST": "smtp.gmail.com",
    "SMTP_PORT": "587",
    "SMTP_USER": "",
    "SMTP_PASS": "",
    "SMTP_USE_TLS": "true"
}

if os.path.exists(env_path):
    with open(env_path, "r", encoding="utf-8") as f:
        lines = f.read().splitlines()

    existing_keys = set()
    new_lines = []
    for line in lines:
        stripped = line.strip()
        if "=" in stripped and not stripped.startswith("#"):
            k = stripped.split("=", 1)[0].strip()
            if k in updates:
                new_lines.append(f'{k}="{updates[k]}"')
                existing_keys.add(k)
                continue
        new_lines.append(line)

    new_lines.append("")
    new_lines.append("# AWS 3-Position Concurrency (2 Macro + 1 Scalp) & 50-Trade Quota Rules")
    for k, v in updates.items():
        if k not in existing_keys:
            new_lines.append(f'{k}="{v}"')

    with open(env_path, "w", encoding="utf-8") as f:
        f.write("\n".join(new_lines) + "\n")
    print(">> AWS .env updated.")

# Reset quota state for the new session
quota_payload = {
    "live_trading_enabled": True,
    "live_trade_cap": 50,
    "live_session_trades": 0,
    "macro_trades": 0,
    "scalp_trades": 0,
    "live_cap_reached_utc": None,
    "updated_at_utc": "2026-11-19T07:13:00+00:00"
}
os.makedirs(os.path.dirname(quota_path), exist_ok=True)
with open(quota_path, "w", encoding="utf-8") as f:
    json.dump(quota_payload, f, indent=2)
print(">> AWS aws_trade_quota.json reset to 0/50 trades (LIVE_ENABLED).")
