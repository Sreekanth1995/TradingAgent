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
    """
    The old _close_position smart-exit path was replaced by the streamlined
    exit_super_order: place a MARKET sell to flatten, cancel the bracket legs,
    clear state. These tests pin that behavior on the current engine.
    """

    def setUp(self):
        self.mock_broker = MagicMock()
        self.engine = SuperOrderEngine(self.mock_broker)
        self.engine.use_redis = False
        self.engine.memory_store = {}

    def test_exit_super_order_places_market_sell_and_clears_state(self):
        """Active position -> exit_super_order flattens with a MARKET SELL and clears state."""
        symbol = "NIFTY_25800_CE"
        sec_id = "42536"
        self.engine._set_state("NIFTY", {
            'side': 'CALL', 'symbol': symbol, 'security_id': sec_id,
            'entry_id': '123', 'quantity': 65,
        })
        self.mock_broker.place_order.return_value = {"success": True, "order_id": "EXIT_1"}

        res = self.engine.exit_super_order("NIFTY")

        self.assertTrue(res.get("success"))
        self.mock_broker.place_order.assert_called_once()
        args, kwargs = self.mock_broker.place_order.call_args
        self.assertEqual(args[0], symbol)
        self.assertEqual(args[1]['transaction_type'], 'SELL')
        self.assertEqual(args[1]['order_type'], 'MARKET')
        self.assertEqual(args[1]['security_id'], sec_id)
        self.assertEqual(args[1]['quantity'], 65)
        # State cleared after exit.
        self.assertEqual(self.engine._get_state("NIFTY")['side'], 'NONE')

    def test_exit_super_order_is_noop_when_no_active_position(self):
        """No active order -> nothing placed, clear error returned."""
        self.engine._set_state("NIFTY", {'side': 'NONE', 'last_signal': 'NONE'})

        res = self.engine.exit_super_order("NIFTY")

        self.assertFalse(res.get("success"))
        self.mock_broker.place_order.assert_not_called()

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
