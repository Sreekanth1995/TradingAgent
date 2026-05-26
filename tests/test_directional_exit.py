import logging
import unittest
from unittest.mock import MagicMock

from super_order_engine import SuperOrderEngine

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')


class TestOppositeSignalExit(unittest.TestCase):
    """
    The old directional LONG_EXIT/SHORT_EXIT signals (which modified opposite
    super-order legs) were removed. In the streamlined engine, an OPPOSITE B/S
    signal exits the current position via exit_super_order; a SAME-side signal is
    a no-op while a position is open. These tests pin that behavior.
    """

    def setUp(self):
        self.broker = MagicMock()
        self.engine = SuperOrderEngine(self.broker)
        self.engine.use_redis = False
        self.engine.memory_store = {}

    def test_opposite_signal_exits_existing_call(self):
        # Active CALL. A SELL ('S') signal should EXIT it (not open a PUT).
        self.engine._set_state("NIFTY", {
            'side': 'CALL', 'symbol': 'NIFTY_25000_CE', 'security_id': '123',
            'entry_id': 'SO_CE_1', 'quantity': 75,
        })
        self.broker.place_order.return_value = {"success": True, "order_id": "EXIT_1"}

        res = self.engine.process_signal("NIFTY", None, "S")

        self.assertTrue(res.get("success"))
        self.broker.place_order.assert_called_once()
        self.assertEqual(self.broker.place_order.call_args.args[1]['transaction_type'], 'SELL')
        # No new entry placed; position flattened and state cleared.
        self.broker.place_super_order.assert_not_called()
        self.assertEqual(self.engine._get_state("NIFTY")['side'], 'NONE')

    def test_opposite_signal_exits_existing_put(self):
        # Active PUT. A BUY ('B') signal should EXIT it.
        self.engine._set_state("NIFTY", {
            'side': 'PUT', 'symbol': 'NIFTY_25100_PE', 'security_id': '456',
            'entry_id': 'SO_PE_1', 'quantity': 75,
        })
        self.broker.place_order.return_value = {"success": True, "order_id": "EXIT_2"}

        res = self.engine.process_signal("NIFTY", None, "B")

        self.assertTrue(res.get("success"))
        self.broker.place_order.assert_called_once()
        self.broker.place_super_order.assert_not_called()
        self.assertEqual(self.engine._get_state("NIFTY")['side'], 'NONE')

    def test_same_side_signal_is_noop_when_in_position(self):
        # Active CALL. Another BUY ('B') => already in position, no new order.
        self.engine._set_state("NIFTY", {
            'side': 'CALL', 'symbol': 'NIFTY_25000_CE', 'security_id': '123',
            'entry_id': 'SO_CE_1', 'quantity': 75,
        })

        res = self.engine.process_signal("NIFTY", {"symbol": "X", "security_id": "9"}, "B")

        self.assertEqual(res.get("action"), "NONE")
        self.broker.place_super_order.assert_not_called()
        self.broker.place_order.assert_not_called()
        self.assertEqual(self.engine._get_state("NIFTY")['side'], 'CALL')


if __name__ == '__main__':
    unittest.main()
