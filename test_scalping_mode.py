import unittest
from unittest.mock import MagicMock, patch
import sys
import os
import time
from datetime import datetime
import pytz

# Add current directory to path
sys.path.append(os.getcwd())

from ranking_engine import RankingEngine, IST

class TestScalpingMode(unittest.TestCase):
    def setUp(self):
        self.mock_broker = MagicMock()
        self.engine = RankingEngine(self.mock_broker)
        self.engine.use_redis = False # Test in memory
        
    @patch('ranking_engine.datetime')
    def test_scalping_mode_logic(self, mock_datetime):
        """
        Verify all conditions for Scalping Mode activation and signal processing.
        """
        symbol = "NIFTY"
        leg_data = {"current_price": 25000, "quantity": 50}
        
        # Mock LTP for all calls
        self.mock_broker.get_ltp.return_value = 100.0
        self.mock_broker.get_itm_contract.return_value = {"symbol": "NIFTY_25000_CE", "security_id": "42536"}
        self.mock_broker.place_super_order.return_value = {"success": True, "order_id": "SO_SCALP"}

        # 1. Standard Mode (5m signal) - Should always work during market hours
        # Set time to 10:00 AM IST. Today is NOT expiry day for this test case part.
        mock_datetime.now.return_value = datetime(2026, 2, 13, 10, 0, tzinfo=IST)
        mock_datetime.fromtimestamp = datetime.fromtimestamp 
        self.mock_broker.is_expiry_day.return_value = False
        
        res = self.engine.process_signal(symbol, 'B', 5, leg_data)
        self.assertIn("OPENED_CALL", res.get('actions', []))
        self.engine._clear_state(symbol)
        
        # 2. Scalping Mode (1m signal) - Window Check
        # Set time to 11:00 AM IST (Outside windows)
        mock_datetime.now.return_value = datetime(2026, 2, 13, 11, 0, tzinfo=IST)
        res = self.engine.process_signal(symbol, 'B', 1, leg_data)
        self.assertEqual(res.get('action'), 'SKIPPED_SCALPING_INACTIVE')
        self.engine._clear_state(symbol)
        
        # 3. Scalping Mode (1m signal) - Non-Expiry Day Check
        # Set time to 10:00 AM (Inside window)
        mock_datetime.now.return_value = datetime(2026, 2, 13, 10, 0, tzinfo=IST)
        self.mock_broker.is_expiry_day.return_value = False
        res = self.engine.process_signal(symbol, 'B', 1, leg_data)
        self.assertEqual(res.get('action'), 'SKIPPED_SCALPING_INACTIVE')
        self.engine._clear_state(symbol)
        
        # 4. Scalping Mode (1m signal) - Activation Check (Bypass)
        # Even if it's NOT an expiry day and NOT in window, the Volume Trigger should allow it.
        mock_datetime.now.return_value = datetime(2026, 2, 13, 11, 0, tzinfo=IST)
        self.mock_broker.is_expiry_day.return_value = False
        self.engine.activate_scalping_mode(duration_mins=5)
        
        res = self.engine.process_signal(symbol, 'B', 1, leg_data)
        self.assertIn("OPENED_CALL", res.get('actions', []))
        self.engine._clear_state(symbol)

    def test_mutual_exclusivity(self):
        """Verify that 5m signals are skipped when scalping mode is active."""
        symbol = "NIFTY"
        leg_data = {"current_price": 25000, "quantity": 50}
        
        # 1. Activate Scalping
        self.engine.activate_scalping_mode(duration_mins=5)
        
        # 2. Receive 5m Signal
        res = self.engine.process_signal(symbol, 'B', 5, leg_data)
        
        # 3. Should be skipped
        self.assertEqual(res.get('action'), 'SKIPPED_SCALPING_ACTIVE')
        self.mock_broker.place_super_order.assert_not_called()

    def test_scalping_mode_expiration(self):
        """Verify that scalping mode expires after the duration."""
        self.engine.activate_scalping_mode(duration_mins=1) # 60 seconds
        self.assertTrue(self.engine._is_scalping_active())
        
        # Manually expire it by setting the time in the past
        if self.engine.use_redis:
            self.engine.r.set("scalping_until", int(time.time()) - 10)
        else:
            self.engine.memory_store["scalping_until"] = int(time.time()) - 10
            
        self.assertFalse(self.engine._is_scalping_active())

if __name__ == '__main__':
    unittest.main()
