import csv
import requests
import json
import time
import os
from datetime import datetime

# Configuration
BASE_URL = "http://localhost:5001"
CSV_FILE = "test_data.csv"
TODAY = "2026-02-18"


def simulate_today():
    if not os.path.exists(CSV_FILE):
        print(f"Error: {CSV_FILE} not found!")
        return

    print(f"Reading alerts for {TODAY} from {CSV_FILE}...")
    
    today_alerts = []
    with open(CSV_FILE, mode='r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            timestamp = row.get('Time', '')
            if timestamp.startswith(TODAY):
                today_alerts.append(row)
    
    # Send in chronological order (CSV is usually latest first)
    today_alerts.reverse()
    
    print(f"Found {len(today_alerts)} alerts for today. Starting simulation...")
    
    alerts_sent = 0
    for row in today_alerts:
        payload_str = row.get('Description', '').strip()
        if not payload_str:
            continue
            
        try:
            payload = json.loads(payload_str)
            timestamp = row.get('Time')
            ticker = row.get('Ticker')
            name = row.get('Name')
            
            # Routing Logic
            if name == "Daily Volume":
                endpoint = f"{BASE_URL}/volume-alert"
            else:
                endpoint = f"{BASE_URL}/webhook"
            
            print(f"\n--- Sending Alert: {name} ({ticker}) at {timestamp} to {endpoint} ---")
            
            response = requests.post(endpoint, json=payload)
            
            if response.status_code == 200:
                print(f"SUCCESS: {json.dumps(response.json(), indent=2)}")
            else:
                print(f"FAILED (Status {response.status_code}): {response.text}")

            
            alerts_sent += 1
            # Very short sleep to allow server to process but finish quickly
            time.sleep(0.1) 
            
        except json.JSONDecodeError:
            continue
        except Exception as e:
            print(f"Error: {e}")
            continue

    print(f"\nSimulation complete. Sent {alerts_sent} alerts.")

if __name__ == "__main__":
    simulate_today()
