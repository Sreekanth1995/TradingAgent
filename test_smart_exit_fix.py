import unittest
from unittest.mock import MagicMock, patch
import logging
import sys
import os

# Add current directory to path
sys.path.append(os.getcwd())

from super_order_engine import SuperOrderEngine
from broker_dhan import DhanClient

# Configure logging to see output during tests
logging.basicConfig(level=logging.INFO)

class TestSmartExitFix(unittest.TestCase):
    def setUp(self):
        self.mock_broker = MagicMock()
        self.engine = SuperOrderEngine(self.mock_broker)
        # Mock IST for consistency
        self.engine.IST = MagicMock()
        
    def test_smart_exit_with_missing_orders_but_open_position(self):
        """
        Scenario: No pending orders found for a security ID, but a position is still open.
        Expected: Engine should check positions and place a MARKET exit order.
        """
        symbol = "NIFTY_25800_CE"
        sec_id = "42536"
        state = {
            'side': 'CALL',
            'symbol': symbol,
            'security_id': sec_id,
            'entry_id': '123',
            'quantity': 65
        }
        
        # 1. Mock LTP fetch
        self.mock_broker.get_ltp.return_value = 100.0
        
        # 2. Mock pending orders to be EMPTY (the bug scenario)
        self.mock_broker.get_pending_orders.return_value = []
        
        # 3. Mock positions to show an OPEN position
        self.mock_broker.get_positions.return_value = [
            {'securityId': sec_id, 'netQty': '65'}
        ]
        
        # 4. Run _close_position
        self.engine._close_position("NIFTY", state)
        
        # 5. Verify that place_sell_order was called as fallback
        self.mock_broker.place_sell_order.assert_called_once()
        args, kwargs = self.mock_broker.place_sell_order.call_args
        self.assertEqual(args[0], symbol)
        self.assertEqual(args[1]['order_type'], 'MARKET')
        self.assertEqual(args[1]['security_id'], sec_id)
        self.assertEqual(args[1]['quantity'], 65)

    def test_smart_exit_with_no_orders_and_no_position(self):
        """
        Scenario: No pending orders and NO open position.
        Expected: Logic should just log and clear state without placing any orders.
        """
        symbol = "NIFTY_25800_CE"
        sec_id = "42536"
        state = {
            'side': 'CALL',
            'symbol': symbol,
            'security_id': sec_id,
            'entry_id': '123',
            'quantity': 65
        }
        
        self.mock_broker.get_ltp.return_value = 100.0
        self.mock_broker.get_pending_orders.return_value = []
        self.mock_broker.get_positions.return_value = [] # Empty positions
        
        self.engine._close_position("NIFTY", state)
        
        # Verify NO place_sell_order call
        self.mock_broker.place_sell_order.assert_not_called()

    def test_broker_pending_orders_flexible_keys(self):
        """
        Test that get_pending_orders handles both securityId and security_id.
        """
        real_broker = DhanClient()
        real_broker.dhan = MagicMock()
        
        # Mock order list with mixed keys
        mock_orders = [
            {'orderId': '1', 'orderStatus': 'PENDING', 'securityId': '42536', 'transactionType': 'SELL'},
            {'orderId': '2', 'orderStatus': 'PENDING', 'security_id': '42536', 'transactionType': 'SELL'},
            {'orderId': '3', 'orderStatus': 'PENDING', 'securityId': '99999', 'transactionType': 'SELL'}
        ]
        real_broker.dhan.get_order_list.return_value = {'status': 'success', 'data': mock_orders}
        
        pending = real_broker.get_pending_orders("42536")
        
        # Should find both order 1 and 2
        self.assertEqual(len(pending), 2)
        oids = [o['orderId'] for o in pending]
        self.assertIn('1', oids)
        self.assertIn('2', oids)

if __name__ == '__main__':
    unittest.main()
