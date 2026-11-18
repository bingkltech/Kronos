"""
scripts/reconstruct_live_trades.py
Reconstruct and evaluate all real-money live trades from Binance USD(S)-M Futures.
"""
from src.quant.binance_execution import BinanceAtomicExecutor
from decimal import Decimal
import datetime
import json

def reconstruct_trades():
    executor = BinanceAtomicExecutor()
    # Fetch all live trades (up to 1000 fills)
    fills = executor.get_live_trade_history(limit=1000, force_refresh=True)
    
    # Sort chronological (oldest to newest)
    fills.sort(key=lambda x: x["time"])
    
    print(f"Total Live Fills Loaded: {len(fills)}")
    print(f"Earliest fill: {fills[0]['time']} | Latest fill: {fills[-1]['time']}")
    
    # Separate into Scalper and Macro
    scalp_fills = [f for f in fills if f["is_scalp"]]
    macro_fills = [f for f in fills if not f["is_scalp"]]
    
    print(f"Macro Fills: {len(macro_fills)} | Scalp Fills: {len(scalp_fills)}")
    
    def process_fills(fill_list, strat_name):
        print("\n" + "=" * 90)
        print(f"REAL-MONEY LIVE AUDIT: {strat_name}")
        print("=" * 90)
        
        # Group closing fills by (symbol, order_id) or order execution
        # In Binance Futures, closing orders realize PnL
        # Let's group by symbol and match positions using a FIFO inventory
        positions = {} # sym -> list of open lots: [{"time", "price", "qty", "side", "order_id", "fee_usd"}]
        closed_trades = []
        
        total_realized_pnl = Decimal("0")
        total_fees = Decimal("0")
        
        for f in fill_list:
            sym = f["symbol"]
            side = f["side"]
            price = Decimal(f["price"])
            qty = Decimal(f["quantity"])
            realized_pnl = Decimal(f["realized_pnl_usd"])
            fee_usd = Decimal(f["fee_usd"])
            t_time = f["time"]
            order_id = f["order_id"]
            trade_id = f["trade_id"]
            
            total_fees += fee_usd
            total_realized_pnl += realized_pnl
            
            # Check if this fill is a closing trade
            if sym not in positions:
                positions[sym] = []
                
            open_lots = positions[sym]
            
            # If no open lots, or same side, add to open lots
            if not open_lots or open_lots[0]["side"] == side:
                open_lots.append({
                    "time": t_time,
                    "price": price,
                    "qty": qty,
                    "side": side,
                    "order_id": order_id,
                    "fee_usd": fee_usd
                })
            else:
                # Opposite side -> closing lots
                close_qty = qty
                entry_prices = []
                entry_times = []
                closed_entry_fees = Decimal("0")
                
                while close_qty > Decimal("0") and open_lots:
                    lot = open_lots[0]
                    if lot["qty"] <= close_qty:
                        entry_prices.append((lot["price"], lot["qty"]))
                        entry_times.append(lot["time"])
                        closed_entry_fees += lot["fee_usd"]
                        close_qty -= lot["qty"]
                        open_lots.pop(0)
                    else:
                        entry_prices.append((lot["price"], close_qty))
                        entry_times.append(lot["time"])
                        # partial fee
                        closed_entry_fees += lot["fee_usd"] * (close_qty / lot["qty"])
                        lot["qty"] -= close_qty
                        lot["fee_usd"] -= lot["fee_usd"] * (close_qty / lot["qty"])
                        close_qty = Decimal("0")
                        
                # Weighted entry price
                tot_matched_qty = sum(q for p, q in entry_prices)
                if tot_matched_qty > 0:
                    avg_entry_price = sum(p * q for p, q in entry_prices) / tot_matched_qty
                    first_entry_time = entry_times[0]
                    entry_side = "BUY" if side == "SELL" else "SELL" # position side was opposite of closing fill
                    
                    closed_trades.append({
                        "symbol": sym,
                        "side": entry_side,
                        "entry_time": first_entry_time,
                        "exit_time": t_time,
                        "avg_entry_price": avg_entry_price,
                        "exit_price": price,
                        "quantity": tot_matched_qty,
                        "notional": avg_entry_price * tot_matched_qty,
                        "realized_pnl": realized_pnl,
                        "entry_fee_usd": closed_entry_fees,
                        "exit_fee_usd": fee_usd,
                        "total_fee_usd": closed_entry_fees + fee_usd,
                        "net_pnl": realized_pnl - (closed_entry_fees + fee_usd),
                        "order_id": order_id
                    })
                    
        # Print summary of closed trades
        print(f"Total Reconstructed Closed Round-Trip Trades: {len(closed_trades)}")
        
        wins = 0
        losses = 0
        gross_win_usd = Decimal("0")
        gross_loss_usd = Decimal("0")
        
        for i, ct in enumerate(closed_trades, 1):
            net = ct["net_pnl"]
            pnl = ct["realized_pnl"]
            fee = ct["total_fee_usd"]
            notional = ct["notional"]
            ret_pct = (pnl / notional * 100) if notional > 0 else Decimal("0")
            
            # Duration calculation
            t0 = datetime.datetime.fromisoformat(ct["entry_time"])
            t1 = datetime.datetime.fromisoformat(ct["exit_time"])
            dur_sec = int((t1 - t0).total_seconds())
            dur_str = f"{dur_sec // 60}m {dur_sec % 60}s" if dur_sec < 3600 else f"{dur_sec / 3600:.1f}h"
            
            is_win = net > Decimal("0")
            if is_win:
                wins += 1
                gross_win_usd += pnl
            else:
                losses += 1
                gross_loss_usd += abs(pnl)
                
            res_str = "WIN " if is_win else "LOSS"
            print(f"[{i:02d}] {ct['symbol']:<12} {ct['side']:<4} | Net: ${net:>7.4f} (Gross: ${pnl:>7.4f}, Fee: ${fee:>6.4f}, {ret_pct:>+6.2f}%) | Notional: ${notional:>6.2f} | Dur: {dur_str:>7} | {res_str} | Entry: {ct['avg_entry_price']:.4f} -> Exit: {ct['exit_price']:.4f} ({t1.strftime('%m-%d %H:%M')})")
            
        win_rate = (wins / len(closed_trades) * 100) if closed_trades else 0
        profit_factor = (gross_win_usd / gross_loss_usd) if gross_loss_usd > 0 else (Decimal("999") if gross_win_usd > 0 else Decimal("0"))
        
        net_total = sum(ct["net_pnl"] for ct in closed_trades)
        gross_total = sum(ct["realized_pnl"] for ct in closed_trades)
        fees_total = sum(ct["total_fee_usd"] for ct in closed_trades)
        
        print("-" * 90)
        print(f"{strat_name} SUMMARY:")
        print(f"  Closed Trades: {len(closed_trades)} | Wins: {wins} | Losses: {losses} | Win Rate: {win_rate:.1f}%")
        print(f"  Gross Realized PnL: ${gross_total:.4f} USDT")
        print(f"  Exchange Fees Paid: ${fees_total:.4f} USDT")
        print(f"  Net Realized PnL:   ${net_total:.4f} USDT")
        print(f"  Profit Factor:      {profit_factor:.2f}x")
        print(f"  Open/Unmatched lots: { {k: len(v) for k, v in positions.items() if len(v) > 0} }")
        
        return closed_trades

    macro_closed = process_fills(macro_fills, "MACRO SWING STRATEGY (LIVE REAL MONEY)")
    scalp_closed = process_fills(scalp_fills, "LIGHTNING SCALPER STRATEGY (LIVE REAL MONEY)")

if __name__ == "__main__":
    reconstruct_trades()
