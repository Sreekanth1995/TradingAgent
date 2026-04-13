import logging
import datetime
import pytz
from unittest.mock import MagicMock
from super_order_engine import SuperOrderEngine

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

IST = pytz.timezone('Asia/Kolkata')

def test_manual_zone_logic():
    print("\n--- STARTING MANUAL ZONE LOGIC TEST (REFACTORED) ---")
    
    # Setup
    broker = MagicMock()
    broker.get_itm_contract.return_value = {
        "security_id": "12345",
        "strike": 25000,
        "expiry": "2026-02-05",
        "symbol": "NIFTY_25000_CE"
    }
    broker.place_buy_order.return_value = {"success": True, "order_id": "mock_id"}
    
    engine = SuperOrderEngine(broker)
    engine.timeframe_weights = {1: 1, 2: 1, 3: 1, 5: 1}
    
    # Mock Data
    symbol = "NIFTY"
    leg_data = {"symbol": "NIFTY", "strike_price": 25000, "quantity": 75, "current_price": 25100}
    now_ist = datetime.datetime.now(IST).replace(hour=10, minute=0, second=0)

    # 1. Open Position normally
    print("\n[Step 1] Opening position with high rank")
    engine.process_signal(symbol, "B", 5, leg_data, now_override=now_ist) # Rank 1
    engine.process_signal(symbol, "B", 3, leg_data, now_override=now_ist) # Rank 2
    engine.process_signal(symbol, "B", 1, leg_data, now_override=now_ist) # Rank 3
    print(f"Current Rank: {engine._get_rank(symbol)}")
    assert engine._get_rank(symbol) == 3
    
    # 2. TP0 Zone Decay Test (No Filtering)
    print("\n[Step 2] Entering TP0 Red Zone - Should only DECAY Rank")
    res5 = engine.process_signal(symbol, "ZONE", "TP0", leg_data, now_override=now_ist) 
    print(f"Action: {res5['action']}, Rank: {res5['new_rank']}, Side: {res5['side']}")
    assert res5['action'] == "ZONE_DECAY"
    assert res5['new_rank'] == 2
    
    # 3. No Weight Cap Test
    print("\n[Step 3] Sending Bullish Signal while in TP0 - Weight should be NORMAL (No Cap)")
    res6 = engine.process_signal(symbol, "B", 2, leg_data, now_override=now_ist)
    print(f"Action: {res6['action']}, Rank: {res6['new_rank']}")
    # Rank 2 + 1 = 3
    assert res6['new_rank'] == 3
    
    # 4. TP2 Zone Decay Test (No Profit Booking)
    print("\n[Step 4] Sending TP2 Alert - Should DECAY Rank (no profit booking)")
    res7 = engine.process_signal(symbol, "ZONE", "TP2_HIGH", leg_data, now_override=now_ist)
    print(f"Action: {res7['action']}, Rank: {res7['new_rank']}, Side: {res7['side']}")
    assert res7['action'] == "ZONE_DECAY"
    # Rank was 3, should be 2 now
    assert res7['new_rank'] == 2
    assert res7['side'] == "CALL"

    print("\n✅ REFACTORED MANUAL ZONE LOGIC TEST PASSED")

if __name__ == "__main__":
    test_manual_zone_logic()
