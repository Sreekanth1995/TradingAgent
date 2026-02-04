import csv
import json
import logging
from datetime import datetime

# Configuration
TARGET_POINTS = 100
SL_POINTS = 20
TIMEFRAME_FILTER = "5" # 5m

def parse_csv(filepath):
    data = []
    with open(filepath, 'r') as f:
        reader = csv.reader(f)
        header = next(reader)
        for row in reader:
            try:
                # Format: Alert ID, Ticker, Name, Description, Time
                # Description is JSON
                desc = row[3]
                timestamp = row[4]
                try:
                    payload = json.loads(desc)
                except:
                    continue
                
                # Extract needed fields
                tf = payload.get('timeframe')
                legs = payload.get('order_legs', [])
                if not legs: continue
                
                leg = legs[0]
                price = float(leg.get('current_price', 0))
                txn = leg.get('transactionType')
                
                # Parse Time
                # 2026-01-19T09:49:02Z
                dt = datetime.strptime(timestamp, "%Y-%m-%dT%H:%M:%SZ")
                
                data.append({
                    "time": dt,
                    "price": price,
                    "tf": tf,
                    "txn": txn,
                    "raw": row
                })
            except Exception as e:
                pass
    
    # Sort by Time Ascending
    data.sort(key=lambda x: x['time'])
    return data

def run_backtest(data):
    position = None # { 'side': 'LONG'/'SHORT', 'entry': 100.0, 'sl': 90, 'tgt': 200 }
    pnl_log = []
    
    print(f"Running Backtest on {len(data)} data points...")
    
    for i, tick in enumerate(data):
        price = tick['price']
        dt = tick['time']
        
        # 1. Check Exits (SL/Target)
        if position:
            pnl = 0
            closed = False
            reason = ""
            
            if position['side'] == 'LONG':
                if price >= position['tgt']:
                    pnl = TARGET_POINTS
                    closed = True
                    reason = "TARGET"
                elif price <= position['sl']:
                    pnl = -SL_POINTS
                    closed = True
                    reason = "STOP_LOSS"
            
            elif position['side'] == 'SHORT':
                if price <= position['tgt']:
                    pnl = TARGET_POINTS
                    closed = True
                    reason = "TARGET"
                elif price >= position['sl']:
                    pnl = -SL_POINTS
                    closed = True
                    reason = "STOP_LOSS"
            
            if closed:
                pnl_log.append({
                    "date": dt.date(),
                    "time": dt.time(),
                    "pnl": pnl,
                    "reason": reason,
                    "side": position['side']
                })
                position = None
        
        # 2. Process Signals (Only 5m)
        if tick['tf'] == TIMEFRAME_FILTER:
            signal = tick['txn']
            
            # Reversal Logic
            if signal == 'B':
                # Close Short if Open
                if position and position['side'] == 'SHORT':
                    # Close at Current Price (Reversal)
                    # PnL = Entry - Current
                    p_pnl = position['entry'] - price
                    pnl_log.append({
                        "date": dt.date(),
                        "time": dt.time(),
                        "pnl": p_pnl,
                        "reason": "REVERSAL_SIGNAL",
                        "side": "SHORT"
                    })
                    position = None
                
                # Open Long (if not already long)
                if not position:
                    position = {
                        'side': 'LONG',
                        'entry': price,
                        'tgt': price + TARGET_POINTS,
                        'sl': price - SL_POINTS
                    }
            
            elif signal == 'S':
                 # Close Long if Open
                if position and position['side'] == 'LONG':
                    # Close at Current Price
                    # PnL = Current - Entry
                    p_pnl = price - position['entry']
                    pnl_log.append({
                        "date": dt.date(),
                        "time": dt.time(),
                        "pnl": p_pnl,
                        "reason": "REVERSAL_SIGNAL",
                        "side": "LONG"
                    })
                    position = None
                
                # Open Short
                if not position:
                    position = {
                        'side': 'SHORT',
                        'entry': price,
                        'tgt': price - TARGET_POINTS,
                        'sl': price + SL_POINTS
                    }

    return pnl_log

def generate_report(pnl_log):
    day_pnl = {}
    total_pnl = 0
    wins = 0
    losses = 0
    
    print("\n--- Trade Log ---")
    for trade in pnl_log:
        d = trade['date']
        p = trade['pnl']
        day_pnl[d] = day_pnl.get(d, 0) + p
        total_pnl += p
        if p > 0: wins += 1
        else: losses += 1
        # print(f"{trade['date']} {trade['time']} | {trade['side']} | {trade['reason']} | PnL: {p:.2f}")

    print("\n--- Day Wise Profit and Loss ---")
    sorted_days = sorted(day_pnl.keys())
    for d in sorted_days:
        print(f"{d}: {day_pnl[d]:.2f}")
    
    print("\n--- Summary ---")
    print(f"Total Trades: {len(pnl_log)}")
    print(f"Wins: {wins}")
    print(f"Losses: {losses}")
    print(f"Total PnL: {total_pnl:.2f}")

if __name__ == "__main__":
    data = parse_csv("test_data.csv")
    log = run_backtest(data)
    generate_report(log)
