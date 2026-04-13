import logging
import datetime
import pytz
from super_order_engine import SuperOrderEngine
from broker_dhan import DhanClient

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

IST = pytz.timezone('Asia/Kolkata')

def test_daily_reset():
    print("\n--- STARTING DAILY RESET TEST ---")
    
    # Setup
    broker = DhanClient()
    engine = SuperOrderEngine(broker)
    
    # Mock Data
    symbol = "NIFTY"
    leg_data = {"symbol": "NIFTY", "strike_price": 25000, "quantity": 75, "current_price": 25100}
    
    # Day 1: Send a signal
    day1 = datetime.datetime(2026, 1, 28, 10, 0, 0, tzinfo=IST)
    print(f"\n[Step 1] Day 1 ({day1.date()}): Send Sell (1m)")
    res1 = engine.process_signal(symbol, "S", 1, leg_data, now_override=day1)
    print(f"Action: {res1['action']}, Rank: {res1['new_rank']}")
    assert res1['new_rank'] == -1
    
    # Day 1: Send same signal again (Deduplicated)
    print("\n[Step 2] Day 1: Send Sell (1m) again")
    res2 = engine.process_signal(symbol, "S", 1, leg_data, now_override=day1)
    print(f"Action: {res2['action']}")
    assert res2['action'] == "SKIPPED_TOGGLE"

    # Day 2: Send same signal (Should be PROCESSED because of reset)
    day2 = datetime.datetime(2026, 1, 29, 10, 0, 0, tzinfo=IST)
    print(f"\n[Step 3] Day 2 ({day2.date()}): Send Sell (1m) again")
    # In Step 3, before processing the signal, the engine should reset.
    # So the current_rank for Step 3 should be 0 because of the reset.
    res3 = engine.process_signal(symbol, "S", 1, leg_data, now_override=day2)
    print(f"Action: {res3['action']}, Rank: {res3['new_rank']}")
    
    # Check that it was NOT ignored as a duplicate
    assert res3['action'] != "SKIPPED_TOGGLE"
    # Rank should be -1 because it reset to 0 and then processed the Sell (1m)
    assert res3['new_rank'] == -1
    
    print("\n✅ DAILY RESET TEST PASSED (Rank and Toggles reset)")

if __name__ == "__main__":
    test_daily_reset()
