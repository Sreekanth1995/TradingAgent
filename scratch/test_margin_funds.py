import requests
import json
import os
from dotenv import load_dotenv

load_dotenv()

SECRET = os.getenv("WEBHOOK_SECRET", "60pgS")
BASE_URL = "http://localhost:5001"

def test_fund_limit():
    print("\n--- Testing Fund Limit ---")
    payload = {"secret": SECRET}
    resp = requests.post(f"{BASE_URL}/fundlimit", json=payload)
    print(f"Status: {resp.status_code}")
    print(f"Response: {json.dumps(resp.json(), indent=2)}")

def test_margin_calc():
    print("\n--- Testing Margin Calculator (Single) ---")
    payload = {
        "secret": SECRET,
        "security_id": "13",
        "exchange_segment": "NSE_FNO",
        "transaction_type": "BUY",
        "quantity": 1,
        "price": 0.0,
        "product_type": "INTRADAY"
    }
    resp = requests.post(f"{BASE_URL}/margincalculator", json=payload)
    print(f"Status: {resp.status_code}")
    print(f"Response: {json.dumps(resp.json(), indent=2)}")

def test_margin_calc_multi():
    print("\n--- Testing Margin Calculator (Multi) ---")
    payload = {
        "secret": SECRET,
        "orders": [
            {
                "security_id": "13",
                "exchange_segment": "NSE_FNO",
                "transaction_type": "BUY",
                "quantity": 1,
                "price": 0.0,
                "product_type": "INTRADAY"
            },
            {
                "security_id": "25",
                "exchange_segment": "NSE_FNO",
                "transaction_type": "SELL",
                "quantity": 2,
                "price": 0.0,
                "product_type": "INTRADAY"
            }
        ]
    }
    resp = requests.post(f"{BASE_URL}/margincalculator/multi", json=payload)
    print(f"Status: {resp.status_code}")
    print(f"Response: {json.dumps(resp.json(), indent=2)}")

if __name__ == "__main__":
    # Ensure server is running on 5001 with USE_MOCK_API=true
    test_fund_limit()
    test_margin_calc()
    test_margin_calc_multi()
