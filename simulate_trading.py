import csv
import json
import logging
import re
import os
from datetime import datetime
import pytz
from ranking_engine import RankingEngine

# Configure Logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger("Simulation")

class MockBroker:
    def __init__(self):
        self.orders = []
        self.positions = {} # instrument_key -> {'qty': int, 'avg_price': float}
        self.total_pnl = 0.0
        self.trade_log = []
        self.trades_count = 0

    def get_itm_contract(self, underlying, side, spot_price):
        """Mock ITM selection for simulation"""
        strike = (round(float(spot_price) / 50) * 50) + (-100 if side == 'CE' else 100)
        return {
            "symbol": f"{underlying}_{int(strike)}_{side}",
            "security_id": "mock_id",
            "strike": strike,
            "expiry": "2025-12-31"
        }

    def place_buy_order(self, instrument_key, leg_data):
        price = float(leg_data.get('current_price', 0))
        qty = int(leg_data.get('quantity', 1))
        
        if instrument_key not in self.positions:
            self.positions[instrument_key] = {'qty': 0, 'avg_price': 0.0}
        
        pos = self.positions[instrument_key]
        new_qty = pos['qty'] + qty
        pos['avg_price'] = ((pos['avg_price'] * pos['qty']) + (price * qty)) / new_qty
        pos['qty'] = new_qty
        
        self.trade_log.append(f"OPEN {instrument_key} @ {price}")
        return {'success': True}

    def place_sell_order(self, instrument_key, leg_data):
        price = float(leg_data.get('current_price', 0))
        
        if instrument_key in self.positions and self.positions[instrument_key]['qty'] > 0:
            pos = self.positions[instrument_key]
            
            # PnL Calculation (Spot Proxy)
            # CALL: (Exit - Entry) * Qty
            # PUT:  (Entry - Exit) * Qty (Inverse PnL)
            if 'PE' in instrument_key or 'PUT' in instrument_key:
                 pnl = (pos['avg_price'] - price) * pos['qty']
            else:
                 pnl = (price - pos['avg_price']) * pos['qty']

            self.total_pnl += pnl
            self.trades_count += 1
            self.trade_log.append(f"CLOSE {instrument_key} @ {price} | PnL: {pnl:.2f}")
            del self.positions[instrument_key]
            return {'success': True}
        
        return {'success': False, 'error': 'No position to sell'}

def simulate():
    broker = MockBroker()
    # Disable Redis for simulation
    os.environ["REDIS_HOST"] = "" 
    engine = RankingEngine(broker)
    
    # Regex from server.py
    ticker_pattern = re.compile(r"([A-Z]+)(\d{2})(\d{2})(\d{2})([CP])(\d+)")

    daily_stats = {} # date -> {'pnl': float, 'trades': int}
    current_day = None

    print("\n" + "="*90)
    print(f"{'TIME':<20} | {'INDEX':<6} | {'SPOT':<8} | {'SIDE':<5} | {'RANK':<5} | {'ACTION':<25}")
    print("-" * 90)

    try:
        with open('test_data.csv', mode='r') as f:
            reader = csv.DictReader(f)
            rows = list(reader)[::-1]

            for row in rows:
                time_str = row['Time']
                date_str = time_str[:10]
                
                if current_day is None:
                    current_day = date_str
                    day_start_pnl = broker.total_pnl
                    day_start_trades = broker.trades_count
                
                # Day change detection for reporting
                if date_str != current_day:
                    # Logic for daily square-off in simulation
                    if broker.positions:
                        # Use the last known price from the PREVIOUS row (last signal of the day)
                        # We need to get the last price we processed. Let's store it.
                        logger.info(f"End of Day {current_day}: Force-Squaring Off {list(broker.positions.keys())}")
                        for key in list(broker.positions.keys()):
                             broker.place_sell_order(key, {'current_price': last_price})

                    daily_gain = broker.total_pnl - day_start_pnl
                    daily_trades = broker.trades_count - day_start_trades
                    daily_stats[current_day] = {'pnl': daily_gain, 'trades': daily_trades}
                    print(f"\n--- DAILY SUMMARY for {current_day}: {daily_gain:.2f} Points | Trades: {daily_trades} ---")
                    
                    # Reset State for New Day
                    current_day = date_str
                    day_start_pnl = broker.total_pnl
                    day_start_trades = broker.trades_count
                    engine.memory_store = {} # Clear Rank, Side, and Active Contract
                    logger.info(f"--- STARTING NEW DAY: {current_day} ---")

                alert_name = row['Name']
                description_json = row['Description']
                try:
                    data = json.loads(description_json)
                except: continue

                timeframe = data.get('timeframe', 1)
                for leg in data.get('order_legs', []):
                    ticker = leg.get('ticker', 'NIFTY')
                    match = ticker_pattern.match(ticker)
                    if match:
                         underlying = match.groups()[0]
                    else:
                         underlying = "NIFTY"
                    
                    transaction_type = leg.get('transactionType')
                    current_price = float(leg.get('current_price', 0))
                    last_price = current_price # Store for daily square-off
                    
                    # Parse Time for Engine Filter
                    try:
                        # Parse as UTC
                        dt_utc = datetime.strptime(time_str, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=pytz.UTC)
                        # Convert to IST
                        dt_obj = dt_utc.astimezone(pytz.timezone('Asia/Kolkata'))
                    except:
                        dt_obj = None

                    # Process Signal (Index Mode)
                    res = engine.process_signal(underlying, transaction_type, int(timeframe), leg, now_override=dt_obj)
                    
                    action = res['action']
                    new_rank = res.get('new_rank', 0)
                    side = res.get('side', 'NONE')
                    
                    print(f"{time_str:<20} | {underlying:<6} | {current_price:<8.2f} | {side:<5} | {new_rank:<5} | {action:<25}")
            # End of Data Cleanup: Close any open positions
            print("-" * 30)
            print("End of Simulation: Closing open positions...")
            for key in list(broker.positions.keys()):
                 logger.info(f"Force Closing {key} at {current_price}")
                 broker.place_sell_order(key, {'current_price': current_price})
            
            # Final day summary
            daily_gain = broker.total_pnl - day_start_pnl
            daily_trades = broker.trades_count - day_start_trades
            daily_stats[current_day] = {'pnl': daily_gain, 'trades': daily_trades}
            print(f"\n--- DAILY SUMMARY for {current_day}: {daily_gain:.2f} Points | Trades: {daily_trades} ---")

    except FileNotFoundError:
        print("Error: test_data.csv not found.")
        return
    except Exception as e:
        print(f"Error during simulation: {e}")
        return

    print("="*90)
    print("\nSIMULATION SUMMARY")
    print("-" * 40)
    print(f"{'Date':<12} | {'PnL (Points)':<13} | {'Trades':<8}")
    print("-" * 40)
    for date, stats in daily_stats.items():
        print(f"  {date:<10} | {stats['pnl']:>13.2f} | {stats['trades']:>8}")
    print("-" * 40)
    print(f"TOTAL PnL (Points): {broker.total_pnl:.2f}")
    print(f"TOTAL TRADES:       {broker.trades_count}")
    print(f"OPEN POSITIONS: {list(broker.positions.keys())}")
    print("="*90 + "\n")

if __name__ == "__main__":
    simulate()
