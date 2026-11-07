"""
scripts/status.py — Real-Time Console Status for Kronos 24/7 Trading Engine.
"""

import sys
import requests
from decimal import Decimal

def main():
    target_url = sys.argv[1].rstrip("/") if len(sys.argv) > 1 and sys.argv[1].startswith("http") else "http://localhost:7070"
    print("=" * 76)
    print(f" [Kronos] 24/7 Standalone Trading Engine - Operational Status ({target_url})")
    print("=" * 76)

    try:
        r = requests.get(f"{target_url}/api/live/status", timeout=5)
        if r.status_code != 200:
            print(f"Server returned HTTP {r.status_code}")
            return
        data = r.json()
    except Exception as e:
        print(f"OFFLINE: Cannot connect to {target_url} ({e})")
        print("Run 'start_standalone.bat' to launch the engine.")
        print("=" * 76)
        return

    bot_state = data.get("bot_state", "UNKNOWN")
    connected = data.get("connected", False)
    acct = data.get("live_account", {})
    error_msg = data.get("error") or acct.get("error")
    exec_mode = data.get("execution_mode", "UNKNOWN")
    dist_guard = data.get("distributed_guard", {})
    inst_tag = dist_guard.get("instance_tag", "PC")
    role = dist_guard.get("role", "ACTIVE_PRIMARY")
    guard_msg = dist_guard.get("message", "")

    wallet = acct.get("total_wallet_balance_usd", 0.0)
    avail = acct.get("available_balance_usd", 0.0)
    unreal = acct.get("unrealized_pnl_usd", 0.0)
    margin_ratio = acct.get("margin_ratio_pct", 0.0)
    bnb_bal = acct.get("bnb_balance", 0.0)
    bnb_active = acct.get("bnb_fee_discount_active", False)
    positions = acct.get("positions", [])

    print(f" Engine State    : {bot_state}")
    print(f" Instance Role   : {inst_tag} [{role}]")
    if guard_msg and role == "PASSIVE_OBSERVER":
        print(f" Cloud Guard     : [!] {guard_msg}")
    print(f" Execution Mode  : {exec_mode}")
    print(f" Binance Futures : {'CONNECTED (HTTP 200)' if connected else 'DISCONNECTED'}")
    if error_msg:
        print(f" Connection Note : {error_msg}")
        if "request ip:" in error_msg:
            detected_ip = error_msg.split("request ip:")[-1].strip()
            print(f" [!] ACTION REQ   : Add '{detected_ip}' to your Binance IP Whitelist.")
    print(f" Wallet Balance  : ${wallet:,.2f} USDT")
    print(f" Free Collateral : ${avail:,.2f} USDT")
    print(f" Unrealized PnL  : {'+' if unreal >= 0 else ''}${unreal:,.2f} USDT")
    print(f" Margin Ratio    : {margin_ratio:.2f}% ({'SAFE' if margin_ratio < 20 else 'MODERATE'})")
    print(f" BNB Fee Buffer  : {bnb_bal:.4f} BNB ({'10% Discount ACTIVE' if bnb_active else 'Inactive'})")
    print(f" Active Trades   : {len(positions)} positions open")

    if positions:
        print("-" * 76)
        print(f" {'SYMBOL':<10} {'SIDE':<6} {'SIZE':<8} {'ENTRY':<12} {'MARK':<12} {'PNL (USD)':<10}")
        print("-" * 76)
        for p in positions:
            sym = p.get("symbol")
            side = p.get("side")
            amt = p.get("position_amt")
            entry = float(p.get("entry_price", 0))
            mark = float(p.get("mark_price", 0))
            pnl = float(p.get("unrealized_pnl_usd", 0))
            print(f" {sym:<10} {side:<6} {amt:<8} ${entry:<11.2f} ${mark:<11.2f} {'+' if pnl >= 0 else ''}${pnl:.2f}")

    print("=" * 76)
    print(" Dashboard URL   : http://localhost:7070")
    print(" Standalone Logs : logs/kronos_standalone.log")
    print("=" * 76)

if __name__ == "__main__":
    main()
