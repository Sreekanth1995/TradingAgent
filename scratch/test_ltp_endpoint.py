import requests
import json
import os
from dotenv import load_dotenv

load_dotenv()

SECRET = os.getenv("WEBHOOK_SECRET", "60pgS")
BASE_URL = "http://localhost:5001" # Default flask port

def test_get_ltp(instrument):
    print(f"\n--- Testing LTP for {instrument} ---")
    payload = {
        "secret": SECRET,
        "instrument": instrument
    }
    try:
        resp = requests.post(f"{BASE_URL}/get-ltp", json=payload)
        print(f"Status: {resp.status_code}")
        print(f"Response: {json.dumps(resp.json(), indent=2)}")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    # Note: Ensure server.py is running on port 5001 (or update BASE_URL)
    test_get_ltp("NIFTY")
    test_get_ltp("BANKNIFTY")
    test_get_ltp("1333") # Mock ID
