import logging
import unittest
from unittest.mock import MagicMock
from ranking_engine import RankingEngine

# Setup Logging
logging.basicConfig(level=logging.INFO)

class TestDirectSignalStrategy(unittest.TestCase):
    def setUp(self):
        self.broker = MagicMock()
        self.engine = RankingEngine(self.broker)
        # Force in-memory for test
        self.engine.use_redis = False 
        self.engine.memory_store = {}
        
        # Mock Broker Responses
        self.broker.get_itm_contract.return_value = {
            "symbol": "NIFTY_24000_CE", 
            "security_id": "123456",
            "strike": 24000,
            "expiry": "2025-01-01"
        }
        self.broker.place_buy_order.return_value = {"success": True, "order_id": "ENTRY_ID_1"}
        self.broker.place_sell_order.return_value = {"success": True, "order_id": "EXIT_ID_1"}
        self.broker.cancel_order.return_value = {"success": True}
        
        # Mock Order Status (Fill simulation)
        self.broker.get_order_status.return_value = {
            "orderStatus": "TRADED",
            "averagePrice": 100.0,
            "price": 100.0
        }

    def test_buy_signal_native_bo(self):
        print("\n--- Testing BUY Signal (Native Super Order - Smart Entry) ---")
        underlying = "NIFTY"
        leg_data = {"transactionType": "B", "current_price": 24050, "quantity": 10}
        
        # 1. Setup Mock for Native BO Success
        self.broker.get_ltp.return_value = 100.0
        self.broker.place_super_order.return_value = {"success": True, "order_id": "BO_ID_1"}
        
        # 2. Trigger BUY
        res = self.engine.process_signal(underlying, "B", "TP0", leg_data)
        
        # Verify
        self.assertIn("OPENED_CALL", res['actions'])
        self.broker.get_ltp.assert_called()
        self.broker.place_super_order.assert_called()
        
        # Verify Arguments for BO
        args, _ = self.broker.place_super_order.call_args
        payload = args[1]
        
        # Smart Entry Check:
        # Price should be 100 - 5 = 95.0
        # Order Type should be LIMIT
        self.assertEqual(payload['order_type'], 'LIMIT')
        self.assertEqual(payload['price'], 95.0)
        
        # Target/SL Check (Based on LTP 100)
        self.assertEqual(payload['target_price'], 200.0) # 100 + 100
        self.assertEqual(payload['stop_loss_price'], 80.0) # 100 - 20

    def test_buy_signal_fallback(self):
        print("\n--- Testing BUY Signal (Fallback to Sim) ---")
        underlying = "BANKNIFTY"
        leg_data = {"transactionType": "B", "current_price": 44000, "quantity": 10}
        
        # 1. Setup Mock for Native BO Failure
        self.broker.get_ltp.return_value = None
        self.broker.place_super_order.return_value = {"success": False, "error": "Mock Fail"}
        
        # 2. Trigger BUY
        res = self.engine.process_signal(underlying, "B", "TP0", leg_data)
        
        # Verify fallback to place_buy_order
        self.broker.place_buy_order.assert_called()
        self.assertEqual(self.broker.place_super_order.call_count, 1) # Tries BO, fails, falls back
        # Actually my logic tries fallback if place_super_order ALSO fails. 
        # But if LTP is none, it skips BO block. Correct.

    def test_reverse_signal_native_cleanup(self):
        print("\n--- Testing REVERSAL (Native BO Cleanup) ---")
        underlying = "NIFTY"
        leg_data = {"transactionType": "S", "current_price": 24050, "quantity": 10}
        
        # Setup Initial State: Native BO
        self.engine._set_state(underlying, {
            'side': 'CALL',
            'entry_id': 'BO_ID_1',
            'is_super_order': True,
            'symbol': 'NIFTY_CE',
            'security_id': '111',
            'quantity': 10
        })
        
        self.broker.reset_mock()
        self.broker.get_ltp.return_value = 100.0
        self.broker.place_super_order.return_value = {"success": True, "order_id": "BO_ID_2"}
        self.broker.place_sell_order.return_value = {"success": True}
        self.broker.cancel_order.return_value = {"success": True}

        # Trigger SELL Signal
        res = self.engine.process_signal(underlying, "S", "TP0", leg_data)
        
        self.assertIn("CLOSED_CALL", res['actions'])
        
    def test_reversal_smart_exit(self):
        print("\n--- Testing REVERSAL (Smart Exit) ---")
        underlying = "NIFTY"
        leg_data = {"transactionType": "S", "current_price": 24050, "quantity": 10}
        
        # Setup: Open Long Position
        self.engine._set_state(underlying, {
            'side': 'CALL',
            'entry_id': 'BO_ID_1',
            'is_super_order': True,
            'symbol': 'NIFTY_CE',
            'security_id': '111',
            'quantity': 10
        })
        
        self.broker.reset_mock()
        
        # Mock LTP = 150
        self.broker.get_ltp.return_value = 150.0
        
        # Mock Pending Orders: Target @ 200, SL @ 80.
        self.broker.get_pending_orders.return_value = [
            {'orderId': 'TGT_LEG', 'securityId': '111', 'orderType': 'LIMIT', 'transactionType': 'SELL', 'price': 200.0},
            {'orderId': 'SL_LEG', 'securityId': '111', 'orderType': 'STOP_LOSS', 'transactionType': 'SELL', 'triggerPrice': 80.0}
        ]
        
        # Trigger SELL
        res = self.engine.process_signal(underlying, "S", "TP0", leg_data)
        
        # Verify Smart Exit Logic
        # 1. Should MODIFY Target to LTP + 5 = 155.0
        # 2. Should MODIFY SL to LTP - 10 = 140.0 (Since 80 < 140)
        
        modify_calls = self.broker.modify_order.call_args_list
        self.assertEqual(len(modify_calls), 2)
        
        # Check Target Mod
        tgt_call = next((c for c in modify_calls if c[0][0] == 'TGT_LEG'), None)
        self.assertIsNotNone(tgt_call)
        self.assertEqual(tgt_call[0][2]['price'], 155.0)
        
        # Check SL Mod
        sl_call = next((c for c in modify_calls if c[0][0] == 'SL_LEG'), None)
        self.assertIsNotNone(sl_call)
        self.assertEqual(sl_call[0][2]['trigger_price'], 140.0)
        
        # Verify NO Cancellation
        self.broker.cancel_order.assert_not_called()
        
        # Verify NO Market Exit
        self.broker.place_sell_order.assert_not_called()
        
        print("Verified: Smart Exit Modified Orders Correctly.")


    def test_reversal_unfilled_entry(self):
        print("\n--- Testing REVERSAL (Unfilled Entry - Cancel) ---")
        underlying = "NIFTY"
        leg_data = {"transactionType": "S", "current_price": 24050, "quantity": 10}
        
        # Setup: Bot has Open Request (Entry Order ID) but it is NOT filled.
        self.engine._set_state(underlying, {
            'side': 'CALL',
            'entry_id': 'ENTRY_BUY_1',
            'is_super_order': True,
            'symbol': 'NIFTY_CE',
            'security_id': '111',
            'quantity': 10
        })
        
        self.broker.reset_mock()
        self.broker.get_ltp.return_value = 100.0
        
        # Mock Pending Orders: ONE BUY (The unfilled entry), NO SELLS (Since entry didn't fill)
        self.broker.get_pending_orders.return_value = [
            {'orderId': 'ENTRY_BUY_1', 'securityId': '111', 'orderType': 'LIMIT', 'transactionType': 'BUY', 'price': 95.0, 'status': 'PENDING'}
        ]
        
        # Trigger SELL (Reversal)
        res = self.engine.process_signal(underlying, "S", "TP0", leg_data)
        
        # Verify
        # 1. Should CANCEL the BUY order (Entry)
        self.broker.cancel_order.assert_called_with('ENTRY_BUY_1')
        
        # 2. Should NOT Modify anything (No SELL orders)
        self.broker.modify_order.assert_not_called()
        
        # 3. Should NOT Place Market Exit (Since not open)
        self.broker.place_sell_order.assert_not_called()
        
        print("Verified: Unfilled Entry Cancelled Correctly.")

if __name__ == '__main__':
    unittest.main()
