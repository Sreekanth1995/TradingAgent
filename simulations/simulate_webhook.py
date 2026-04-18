import csv
import requests
import json
import time
import os

# Configuration
URL = "http://localhost:5001/webhook"
CSV_FILE = "test_data.csv"

def simulate_from_csv():
    if not os.path.exists(CSV_FILE):
        print(f"Error: {CSV_FILE} not found!")
        return

    print(f"Reading alerts from {CSV_FILE}...")
    
    with open(CSV_FILE, mode='r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        
        alerts_sent = 0
        for row in reader:
            payload_str = row.get('Description', '').strip()
            
            if not payload_str:
                continue
                
            try:
                payload = json.loads(payload_str)
                print(f"\n--- Sending Alert ID: {row.get('Alert ID')} ---")
                
                response = requests.post(URL, json=payload)
                
                if response.status_code == 200:
                    print(f"SUCCESS: {json.dumps(response.json(), indent=2)}")
                else:
                    print(f"FAILED (Status {response.status_code}): {response.text}")
                
                alerts_sent += 1
                time.sleep(1) # Slow down for visibility
                
            except json.JSONDecodeError:
                continue
            except Exception as e:
                print(f"Error: {e}")
                continue

    print(f"\nSimulation complete. Sent {alerts_sent} alerts.")

if __name__ == "__main__":
    simulate_from_csv()

