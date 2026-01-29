import logging
import datetime
import pytz
import json
from unittest.mock import MagicMock
from ranking_engine import RankingEngine

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

IST = pytz.timezone('Asia/Kolkata')

def test_multiple_zone_hits():
    print("\n--- TESTING MULTIPLE HITS TO SAME ZONE ---")
    
    broker = MagicMock()
    broker.get_itm_contract.return_value = {
        "security_id": "12345",
        "symbol": "NIFTY_25000_CE"
    }
    broker.place_buy_order.return_value = {"success": True, "order_id": "mock_id"}
    
    engine = RankingEngine(broker)
    engine.timeframe_weights = {1: 1, 2: 1, 3: 1, 5: 1}
    
    symbol = "NIFTY"
    leg_data = {"symbol": "NIFTY", "strike_price": 25000, "quantity": 75, "current_price": 25100}
    now_ist = datetime.datetime.now(IST).replace(hour=10, minute=0, second=0)

    # 1. Establish a trend
    print("\n[Step 1] Opening position (Rank 3)")
    engine.process_signal(symbol, "B", 5, leg_data, now_override=now_ist)
    engine.process_signal(symbol, "B", 3, leg_data, now_override=now_ist)
    engine.process_signal(symbol, "B", 1, leg_data, now_override=now_ist)
    assert engine._get_rank(symbol) == 3

    # 2. First hit to UTP1_LOW
    print("\n[Step 2] Touching UTP1_LOW (First time)")
    res1 = engine.process_signal(symbol, "ZONE", "UTP1_LOW", leg_data, now_override=now_ist)
    print(f"Action: {res1['action']}, Rank: {res1['new_rank']}")
    assert res1['action'] == "ZONE_DECAY"
    assert res1['new_rank'] == 2

    # 3. Second hit to UTP1_LOW
    print("\n[Step 3] Touching UTP1_LOW again (Immediate Repeat)")
    res2 = engine.process_signal(symbol, "ZONE", "UTP1_LOW", leg_data, now_override=now_ist)
    print(f"Action: {res2['action']}, Rank: {res2['new_rank']}")
    assert res2['action'] == "SKIPPED_ZONE_TOGGLE"
    assert res2['new_rank'] == 2 # Rank should NOT decay again

    # 4. Hit a DIFFERENT zone
    print("\n[Step 4] Touching TP2_HIGH (Different Zone)")
    res3 = engine.process_signal(symbol, "ZONE", "TP2_HIGH", leg_data, now_override=now_ist)
    print(f"Action: {res3['action']}, Rank: {res3['new_rank']}")
    assert res3['action'] == "ZONE_DECAY"
    assert res3['new_rank'] == 1

    # 5. Hit original zone again
    print("\n[Step 5] Touching UTP1_LOW again (After switching zones)")
    res4 = engine.process_signal(symbol, "ZONE", "UTP1_LOW", leg_data, now_override=now_ist)
    print(f"Action: {res4['action']}, Rank: {res4['new_rank']}")
    assert res4['action'] == "ZONE_DECAY"
    assert res4['new_rank'] == 0 # Should decay now because ZONE_STATE changed
    
    print("\n✅ MULTIPLE ZONE HITS TEST PASSED")

if __name__ == "__main__":
    test_multiple_zone_hits()
