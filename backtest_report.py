import csv
import json
import logging
from datetime import datetime
import pytz

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)

IST = pytz.timezone('Asia/Kolkata')

# Strategy Configs (Adapted for Spot Points simulation)
CONFIGS = {
    "NORMAL": {"target": 50, "sl": 20, "trailing": 15},
    "SCALPING": {"target": 20, "sl": 20, "trailing": 5}
}

# Expiry Days Simulation (Simplified for Backtest)
# NIFTY Expiry is usually Thursday. 
# February 2026: Feb 5, 12, 19, 26 are Thursdays.
EXPIRY_DAYS = ["2026-02-05", "2026-02-12", "2026-02-19", "2026-02-26"]


class BacktestEngine:
    def __init__(self, csv_path):
        self.csv_path = csv_path
        self.alerts = []
        self.daily_pnl = {}

    def load_data(self):
        with open(self.csv_path, 'r') as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    payload = json.loads(row['Description'])
                    time_str = row['Time']
                    # Handle TradingView time format e.g. 2026-02-18T09:55:02Z
                    dt = datetime.strptime(time_str, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=pytz.UTC).astimezone(IST)
                    
                    self.alerts.append({
                        "time": dt,
                        "date": dt.strftime('%Y-%m-%d'),
                        "name": row['Name'],
                        "payload": payload,
                        "timeframe": int(payload.get('timeframe', 5)),
                        "price": float(payload['order_legs'][0]['current_price']),
                        "type": payload['order_legs'][0]['transactionType'] # 'B' or 'S'
                    })
                except Exception as e:
                    # logger.warning(f"Skipping row due to error: {e}")
                    pass
        
        # Sort by time
        self.alerts.sort(key=lambda x: x['time'])
        logger.info(f"Loaded {len(self.alerts)} valid alerts.")

    def run(self):
        dates = sorted(list(set(a['date'] for a in self.alerts)))
        
        for date in dates:
            day_alerts = [a for a in self.alerts if a['date'] == date]
            self.daily_pnl[date] = self.simulate_day(date, day_alerts)

    def simulate_day(self, date, day_alerts):
        scalping_until = None
        active_trade = None # {type, entry_price, target, sl, timeframe}
        day_points = 0
        trade_count = 0
        wins = 0
        
        is_expiry_day = date in EXPIRY_DAYS
        
        for alert in day_alerts:
            now = alert['time']
            current_price = alert['price']
            
            # 1. Update Scalping Mode
            if alert['name'] == "Daily Volume":
                scalping_until = now.timestamp() + (5 * 60)
                continue
            
            # RankingEngine._is_scalping_active logic
            # Window checks
            h, m = now.hour, now.minute
            in_window1 = (h == 9 and m >= 20) or (h == 10 and m <= 35)
            in_window2 = (h == 14 and m >= 45) or (h == 15 and m <= 30)
            
            is_volume_scalping = scalping_until and scalping_until > now.timestamp()
            is_standard_scalping = (in_window1 or in_window2) and is_expiry_day
            
            is_scalping_active = is_volume_scalping or is_standard_scalping

            
            # 2. Check Timeframe Eligibility (ranking_engine.py logic)
            if alert['timeframe'] == 1 and not is_scalping_active:
                continue
            if alert['timeframe'] == 5 and is_scalping_active:
                continue
                
            # 3. Market Open Volatility Check (9:15 - 9:25 IST)
            if not is_scalping_active:
                if now.hour == 9 and 15 <= now.minute < 25:
                    continue

            # 4. Handle Active Trade
            if active_trade:
                # Check for Reversal or Exit
                exit_price = None
                reason = ""
                
                # Check for Target/SL hit by this alert's price
                if active_trade['type'] == 'B':
                    if current_price >= active_trade['target']:
                        exit_price = active_trade['target']
                        reason = "TARGET"
                    elif current_price <= active_trade['sl']:
                        exit_price = active_trade['sl']
                        reason = "SL"
                    elif alert['type'] == 'S':
                        exit_price = current_price
                        reason = "REVERSAL"
                else: # 'S'
                    if current_price <= active_trade['target']:
                        exit_price = active_trade['target']
                        reason = "TARGET"
                    elif current_price >= active_trade['sl']:
                        exit_price = active_trade['sl']
                        reason = "SL"
                    elif alert['type'] == 'B':
                        exit_price = current_price
                        reason = "REVERSAL"
                
                if exit_price:
                    pnl = (exit_price - active_trade['entry_price']) if active_trade['type'] == 'B' else (active_trade['entry_price'] - exit_price)
                    day_points += pnl
                    if pnl > 0: wins += 1
                    active_trade = None
                    if reason != "REVERSAL":
                        continue 


            # 5. Open New Trade
            if not active_trade:
                config = CONFIGS["SCALPING" if is_scalping_active else "NORMAL"]
                
                target = current_price + config['target'] if alert['type'] == 'B' else current_price - config['target']
                sl = current_price - config['sl'] if alert['type'] == 'B' else current_price + config['sl']
                
                active_trade = {
                    "type": alert['type'],
                    "entry_price": current_price,
                    "target": target,
                    "sl": sl
                }
                trade_count += 1

        # Close any open trade at the end of the day
        if active_trade:
            last_price = day_alerts[-1]['price']
            pnl = (last_price - active_trade['entry_price']) if active_trade['type'] == 'B' else (active_trade['entry_price'] - last_price)
            day_points += pnl
            if pnl > 0: wins += 1

        return {"points": round(day_points, 2), "trades": trade_count, "wins": wins}

    def print_report(self):
        print("\n" + "="*50)
        print(f"{'Date':<15} | {'Trades':<8} | {'Win Rate':<10} | {'P&L Points':<10}")
        print("-" * 50)
        total_pnl = 0
        total_trades = 0
        total_wins = 0
        for date in sorted(self.daily_pnl.keys()):
            pnl = self.daily_pnl[date]['points']
            trades = self.daily_pnl[date]['trades']
            wins = self.daily_pnl[date]['wins']
            win_rate = f"{(wins/trades*100):.1f}%" if trades > 0 else "0.0%"
            print(f"{date:<15} | {trades:<8} | {win_rate:<10} | {pnl:<10}")
            total_pnl += pnl
            total_trades += trades
            total_wins += wins
        
        overall_win_rate = f"{(total_wins/total_trades*100):.1f}%" if total_trades > 0 else "0.0%"
        avg_points = round(total_pnl/total_trades, 2) if total_trades > 0 else 0
        print("-" * 50)
        print(f"{'TOTAL':<15} | {total_trades:<8} | {overall_win_rate:<10} | {round(total_pnl, 2):<10}")
        print(f"Average Points per Trade: {avg_points}")
        print("="*50 + "\n")


if __name__ == "__main__":
    engine = BacktestEngine("test_data.csv")
    engine.load_data()
    engine.run()
    engine.print_report()
