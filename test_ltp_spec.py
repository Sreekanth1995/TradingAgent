import unittest
from unittest.mock import patch, MagicMock
import os

# Mock environment variables
os.environ["DHAN_CLIENT_ID"] = "1001"
os.environ["DHAN_ACCESS_TOKEN"] = "test_token"

from broker_dhan import DhanClient

class TestLtpSpec(unittest.TestCase):
    def setUp(self):
        self.client = DhanClient()
        # Mock lot_map and other things if needed, but get_ltp is mostly independent
        self.client.dry_run = False

    @patch('requests.post')
    def test_get_ltp_success(self, mock_post):
        # 1. Setup Mock Response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": {
                "NSE_FNO": {
                    "12345": {
                        "last_price": 150.75
                    }
                }
            },
            "status": "success"
        }
        mock_post.return_value = mock_response

        # 2. Call get_ltp
        ltp = self.client.get_ltp("12345", "NSE_FNO")

        # 3. Verify Request
        self.assertEqual(ltp, 150.75)
        
        args, kwargs = mock_post.call_args
        headers = kwargs['headers']
        payload = kwargs['json']

        # Verify Headers
        self.assertEqual(headers['client-id'], "1001")
        # Wait, I set env above, but let's check DhanClient init.
        
        # Verify Payload
        self.assertEqual(payload, {"NSE_FNO": [12345]})

    @patch('requests.post')
    def test_get_ltp_failure(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.text = "Unauthorized"
        mock_post.return_value = mock_response

        ltp = self.client.get_ltp("12345")
        self.assertIsNone(ltp)
    @patch('requests.post')
    def test_place_super_order_spec(self, mock_post):
        # 1. Setup Mock Response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"orderId": "BO_123", "orderStatus": "PENDING"}
        mock_post.return_value = mock_response

        # 2. Call place_super_order with unrounded prices
        leg_data = {
            "security_id": "11536",
            "quantity": 10,
            "order_type": "LIMIT",
            "price": 100.07,         # Unrounded
            "target_price": 130.12,  # Unrounded
            "stop_loss_price": 80.03 # Unrounded
        }
        res = self.client.place_super_order("NIFTY_CE", leg_data)

        # 3. Verify
        self.assertTrue(res['success'])
        
        args, kwargs = mock_post.call_args
        payload = kwargs['json']

        # Verify Rounding (to 0.05 tick size)
        self.assertEqual(payload['price'], 100.05)
        self.assertEqual(payload['targetPrice'], 130.1)
        self.assertEqual(payload['stopLossPrice'], 80.05)
        
        # Verify Mandatory Fields
        self.assertEqual(payload['trailingJump'], 1.0) # Default
        self.assertEqual(payload['validity'], 'DAY')
        self.assertEqual(payload['transactionType'], 'BUY')
        self.assertEqual(payload['securityId'], '11536') # String

if __name__ == '__main__':
    unittest.main()
