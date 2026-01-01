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

    print("\n" + "="*90)
    print(f"{'TIME':<20} | {'INDEX':<6} | {'SPOT':<8} | {'SIDE':<5} | {'RANK':<5} | {'ACTION':<25}")
    print("-" * 90)

    try:
        with open('test_data.csv', mode='r') as f:
            reader = csv.DictReader(f)
            rows = list(reader)[::-1]

            for row in rows:
                time_str = row['Time']
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
                    
                    # Parse Time for Engine Filter
                    # 2025-12-30T09:15:00Z -> datetime
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
                 # Use the last known price from the final row
                 # Warning: This assumes 'current_price' is available from the last iteration
                 # We construct a dummy leg_data with the last price
                 logger.info(f"Force Closing {key} at {current_price}")
                 broker.place_sell_order(key, {'current_price': current_price})

    except FileNotFoundError:
        print("Error: test_data_2.csv not found.")
        return
    except Exception as e:
        print(f"Error during simulation: {e}")
        return

    print("="*90)
    print("\nSIMULATION SUMMARY")
    print("-" * 20)
    for trade in broker.trade_log:
        print(f"  {trade}")
    print("-" * 20)
    print(f"TOTAL PnL (Points): {broker.total_pnl:.2f}")
    print(f"OPEN POSITIONS: {list(broker.positions.keys())}")
    print("="*90 + "\n")

if __name__ == "__main__":
    simulate()
