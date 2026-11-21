import json
import urllib.request
import datetime
from decimal import Decimal, ROUND_HALF_UP

def main():
    url = "http://127.0.0.1:7072/api/live/trades?limit=1000"
    try:
        req = urllib.request.urlopen(url)
    except Exception:
        url = "http://localhost:7070/api/live/trades?limit=1000"
        req = urllib.request.urlopen(url)
    data = json.loads(req.read().decode("utf-8"))
    trades = data.get("trades", [])
    
    # Target 24h window: 2026-11-20 09:48:34 UTC to 2026-11-21 09:55:00 UTC
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    cutoff_24h = now_utc - datetime.timedelta(hours=24)
    
    recent_trades = []
    for t in trades:
        t_time_str = t.get("time")
        if not t_time_str:
            continue
        t_dt = datetime.datetime.fromisoformat(t_time_str)
        if t_dt.tzinfo is None:
            t_dt = t_dt.replace(tzinfo=datetime.timezone.utc)
        if t_dt >= cutoff_24h:
            recent_trades.append(t)
            
    print(f"=== 24-HOUR LIVE TRADE AUDIT ({cutoff_24h.strftime('%Y-%m-%d %H:%M:%S UTC')} to {now_utc.strftime('%Y-%m-%d %H:%M:%S UTC')}) ===")
    print(f"Total Fills in 24h: {len(recent_trades)}")
    
    # Group fills by closing order
    orders = {}
    for t in recent_trades:
        oid = str(t.get("order_id"))
        if oid not in orders:
            orders[oid] = {
                "symbol": t.get("symbol"),
                "side": t.get("side"),
                "time": t.get("time"),
                "order_id": oid,
                "trade_type": t.get("trade_type"),
                "fills": []
            }
        orders[oid]["fills"].append(t)
        
    closed_orders = []
    entry_orders = []
    
    for oid, o in orders.items():
        # check if this order has realized PnL != 0
        total_realized = sum(Decimal(str(f.get("realized_pnl_usd", "0"))) for f in o["fills"])
        total_fee = sum(Decimal(str(f.get("fee_usd", "0"))) for f in o["fills"])
        total_qty = sum(Decimal(str(f.get("quantity", "0"))) for f in o["fills"])
        weighted_px = sum(Decimal(str(f.get("price", "0"))) * Decimal(str(f.get("quantity", "0"))) for f in o["fills"]) / (total_qty if total_qty > 0 else 1)
        
        o["total_realized_gross"] = total_realized
        o["total_fee"] = total_fee
        o["net_pnl"] = total_realized - total_fee
        o["total_qty"] = total_qty
        o["avg_price"] = weighted_px
        
        if total_realized != Decimal("0"):
            closed_orders.append(o)
        else:
            entry_orders.append(o)
            
    closed_orders.sort(key=lambda x: x["time"])
    entry_orders.sort(key=lambda x: x["time"])
    
    print("\n--- CLOSED / EXIT EXECUTIONS (WINS & LOSSES) ---")
    total_gross = Decimal("0")
    total_fees = Decimal("0")
    total_net = Decimal("0")
    win_count = 0
    loss_count = 0
    
    for co in closed_orders:
        net = co["net_pnl"]
        gross = co["total_realized_gross"]
        fee = co["total_fee"]
        total_gross += gross
        total_fees += fee
        total_net += net
        is_win = gross > Decimal("0")
        if is_win:
            win_count += 1
            res_str = "WIN "
        else:
            loss_count += 1
            res_str = "LOSS"
            
        print(f"[{co['time']}] {res_str} | {co['symbol']} | Side: {co['side']} | Qty: {co['total_qty']} @ {co['avg_price']:.4f} | Gross: ${gross:+.4f} | Fee: ${fee:.4f} | Net: ${net:+.4f} | Order: {co['order_id']}")

    print("\n--- OPEN / ENTRY EXECUTIONS ---")
    for eo in entry_orders:
        print(f"[{eo['time']}] ENTRY | {eo['symbol']} | Side: {eo['side']} | Qty: {eo['total_qty']} @ {eo['avg_price']:.4f} | Fee: ${eo['total_fee']:.4f} | Order: {eo['order_id']}")

    print("\n=== 24-HOUR FINANCIAL AGGREGATE ===")
    print(f"Total Closed Decisions: {len(closed_orders)} (Wins: {win_count}, Losses: {loss_count})")
    win_rate = (win_count / len(closed_orders) * 100) if closed_orders else 0
    print(f"Win Rate: {win_rate:.1f}%")
    print(f"Gross Realized PnL: ${total_gross:+.4f} USDT")
    print(f"Total Exchange Fees: ${total_fees:.4f} USDT")
    print(f"Net Realized PnL:    ${total_net:+.4f} USDT")

if __name__ == "__main__":
    main()
