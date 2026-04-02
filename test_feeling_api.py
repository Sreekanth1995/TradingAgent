import unittest
import json
from unittest.mock import patch, MagicMock

# Simulate persistent state across endpoints for our mock engine
mock_state = {}

class TestFeelingAPI(unittest.TestCase):
    @patch('server.DhanClient')
    @patch('server.RankingEngine')
    def setUp(self, mock_engine, mock_dhan):
        # Reset state before each test
        global mock_state
        mock_state = {}
        
        # Mock components
        mock_dhan.return_value = MagicMock()
        self.mock_engine_instance = MagicMock()
        self.mock_engine_instance.process_signal.return_value = {"action": "MOCKED_SUCCESS"}
        
        # Mock state behavior
        def mock_get_state(symbol):
            return mock_state.get(symbol, {"side": "NONE", "last_signal": "NONE"})
        def mock_set_state(symbol, state):
            mock_state[symbol] = state

        self.mock_engine_instance._get_state.side_effect = mock_get_state
        self.mock_engine_instance._set_state.side_effect = mock_set_state
        
        mock_engine.return_value = self.mock_engine_instance
        
        import os
        os.environ['WEBHOOK_SECRET'] = '60pgS'
        
        from server import app
        app.config['TESTING'] = True
        
        import server
        server.engine = self.mock_engine_instance
        server.broker = MagicMock()
        server.SECRET = '60pgS'

        self.client = app.test_client()

    def set_feeling(self, symbol, feeling):
        payload = {
            "secret": "60pgS",
            "timeframe": "5",
            "order_legs": [
                {
                    "symbol": symbol,
                    "feeling": feeling,
                    "current_price": 20000
                }
            ]
        }
        res = self.client.post('/feeling', json=payload)
        self.assertEqual(res.status_code, 200)

    def test_feeling_buy_accepts_b(self):
        self.set_feeling("NIFTY", "BUY")
        payload = {
            "secret": "60pgS",
            "timeframe": "5",
            "order_legs": [{"symbol": "NIFTY", "transactionType": "B", "current_price": 20000}]
        }
        res = self.client.post('/webhook', json=payload)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()["actions"][0]["action"], "MOCKED_SUCCESS")

    def test_feeling_buy_ignores_s(self):
        self.set_feeling("NIFTY", "BUY")
        payload = {
            "secret": "60pgS",
            "timeframe": "5",
            "order_legs": [{"symbol": "NIFTY", "transactionType": "S", "current_price": 20000}]
        }
        res = self.client.post('/webhook', json=payload)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()["actions"][0]["action"], "IGNORED_DUE_TO_FEELING")

    def test_feeling_sell_accepts_s(self):
        self.set_feeling("NIFTY", "SELL")
        payload = {
            "secret": "60pgS",
            "timeframe": "5",
            "order_legs": [{"symbol": "NIFTY", "transactionType": "S", "current_price": 20000}]
        }
        res = self.client.post('/webhook', json=payload)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()["actions"][0]["action"], "MOCKED_SUCCESS")

    def test_feeling_sell_ignores_b(self):
        self.set_feeling("NIFTY", "SELL")
        payload = {
            "secret": "60pgS",
            "timeframe": "5",
            "order_legs": [{"symbol": "NIFTY", "transactionType": "B", "current_price": 20000}]
        }
        res = self.client.post('/webhook', json=payload)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()["actions"][0]["action"], "IGNORED_DUE_TO_FEELING")

    def test_no_feeling_processed_normally(self):
        payload = {
            "secret": "60pgS",
            "timeframe": "5",
            "order_legs": [{"symbol": "NIFTY", "transactionType": "B", "current_price": 20000}]
        }
        res = self.client.post('/webhook', json=payload)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()["actions"][0]["action"], "MOCKED_SUCCESS")

if __name__ == '__main__':
    unittest.main()
