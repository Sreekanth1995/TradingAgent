import unittest
from unittest.mock import MagicMock
import logging
import sys
import os

# Add current directory to path
sys.path.append(os.getcwd())

from super_order_engine import SuperOrderEngine

# Configure logging to see output during tests
logging.basicConfig(level=logging.INFO)


class TestSuperOrderModify(unittest.TestCase):
    """
    The old _close_position smart-exit that modified each bracket leg by type
    (broker.modify_super_order(parent, leg, fields)) was removed. The current
    engine exposes modify_super_order(underlying, ...) which routes to the
    broker's per-leg methods. These tests pin that routing.
    """

    def setUp(self):
        self.broker = MagicMock()
        self.engine = SuperOrderEngine(self.broker)
        self.engine.use_redis = False
        self.engine.memory_store = {}

    def test_modify_super_order_routes_to_correct_broker_legs(self):
        self.engine._set_state("NIFTY", {
            'side': 'CALL', 'symbol': 'NIFTY_25800_CE', 'security_id': '42536',
            'entry_id': 'so_parent_999', 'sl_price': 80.0, 'quantity': 75,
        })

        res = self.engine.modify_super_order(
            "NIFTY", stop_loss_price=95.0, target_price=105.0, trailing_jump=5.0,
        )
        self.assertTrue(res.get("success"))

        # SL leg modified with the parent order id + new SL + trailing.
        self.broker.modify_super_sl_leg.assert_called_once()
        sl_args = self.broker.modify_super_sl_leg.call_args.args
        self.assertEqual(sl_args[0], 'so_parent_999')
        self.assertEqual(sl_args[1], 95.0)
        self.assertEqual(sl_args[2], 5.0)

        # Target leg modified with the parent order id + new target.
        self.broker.modify_super_target_leg.assert_called_once_with('so_parent_999', 105.0)

    def test_modify_super_order_only_target_does_not_touch_sl_leg(self):
        self.engine._set_state("NIFTY", {
            'side': 'CALL', 'symbol': 'NIFTY_25800_CE', 'security_id': '42536',
            'entry_id': 'so_parent_999', 'quantity': 75,
        })

        self.engine.modify_super_order("NIFTY", target_price=120.0)

        self.broker.modify_super_target_leg.assert_called_once_with('so_parent_999', 120.0)
        self.broker.modify_super_sl_leg.assert_not_called()

    def test_modify_super_order_errors_without_active_order(self):
        self.engine._set_state("NIFTY", {'side': 'NONE', 'last_signal': 'NONE'})

        res = self.engine.modify_super_order("NIFTY", target_price=105.0)

        self.assertFalse(res.get("success"))
        self.broker.modify_super_target_leg.assert_not_called()
        self.broker.modify_super_sl_leg.assert_not_called()


if __name__ == '__main__':
    unittest.main()
