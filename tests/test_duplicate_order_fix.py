import unittest
from unittest.mock import MagicMock, patch
import sys
import os

# Add current directory to path
sys.path.append(os.getcwd())

from super_order_engine import SuperOrderEngine

class TestDuplicateOrderFix(unittest.TestCase):
    def setUp(self):
        self.mock_broker = MagicMock()
        self.engine = SuperOrderEngine(self.mock_broker)
        
    def test_duplicate_order_modification_with_different_strike(self):
        """
        Scenario: A SELL signal arrives (PE). A PE Super Order is already active but has a different strike.
        Expected: The system should identify the existing PE super order (via tradingSymbol) and MODIFY it instead of PLACING a NEW one.
        """
        underlying = "NIFTY"
        signal_type = "S" # SELL -> PE
        timeframe = 5
        leg_data = {'current_price': 25000} # ITM PE strike will be 25050
        
        # 1. Mock ITM Resolution
        # Current Signal ITM Strike: 25050
        itm_ce = {'security_id': '100', 'symbol': 'NIFTY_24950_CE'}
        itm_pe = {'security_id': '200', 'symbol': 'NIFTY_25050_PE'}
        
        # We need itm_ce and itm_pe for the engine's _execute_signal logic
        def get_itm_contract_mock(und, side, spot):
            if side == 'CE': return itm_ce
            if side == 'PE': return itm_pe
            return None
            
        self.mock_broker.get_itm_contract.side_effect = get_itm_contract_mock
        self.mock_broker.get_ltp.return_value = 100.0 # Option LTP
        
        # 2. Mock Existing Super Orders
        # An existing PE order with a DIFFERENT strike (e.g., 25150)
        existing_pe_order = {
            'orderId': 'oid_existing_pe',
            'legName': 'TARGET_LEG',
            'orderType': 'LIMIT',
            'transactionType': 'SELL',
            'securityId': '300', # Different from 200
            'tradingSymbol': 'NIFTY_25150_PE'
        }
        self.mock_broker.get_super_orders.return_value = [existing_pe_order]
        
        # 3. Process signal
        result = self.engine.process_signal(underlying, signal_type, timeframe, leg_data)
        
        # 4. Verifications
        # Ensure NO new order was placed
        self.mock_broker.place_super_order.assert_not_called()
        
        # Ensure existing order was modified
        self.mock_broker.modify_super_target_leg.assert_called_with('oid_existing_pe', 175.0) # 100 * 1.75
        self.mock_broker.modify_super_sl_leg.assert_called_with('oid_existing_pe', 80.0)    # 100 * 0.80
        
        print("\n✅ Verification Successful: Existing PE order identified via symbol and modified.")

if __name__ == '__main__':
    unittest.main()
