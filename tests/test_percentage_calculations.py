import unittest
from unittest.mock import MagicMock
import sys
import os

# Add current directory to path
sys.path.append(os.getcwd())

from super_order_engine import SuperOrderEngine


class TestPercentageCalculations(unittest.TestCase):
    """
    The percentage -> absolute-price conversion that used to live in the old
    _open_position now lives inline in SuperOrderEngine.process_signal (calc_abs).
    These tests pin that math against the current streamlined engine.
    """

    def setUp(self):
        self.broker = MagicMock()
        self.engine = SuperOrderEngine(self.broker)
        self.engine.use_redis = False
        self.engine.memory_store = {}

    def test_process_signal_converts_percentages_to_absolute_prices(self):
        # Server resolves the ITM and passes it in; option LTP = 100.
        self.broker.get_ltp.return_value = 100.0
        self.broker.place_super_order.return_value = {"success": True, "order_id": "SO_123"}
        itm = {"symbol": "NIFTY_25000_CE", "security_id": "42536"}

        # Target 50%, SL 20%, Trailing 15% (all < 50 -> percent of option LTP).
        res = self.engine.process_signal(
            "NIFTY", itm, "B",
            leg_data={"target": 50, "sl": 20, "trailing": 15, "quantity": 1},
        )
        self.assertTrue(res.get("success"))

        leg = self.broker.place_super_order.call_args.args[1]
        self.assertEqual(leg["target_price"], 150.0)     # 100 + 50%
        self.assertEqual(leg["stop_loss_price"], 80.0)   # 100 - 20%
        self.assertEqual(leg["trailing_jump"], 15.0)     # 100 * 15%

    def test_process_signal_uses_engine_defaults_when_unspecified(self):
        self.broker.get_ltp.return_value = 200.0
        self.broker.place_super_order.return_value = {"success": True, "order_id": "SO_9"}
        itm = {"symbol": "NIFTY_25000_CE", "security_id": "42536"}

        self.engine.process_signal("NIFTY", itm, "B", leg_data={"quantity": 1})

        leg = self.broker.place_super_order.call_args.args[1]
        # configs DEFAULT: target 55, sl 20, trailing 20
        self.assertEqual(leg["target_price"], 310.0)     # 200 + 55%
        self.assertEqual(leg["stop_loss_price"], 160.0)  # 200 - 20%
        self.assertEqual(leg["trailing_jump"], 40.0)     # 200 * 20%


if __name__ == '__main__':
    unittest.main()
