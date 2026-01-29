import logging
import datetime
import pytz
from unittest.mock import MagicMock
from ranking_engine import RankingEngine

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

IST = pytz.timezone('Asia/Kolkata')

def test_manual_zone_logic():
    print("\n--- STARTING MANUAL ZONE LOGIC TEST (FINAL) ---")
    
    # Setup
    broker = MagicMock()
    broker.get_itm_contract.return_value = {
        "security_id": "12345",
        "strike": 25000,
        "expiry": "2026-02-05",
        "symbol": "NIFTY_25000_CE"
    }
    broker.place_buy_order.return_value = {"success": True, "order_id": "mock_id"}
    
    engine = RankingEngine(broker)
    engine.timeframe_weights = {1: 1, 2: 1, 3: 1, 5: 1} # Weights are 1 in actual code now
    
    # Mock Data
    symbol = "NIFTY"
    leg_data = {"symbol": "NIFTY", "strike_price": 25000, "quantity": 75, "current_price": 25100}
    now_ist = datetime.datetime.now(IST).replace(hour=10, minute=0, second=0)

    # 1. TP0 Filter Test: Block New Entry
    print("\n[Step 1] TP0 Red Zone: Sending TP0 Alert")
    engine.process_signal(symbol, "ZONE", "TP0", leg_data, now_override=now_ist)
    
    print("[Step 2] Sending Buy (5m) while in TP0 - Should block")
    res2 = engine.process_signal(symbol, "B", 5, leg_data, now_override=now_ist)
    print(f"Action: {res2['action']}, Rank: {res2['new_rank']}")
    assert res2['action'] == "SKIPPED_TP0_FILTER"
    
    # 2. TP1 Alert: Move out of TP0
    print("\n[Step 3] Sending TP1 Alert (Exit Red Zone)")
    engine.process_signal(symbol, "ZONE", "TP1", leg_data, now_override=now_ist)
    
    # 3. Open Position normally
    print("[Step 4] Opening position with high rank")
    engine.process_signal(symbol, "B", 5, leg_data, now_override=now_ist) # Rank 1
    engine.process_signal(symbol, "B", 3, leg_data, now_override=now_ist) # Rank 2
    engine.process_signal(symbol, "B", 1, leg_data, now_override=now_ist) # Rank 3
    print(f"Current Rank: {engine._get_rank(symbol)}")
    assert engine._get_rank(symbol) == 3
    
    # 4. TP0 Weight Cap Test: Existing Position
    print("\n[Step 5] Entering TP0 Red Zone")
    engine.process_signal(symbol, "ZONE", "TP0", leg_data, now_override=now_ist) 
    # Zone decay: 3 -> 2
    print(f"Rank after TP0 entry (Decay): {engine._get_rank(symbol)}")
    assert engine._get_rank(symbol) == 2
    
    print("[Step 6] Sending Bullish Signal while in TP0 - Weight should be 1")
    # Normally signal toggle would ignore repeat 'B' if timeframe is same.
    # We use a different timeframe '2' to ensure it's a new signal bias.
    res8 = engine.process_signal(symbol, "B", 2, leg_data, now_override=now_ist)
    print(f"Action: {res8['action']}, Rank: {res8['new_rank']}")
    # Rank 2 + 1 (capped weight) = 3
    assert res8['new_rank'] == 3
    
    # 5. TP2 Zone Decay Test (No Profit Booking)
    print("\n[Step 7] Sending TP2 Alert - Should DECAY Rank (no profit booking)")
    res9 = engine.process_signal(symbol, "ZONE", "TP2_HIGH", leg_data, now_override=now_ist)
    print(f"Action: {res9['action']}, Rank: {res9['new_rank']}, Side: {res9['side']}")
    assert res9['action'] == "ZONE_DECAY"
    # Rank was 3, should be 2 now
    assert res9['new_rank'] == 2
    assert res9['side'] == "CALL"

    
    print("\n✅ MANUAL ZONE LOGIC TEST PASSED")

if __name__ == "__main__":
    test_manual_zone_logic()
