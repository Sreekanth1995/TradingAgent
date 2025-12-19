import os
import re
import logging
from flask import Flask, request, jsonify
from dotenv import load_dotenv
from ranking_engine import RankingEngine
from broker_dhan import DhanClient

# Load Environment Variables
load_dotenv()

# Configuration
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
SECRET = os.getenv("WEBHOOK_SECRET", "60pgS") # Default from user example

# Logging Setup
logging.basicConfig(level=getattr(logging, LOG_LEVEL), format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Initialize Components
try:
    broker = DhanClient()
    engine = RankingEngine(broker)
    logger.info("System Initialized Successfully")
except Exception as e:
    logger.error(f"Initialization Failed: {e}")
    raise e

@app.route('/webhook', methods=['POST'])
def webhook():
    """
    Endpoint to receive TradingView Alerts.
    Expected Payload:
    {
      "secret": "60pgS",
      "alertType": "multi_leg_order",
      "timeframe": 1,
      "order_legs": [...]
    }
    """
    try:
        # Force JSON parsing even if Content-Type header is missing
        data = request.get_json(force=True, silent=True)
        logger.info(f"DEBUG - Received Payload: {data}")
        
        if not data:
            return jsonify({"status": "error", "message": "Invalid or missing JSON payload"}), 400
        
        # 1. Security Check
        if data.get('secret') != SECRET:
            logger.warning("Unauthorized Webhook Attempt")
            return jsonify({"status": "error", "message": "Unauthorized"}), 401
            
        # 2. Extract Key Fields
        timeframe = data.get('timeframe')
        if not timeframe:
             return jsonify({"status": "error", "message": "Missing timeframe"}), 400

        legs = data.get('order_legs', [])
        if not legs:
             return jsonify({"status": "error", "message": "No order legs found"}), 400
             
        # Process each leg (Usually 1 for simple alerts, but handling list for robustness)
        results = []
        for leg in legs:
            # 2.1 Parse Ticker if available (Override explicit fields)
            ticker = leg.get('ticker')
            if ticker:
                # Format: NIFTY251223C25850 (Symbol + YYMMDD + Type + Strike)
                # Regex to handle variable length symbol and strike
                # Looking for: String chars + 6 digits (Date) + 1 char (C/P) + Digits (Strike)
                match = re.match(r'^([A-Z]+)(\d{2})(\d{2})(\d{2})([CP])(\d+(\.\d+)?)$', ticker)
                if match:
                    groups = match.groups()
                    leg['symbol'] = groups[0]
                    # Expiry: YYMMDD -> YYYY-MM-DD
                    leg['expiry_date'] = f"20{groups[1]}-{groups[2]}-{groups[3]}"
                    # Option Type: C -> CE, P -> PE
                    leg['option_type'] = "CE" if groups[4] == "C" else "PE"
                    leg['strike_price'] = groups[5] # Keep as string or convert if needed
                    
                    logger.info(f"Parsed Ticker {ticker} -> {leg['symbol']} {leg['strike_price']} {leg['option_type']} Exp:{leg['expiry_date']}")
                else:
                    logger.warning(f"Could not parse ticker: {ticker}. Using existing fields.")

            symbol = leg.get('symbol')
            if not symbol:
                 logger.error(f"Missing Symbol for leg: {leg}")
                 continue
            # Construct a unique ticker for the option contract
            # E.g., NIFTY 26000 CE 2025-10-28
            # For now, we will use a simplified unique key based on what's available
            # Or just use the raw symbol if it's unique enough for the user's charts
            instrument_key = f"{symbol}_{leg.get('strike_price')}_{leg.get('option_type')}"
            
            transaction_type = leg.get('transactionType') # B or S
            
            logger.info(f"Received Signal: {transaction_type} for {instrument_key} on {timeframe}m timeframe")
            
            # 3. Process with Ranking Engine
            action = engine.process_signal(instrument_key, transaction_type, int(timeframe), leg)
            results.append(action)

        return jsonify({"status": "success", "actions": results}), 200

    except Exception as e:
        logger.error(f"Webhook Processing Error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == '__main__':
    port = int(os.getenv("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
