import unittest
from unittest.mock import MagicMock, patch
import logging
import sys
import os

# Add current directory to path
sys.path.append(os.getcwd())

from ranking_engine import RankingEngine

# Configure logging to see output during tests
logging.basicConfig(level=logging.INFO)

class TestSuperOrderSmartExitRefined(unittest.TestCase):
    def setUp(self):
        self.mock_broker = MagicMock()
        self.engine = RankingEngine(self.mock_broker)
        
    def test_smart_exit_super_order_modifies_each_leg_by_type(self):
        """
        Scenario: A Super Order is active and a counter signal triggers _close_position.
        Expected: 
          - TARGET_LEG should be modified to LTP + 5.
          - STOP_LOSS_LEG should be modified to LTP - 5.
        """
        symbol = "NIFTY_25800_CE"
        sec_id = "42536"
        state = {
            'side': 'CALL',
            'symbol': symbol,
            'security_id': sec_id,
            'entry_id': 'so_parent_999',
            'is_super_order': True,
            'quantity': 75
        }
        
        # 1. Mock LTP fetch
        ltp = 100.0
        self.mock_broker.get_ltp.return_value = ltp
        
        # 2. Mock pending orders
        # One Limit (Target) and one Stop Loss
        self.mock_broker.get_pending_orders.return_value = [
            {'orderId': 'oid_target', 'orderType': 'LIMIT', 'transactionType': 'SELL', 'securityId': sec_id},
            {'orderId': 'oid_sl', 'orderType': 'STOP_LOSS_MARKET', 'transactionType': 'SELL', 'securityId': sec_id}
        ]
        
        # 3. Process signal/close position
        self.engine._set_state("NIFTY", state)
        self.engine._close_position("NIFTY", state)
        
        # 4. Verify modify_super_order calls
        calls = self.mock_broker.modify_super_order.call_args_list
        self.assertEqual(len(calls), 2)
        
        # Check Target Modification
        target_call = next(c for c in calls if c.args[1] == 'TARGET_LEG')
        self.assertEqual(target_call.args[0], 'so_parent_999')
        self.assertEqual(target_call.args[2]['target_price'], 105.0)
        
        # Check SL Modification
        sl_call = next(c for c in calls if c.args[1] == 'STOP_LOSS_LEG')
        self.assertEqual(sl_call.args[0], 'so_parent_999')
        self.assertEqual(sl_call.args[2]['stop_loss_price'], 95.0)

    @patch('broker_dhan.requests.put')
    def test_broker_modify_super_order_payload(self, mock_put):
        """
        Scenario: Broker modify_super_order is called.
        Expected: Payload should have camelCase keys and rounded prices.
        """
        from broker_dhan import DhanClient
        broker = DhanClient()
        broker.client_id = "test_client"
        broker.access_token = "test_token"
        broker.dry_run = False
        
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_put.return_value = mock_resp
        
        broker.modify_super_order("parent_123", "TARGET_LEG", {"target_price": 105.123})
        
        # Verify JSON payload
        args, kwargs = mock_put.call_args
        payload = kwargs['json']
        
        self.assertEqual(payload['targetPrice'], 105.1) # Rounded to 0.05 (105.1 because 105.123 -> 105.1)
        self.assertEqual(payload['legName'], "TARGET_LEG")
        self.assertTrue(isinstance(payload['targetPrice'], float))

if __name__ == '__main__':
    unittest.main()
