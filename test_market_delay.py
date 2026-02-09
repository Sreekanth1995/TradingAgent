import unittest
from unittest.mock import MagicMock, patch
from datetime import datetime
import pytz
from ranking_engine import RankingEngine

IST = pytz.timezone('Asia/Kolkata')

class TestMarketDelay(unittest.TestCase):
    def setUp(self):
        self.broker = MagicMock()
        self.engine = RankingEngine(self.broker)
        # Disable Redis for tests
        self.engine.use_redis = False
        self.engine.memory_store = {}

    @patch('ranking_engine.datetime')
    def test_market_delay_active(self, mock_datetime):
        # 09:20 AM IST - Should be ignored
        mock_now = datetime(2026, 2, 6, 9, 20, 0, tzinfo=IST)
        mock_datetime.now.return_value = mock_now
        mock_datetime.side_effect = lambda *args, **kw: datetime(*args, **kw)

        leg_data = {"current_price": 25000}
        result = self.engine.process_signal("NIFTY", "B", 1, leg_data)
        
        self.assertEqual(result["action"], "SKIPPED_MARKET_OPEN_DELAY")
        self.broker.get_itm_contract.assert_not_called()

    @patch('ranking_engine.datetime')
    def test_market_delay_passed(self, mock_datetime):
        # 09:26 AM IST - Should be processed
        mock_now = datetime(2026, 2, 6, 9, 26, 0, tzinfo=IST)
        mock_datetime.now.return_value = mock_now
        mock_datetime.side_effect = lambda *args, **kw: datetime(*args, **kw)

        # Mock broker methods to avoid actual calls
        self.broker.get_itm_contract.return_value = {
            "symbol": "NIFTY_25000_CE",
            "security_id": "12345",
            "strike": 25000,
            "expiry": "2026-02-12"
        }
        self.broker.get_ltp.return_value = 100.0
        self.broker.place_super_order.return_value = {"success": True, "order_id": "SO_123"}

        leg_data = {"current_price": 25000, "quantity": 1}
        result = self.engine.process_signal("NIFTY", "B", 1, leg_data)
        
        self.assertEqual(result["action"], "OPENED_CALL")
        self.broker.get_itm_contract.assert_called()

    @patch('ranking_engine.datetime')
    def test_pre_market_hours(self, mock_datetime):
        # 09:10 AM IST - Should be processed by the engine? 
        # Actually our logic says: if market_start <= now < delay_end: skip.
        # 09:10 is NOT in that range. So it would be PROCESSED by this logic.
        # However, it's usually outside market hours anyway.
        mock_now = datetime(2026, 2, 6, 9, 10, 0, tzinfo=IST)
        mock_datetime.now.return_value = mock_now
        mock_datetime.side_effect = lambda *args, **kw: datetime(*args, **kw)

        self.broker.get_itm_contract.return_value = {
            "symbol": "NIFTY_25000_CE",
            "security_id": "12345",
            "strike": 25000,
            "expiry": "2026-02-12"
        }
        self.broker.get_ltp.return_value = 100.0
        self.broker.place_super_order.return_value = {"success": True, "order_id": "SO_123"}

        leg_data = {"current_price": 25000, "quantity": 1}
        result = self.engine.process_signal("NIFTY", "B", 1, leg_data)
        
        self.assertEqual(result["action"], "OPENED_CALL")

if __name__ == '__main__':
    unittest.main()
