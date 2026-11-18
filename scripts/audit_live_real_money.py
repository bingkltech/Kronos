"""
scripts/audit_live_real_money.py - Deep forensic audit of real live Binance trades (Macro & Scalper).
"""
import os
import json
import datetime
from decimal import Decimal, ROUND_HALF_UP
from src.quant.binance_execution import BinanceAtomicExecutor

def run_live_audit():
    executor = BinanceAtomicExecutor()
    bnb_price = executor.get_bnb_price()
    print(f"Current Live BNB Price: ${bnb_price:.2f}")

    # Load known scalp order IDs
    scalp_order_ids = set()
    if os.path.exists("data/scalp_orders.json"):
        with open("data/scalp_orders.json", "r") as f:
            d = json.load(f)
            if isinstance(d, list):
                scalp_order_ids = set(str(x) for x in d)

    print(f"Loaded {len(scalp_order_ids)} registered scalp order IDs from data/scalp_orders.json")

    # Symbols that have been traded
    symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "DOGEUSDT", "ADAUSDT", "LINKUSDT", "SUIUSDT", "1000PEPEUSDT", "AVAXUSDT"]

    all_orders_by_id = {}
    all_trades_by_sym = {}

    for sym in symbols:
        try:
            orders = executor._signed_request("GET", "/fapi/v1/allOrders", {"symbol": sym, "limit": 500})
            for o in orders:
                all_orders_by_id[str(o["orderId"])] = o
        except Exception as e:
            print(f"Error fetching orders for {sym}: {e}")

        try:
            trades = executor._signed_request("GET", "/fapi/v1/userTrades", {"symbol": sym, "limit": 500})
            all_trades_by_sym[sym] = trades
        except Exception as e:
            print(f"Error fetching trades for {sym}: {e}")

    print(f"Total Live Orders indexed: {len(all_orders_by_id)}")
    total_fills = sum(len(t) for t in all_trades_by_sym.values())
    print(f"Total Live Fills across symbols: {total_fills}")

    # Process each symbol into closed round-trip positions
    macro_trades = []
    scalp_trades = []

    for sym, fills in all_trades_by_sym.items():
        if not fills:
            continue
        # sort fills chronologically
        fills.sort(key=lambda x: x["time"])

        # We group fills by closing order
        # When an order has realizedPnl != 0, it is a closing execution
        closing_orders = {}
        for f in fills:
            pnl_dec = Decimal(str(f.get("realizedPnl", "0")))
            oid = str(f["orderId"])
            if pnl_dec != Decimal("0"):
                if oid not in closing_orders:
                    closing_orders[oid] = []
                closing_orders[oid].append(f)

        # Reconstruct inventory
        inventory = [] # list of {"time", "price", "qty", "side", "order_id", "fee_usd"}
        for f in fills:
            pnl_dec = Decimal(str(f.get("realizedPnl", "0")))
            price = Decimal(str(f["price"]))
            qty = Decimal(str(f["qty"]))
            oid = str(f["orderId"])
            side = f["side"] # BUY or SELL
            t_ms = f["time"]
            t_dt = datetime.datetime.fromtimestamp(t_ms / 1000, tz=datetime.timezone.utc)
            
            # fee calc
            comm = Decimal(str(f.get("commission", "0")))
            comm_asset = f.get("commissionAsset", "USDT")
            if comm_asset == "BNB":
                fee_usd = comm * bnb_price
            else:
                fee_usd = comm

            if pnl_dec == Decimal("0"):
                # Opening fill
                inventory.append({
                    "time": t_dt,
                    "price": price,
                    "qty": qty,
                    "side": side,
                    "order_id": oid,
                    "fee_usd": fee_usd
                })
            else:
                # Closing fill
                # Match against opposite inventory
                matched_entries = []
                matched_entry_fees = Decimal("0")
                rem_qty = qty
                while rem_qty > Decimal("0") and inventory:
                    lot = inventory[0]
                    if lot["side"] != side:
                        if lot["qty"] <= rem_qty:
                            matched_entries.append((lot["price"], lot["qty"], lot["time"], lot["order_id"]))
                            matched_entry_fees += lot["fee_usd"]
                            rem_qty -= lot["qty"]
                            inventory.pop(0)
                        else:
                            matched_entries.append((lot["price"], rem_qty, lot["time"], lot["order_id"]))
                            portion = rem_qty / lot["qty"]
                            matched_entry_fees += lot["fee_usd"] * portion
                            lot["qty"] -= rem_qty
                            lot["fee_usd"] -= lot["fee_usd"] * portion
                            rem_qty = Decimal("0")
                    else:
                        break

                tot_matched = sum(q for p, q, t, o in matched_entries)
                if tot_matched > 0:
                    avg_entry = sum(p * q for p, q, t, o in matched_entries) / tot_matched
                    entry_time = matched_entries[0][2]
                    pos_side = "BUY" if side == "SELL" else "SELL"
                    entry_oid = matched_entries[0][3]
                else:
                    avg_entry = price
                    entry_time = t_dt
                    pos_side = "BUY" if side == "SELL" else "SELL"
                    entry_oid = "UNKNOWN"

                # Check if entry or exit was a scalp
                order_info = all_orders_by_id.get(oid, {})
                client_oid = order_info.get("clientOrderId", "")
                entry_order_info = all_orders_by_id.get(entry_oid, {})
                entry_client_oid = entry_order_info.get("clientOrderId", "")

                is_scalp = (
                    oid in scalp_order_ids or
                    entry_oid in scalp_order_ids or
                    "scalp" in client_oid.lower() or
                    "scalp" in entry_client_oid.lower() or
                    "lightning" in client_oid.lower() or
                    "tiger" in client_oid.lower()
                )

                dur_sec = int((t_dt - entry_time).total_seconds())

                tot_fee = matched_entry_fees + fee_usd
                net_pnl = pnl_dec - tot_fee
                notional = avg_entry * qty

                trade_record = {
                    "symbol": sym,
                    "side": pos_side,
                    "entry_price": avg_entry,
                    "exit_price": price,
                    "quantity": qty,
                    "notional": notional,
                    "gross_pnl": pnl_dec,
                    "total_fee": tot_fee,
                    "net_pnl": net_pnl,
                    "entry_time": entry_time.isoformat(),
                    "exit_time": t_dt.isoformat(),
                    "duration_seconds": dur_sec,
                    "order_id": oid,
                    "client_order_id": client_oid,
                    "entry_client_order_id": entry_client_oid,
                    "is_scalp": is_scalp
                }

                if is_scalp:
                    scalp_trades.append(trade_record)
                else:
                    macro_trades.append(trade_record)

    # Consolidate partial fills that share the exact same closing order_id
    def consolidate_by_order(trade_list):
        grouped = {}
        for t in trade_list:
            oid = t["order_id"]
            if oid not in grouped:
                grouped[oid] = []
            grouped[oid].append(t)

        consolidated = []
        for oid, group in grouped.items():
            sym = group[0]["symbol"]
            side = group[0]["side"]
            tot_qty = sum(t["quantity"] for t in group)
            tot_notional = sum(t["notional"] for t in group)
            tot_gross = sum(t["gross_pnl"] for t in group)
            tot_fee = sum(t["total_fee"] for t in group)
            tot_net = sum(t["net_pnl"] for t in group)
            avg_entry = sum(t["entry_price"] * t["quantity"] for t in group) / tot_qty if tot_qty > 0 else Decimal("0")
            avg_exit = sum(t["exit_price"] * t["quantity"] for t in group) / tot_qty if tot_qty > 0 else Decimal("0")
            dur = group[0]["duration_seconds"]
            e_time = group[0]["entry_time"]
            x_time = group[-1]["exit_time"]
            cid = group[0]["client_order_id"]
            consolidated.append({
                "order_id": oid,
                "symbol": sym,
                "side": side,
                "quantity": tot_qty,
                "entry_price": avg_entry,
                "exit_price": avg_exit,
                "notional": tot_notional,
                "gross_pnl": tot_gross,
                "fee": tot_fee,
                "net_pnl": tot_net,
                "duration_seconds": dur,
                "entry_time": e_time,
                "exit_time": x_time,
                "client_order_id": cid
            })
        consolidated.sort(key=lambda x: x["exit_time"])
        return consolidated

    c_macro = consolidate_by_order(macro_trades)
    c_scalp = consolidate_by_order(scalp_trades)

    print("\n" + "=" * 90)
    print(f"CONSOLIDATED LIVE MACRO CLOSED TRADES: {len(c_macro)}")
    print("=" * 90)
    m_wins = [t for t in c_macro if t["net_pnl"] > 0]
    m_losses = [t for t in c_macro if t["net_pnl"] <= 0]
    m_gross = sum(t["gross_pnl"] for t in c_macro)
    m_fees = sum(t["fee"] for t in c_macro)
    m_net = sum(t["net_pnl"] for t in c_macro)
    print(f"Macro: {len(c_macro)} Trades | Wins: {len(m_wins)} | Losses: {len(m_losses)} | Win Rate: {len(m_wins)/len(c_macro)*100:.1f}%")
    print(f"Gross PnL: ${m_gross:.4f} | Fees: ${m_fees:.4f} | Net PnL: ${m_net:.4f}")

    print("\n" + "=" * 90)
    print(f"CONSOLIDATED LIVE LIGHTNING SCALP CLOSED TRADES: {len(c_scalp)}")
    print("=" * 90)
    s_wins = [t for t in c_scalp if t["net_pnl"] > 0]
    s_losses = [t for t in c_scalp if t["net_pnl"] <= 0]
    s_gross = sum(t["gross_pnl"] for t in c_scalp)
    s_fees = sum(t["fee"] for t in c_scalp)
    s_net = sum(t["net_pnl"] for t in c_scalp)
    s_wr = (len(s_wins)/len(c_scalp)*100) if c_scalp else 0
    print(f"Scalp: {len(c_scalp)} Trades | Wins: {len(s_wins)} | Losses: {len(s_losses)} | Win Rate: {s_wr:.1f}%")
    print(f"Gross PnL: ${s_gross:.4f} | Fees: ${s_fees:.4f} | Net PnL: ${s_net:.4f}")

    # Save to json for detailed reporting
    with open("data/live_audit_summary.json", "w") as f:
        json.dump({
            "macro_trades": [{k: str(v) if isinstance(v, Decimal) else v for k, v in t.items()} for t in c_macro],
            "scalp_trades": [{k: str(v) if isinstance(v, Decimal) else v for k, v in t.items()} for t in c_scalp],
            "macro_summary": {
                "count": len(c_macro),
                "wins": len(m_wins),
                "losses": len(m_losses),
                "win_rate": float(len(m_wins)/len(c_macro)*100) if c_macro else 0,
                "gross_pnl": str(m_gross),
                "fees": str(m_fees),
                "net_pnl": str(m_net)
            },
            "scalp_summary": {
                "count": len(c_scalp),
                "wins": len(s_wins),
                "losses": len(s_losses),
                "win_rate": float(s_wr),
                "gross_pnl": str(s_gross),
                "fees": str(s_fees),
                "net_pnl": str(s_net)
            }
        }, f, indent=2)

    print("\nSaved full trade audit to data/live_audit_summary.json")

if __name__ == "__main__":
    run_live_audit()
