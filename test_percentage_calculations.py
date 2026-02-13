import unittest
from unittest.mock import MagicMock
import sys
import os

# Add current directory to path
sys.path.append(os.getcwd())

from ranking_engine import RankingEngine

class TestPercentageCalculations(unittest.TestCase):
    def setUp(self):
        self.mock_broker = MagicMock()
        self.engine = RankingEngine(self.mock_broker)
        
    def test_open_position_percentage_math(self):
        """
        Verify that _open_position calculates levels correctly using percentages.
        Using NIFTY: Target 50%, SL 20%, Trailing 10%
        """
        underlying = "NIFTY"
        side = "CALL"
        leg_data = {"current_price": 25000} # Index spot
        
        # Mock ITM and LTP
        self.mock_broker.get_itm_contract.return_value = {
            "symbol": "NIFTY_25000_CE",
            "security_id": "42536"
        }
        self.mock_broker.get_ltp.return_value = 100.0 # Option price
        
        # Mock Super Order Response
        self.mock_broker.place_super_order.return_value = {"success": True, "order_id": "SO_123"}
        
        # Run _open_position
        res = self.engine._open_position(underlying, side, leg_data)
        
        # Verify the parameters passed to place_super_order
        args, kwargs = self.mock_broker.place_super_order.call_args
        so_leg = args[1]
        
        # 100 + 50% = 150
        self.assertEqual(so_leg['target_price'], 150.0)
        # 100 - 20% = 80
        self.assertEqual(so_leg['stop_loss_price'], 80.0)
        # 100 * 15% = 15
        self.assertEqual(so_leg['trailing_jump'], 15.0)

    def test_trailing_sl_percentage_math(self):
        """
        Verify that _close_position calculates trailing offset correctly during Smart Exit.
        """
        underlying = "NIFTY"
        state = {
            "symbol": "NIFTY_25000_CE",
            "security_id": "42536",
            "entry_id": "SO_123",
            "is_super_order": True,
            "side": "CALL"
        }
        
        self.mock_broker.get_ltp.return_value = 120.0 # Current Option Price
        # Mock one pending SL order
        self.mock_broker.get_pending_orders.return_value = [{
            "orderId": "SO_123_SL",
            "orderType": "STOP_LOSS_MARKET",
            "transactionType": "SELL",
            "triggerPrice": 80.0
        }]
        
        self.engine.trailing_sl_enabled = True
        self.mock_broker.modify_super_order.return_value = {"success": True}
        
        # Run _close_position (calls trailing logic)
        self.engine._close_position(underlying, state)
        
        # Calculation:
        # LTP = 120
        # Trail % = 15%
        # Offset = 120 * 0.15 = 18.0
        # Barrier = 120 - 18.0 = 102.0
        
        self.mock_broker.modify_super_order.assert_called_once()
        args, kwargs = self.mock_broker.modify_super_order.call_args
        # args[2] is fields
        self.assertEqual(args[2]['stop_loss_price'], 102.0)

if __name__ == '__main__':
    unittest.main()
