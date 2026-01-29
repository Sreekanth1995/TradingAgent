import logging
import json
from unittest.mock import MagicMock
from ranking_engine import RankingEngine

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

def test_manual_exit():
    print("\n--- TESTING MANUAL EXIT ALL ---")
    
    broker = MagicMock()
    broker.get_itm_contract.return_value = {"symbol": "NIFTY_25000_CE", "security_id": "123"}
    broker.place_buy_order.return_value = {"success": True}
    
    engine = RankingEngine(broker)
    symbol = "NIFTY"
    leg_data = {"symbol": "NIFTY", "current_price": 25100}

    # 1. Setup an active position and rank
    print("[Step 1] Setting up active position and rank")
    engine._open_new_trend(symbol, "CALL", 3, leg_data)
    engine._set_rank(symbol, 3)
    
    # Verify setup
    assert engine._get_rank(symbol) == 3
    assert engine._get_active_contract(symbol) is not None
    assert engine._get_global_side() == "CALL"

    # 2. Trigger Manual Exit
    print("[Step 2] Triggering manual_exit_all")
    engine.manual_exit_all()

    # 3. Verify results
    print("[Step 3] Verifying ranks and positions are reset")
    assert engine._get_rank(symbol) == 0
    assert engine._get_active_contract(symbol) is None
    assert engine._get_global_side() == "NONE"
    
    # 4. Verify broker was called to sell
    broker.place_sell_order.assert_called_once()
    print("✅ Broker place_sell_order was called.")

    print("\n✅ MANUAL EXIT ALL TEST PASSED")

if __name__ == "__main__":
    test_manual_exit()
