import logging
import datetime
import pytz
from super_order_engine import SuperOrderEngine
from broker_dhan import DhanClient

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

IST = pytz.timezone('Asia/Kolkata')

def test_signed_rank():
    print("\n--- STARTING WEIGHTED SIGNED RANK STRATEGY TEST ---")
    
    # Setup
    broker = DhanClient()
    engine = SuperOrderEngine(broker)
    
    # Mock Data
    symbol = "NIFTY"
    leg_data = {"symbol": "NIFTY", "strike_price": 25000, "quantity": 75, "current_price": 25100}
    now_ist = datetime.datetime.now(IST).replace(hour=10, minute=0, second=0)

    # 1. Starting at 0 rank
    print("\n[Step 1] Initial State")
    assert engine._get_rank(symbol) == 0
    assert engine._get_global_side() == "NONE"

    # 2. Buy signal (1m) -> rank +1 (Weight 1), Open CALL
    print("\n[Step 2] Sending Buy (1m)")
    res2 = engine.process_signal(symbol, "B", 1, leg_data, now_override=now_ist)
    print(f"Action: {res2['action']}, Rank: {res2['new_rank']}, Side: {res2['side']}")
    assert res2['new_rank'] == 1
    assert res2['side'] == "CALL"
    assert res2['action'] == "OPEN_CALL"

    # 3. Buy (5m) -> rank +4 (1 + 3), Uphold CALL
    print("\n[Step 3] Sending Buy (5m) - Weight 3")
    res3 = engine.process_signal(symbol, "B", 5, leg_data, now_override=now_ist)
    print(f"Action: {res3['action']}, Rank: {res3['new_rank']}")
    assert res3['new_rank'] == 4
    assert res3['action'] == "UPHOLD_CALL"

    # 4. Sell (1m) -> rank +3 (4 - 1), Decay CALL
    print("\n[Step 4] Sending Sell (1m) - Weight 1")
    res4 = engine.process_signal(symbol, "S", 1, leg_data, now_override=now_ist)
    print(f"Action: {res4['action']}, Rank: {res4['new_rank']}")
    assert res4['new_rank'] == 3
    assert res4['action'] == "DECAY_CALL"

    # 5. Zone touch -> rank +2 (3 - 1), Decay CALL
    print("\n[Step 5] Touching Zone (Rank 3 -> 2)")
    res5 = engine.process_signal(symbol, "ZONE", "TP1_HIGH", leg_data, now_override=now_ist)
    print(f"Action: {res5['action']}, Rank: {res5['new_rank']}")
    assert res5['new_rank'] == 2

    # 6. Sell (5m) -> rank -1 (2 - 3), Flip to PUT
    print("\n[Step 6] Sending Sell (5m) - Weight 3 -> Flip")
    res6 = engine.process_signal(symbol, "S", 5, leg_data, now_override=now_ist)
    print(f"Action: {res6['action']}, Rank: {res6['new_rank']}, Side: {res6['side']}")
    assert res6['new_rank'] == -1
    assert res6['side'] == "PUT"
    assert "OPEN_PUT" in res6['action']

    # 7. Buy (3m) -> rank +1 (-1 + 2), Flip to CALL
    print("\n[Step 7] Sending Buy (3m) - Weight 2 -> Flip Back")
    res7 = engine.process_signal(symbol, "B", 3, leg_data, now_override=now_ist)
    print(f"Action: {res7['action']}, Rank: {res7['new_rank']}, Side: {res7['side']}")
    assert res7['new_rank'] == 1
    assert res7['side'] == "CALL"
    assert "OPEN_CALL" in res7['action']

    print("\n✅ WEIGHTED SIGNED RANK STRATEGY TEST PASSED")

if __name__ == "__main__":
    test_signed_rank()
