import logging
import os
import csv
import requests
from datetime import datetime

try:
    from dhanhq import dhanhq
    from dhanhq.constants import ExchangeSegment, TransactionType, OrderType, ProductType, Validity
    DHAN_AVAILABLE = True
except ImportError:
    DHAN_AVAILABLE = False
    # Define dummy constants if library is missing to prevent NameError in code
    class ExchangeSegment: NSE_FNO = "NSE_FNO"
    class TransactionType: BUY = "BUY"; SELL = "SELL"
    class OrderType: MARKET = "MARKET"
    class ProductType: INTRADAY = "INTRADAY"
    class Validity: DAY = "DAY"

logger = logging.getLogger(__name__)

class DhanClient:
    def __init__(self):
        self.client_id = os.getenv("DHAN_CLIENT_ID")
        self.access_token = os.getenv("DHAN_ACCESS_TOKEN")
        self.dhan = None
        self.scrip_map = {} # (symbol, strike, opt_type, expiry_date) -> security_id
        
        # Load Scrip Master
        try:
            self._load_scrip_master()
        except Exception as e:
            logger.error(f"Failed to load Scrip Master: {e}")

        if self.client_id and self.access_token and DHAN_AVAILABLE:
            logger.info("Dhan Credentials found. Connected to DhanHQ.")
            self.dhan = dhanhq(self.client_id, self.access_token)
        elif not DHAN_AVAILABLE:
            logger.warning("dhanhq library not found. Install with `pip install dhanhq`.")
        else:
            logger.warning("No Dhan credentials found. Running in SIMULATION mode.")

    def _load_scrip_master(self):
        """
        Downloads and parses the Dhan Scrip Master CSV.
        """
        csv_file = "dhan_scrip_master.csv"
        url = "https://images.dhan.co/api-data/api-scrip-master.csv"
        
        # Download if not exists or old (simplification: always download on startup or check existence)
        if not os.path.exists(csv_file):
            logger.info(f"Downloading Scrip Master from {url}...")
            try:
                r = requests.get(url, stream=True)
                if r.status_code == 200:
                    with open(csv_file, 'wb') as f:
                        for chunk in r.iter_content(chunk_size=1024):
                            f.write(chunk)
                    logger.info("Download Complete.")
                else:
                    logger.error(f"Failed to download Scrip Master. Status: {r.status_code}")
                    return
            except Exception as e:
                logger.error(f"Download Error: {e}")
                return

        # Parse CSV
        logger.info("Parsing Scrip Master...")
        count = 0
        try:
            with open(csv_file, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    # Filter for NSE Options
                    if row['SEM_EXM_EXCH_ID'] == 'NSE' and row['SEM_INSTRUMENT_NAME'] in ['OPTIDX', 'OPTSTK', 'FUTIDX', 'FUTSTK']:
                        # Extract Key Fields
                        sym = row['SM_SYMBOL_NAME'] # NIFTY
                        strike = float(row.get('SEM_STRIKE_PRICE', 0)) # 26000.00
                        opt_type = row.get('SEM_OPTION_TYPE') # CE
                        
                        # Handle Expiry Date Format: "2024-08-28 14:30:00" -> "2024-08-28"
                        expiry_raw = row.get('SEM_EXPIRY_DATE', '').split(" ")[0]
                        
                        key = (sym, strike, opt_type, expiry_raw)
                        self.scrip_map[key] = row['SEM_SMST_SECURITY_ID']
                        count += 1
            logger.info(f"Loaded {count} instruments into Scrip Map.")
        except Exception as e:
            logger.error(f"Error parsing CSV: {e}")

    def _get_security_id(self, symbol, strike, opt_type, expiry):
        """
        Look up Security ID from the loaded map.
        key = (Symbol, Strike(float), OptionType, Expiry(YYYY-MM-DD))
        """
        # Normalize inputs
        try:
             s_price = float(strike)
        except:
             s_price = 0.0
             
        # Normalize expiry (User sends '2025-10-28', map has '2025-10-28')
        # Ensure exact string match
        
        key = (symbol, s_price, opt_type, expiry)
        sec_id = self.scrip_map.get(key)
        
        if sec_id:
            return sec_id
        else:
            # Fallback debug log to help user see what keys exist
            # logger.debug(f"Missing Key: {key}")
            logger.warning(f"Security ID NOT FOUND for {key}. Using Dummy 1333.")
            return "1333"

    def place_buy_order(self, symbol, leg_data):
        return self._place_order(symbol, leg_data, TransactionType.BUY)

    def place_sell_order(self, symbol, leg_data):
        return self._place_order(symbol, leg_data, TransactionType.SELL)

    def _place_order(self, symbol, leg_data, transaction_type):
        """
        Internal method to execute order via Dhan API
        """
        try:
            qty = int(leg_data.get('quantity', 1))
            
            # 1. Resolve Security ID
            strike = leg_data.get('strike_price')
            opt_type = leg_data.get('option_type')
            expiry = leg_data.get('expiry_date')
            sec_id = self._get_security_id(symbol, strike, opt_type, expiry)

            logger.info(f"$$$ [BROKER] PLACING {transaction_type} ORDER: {qty} x {symbol} (ID: {sec_id}) $$$")

            if self.dhan:
                # Real API Call
                resp = self.dhan.place_order(
                    security_id=sec_id,
                    exchange_segment=ExchangeSegment.NSE_FNO,
                    transaction_type=transaction_type,
                    quantity=qty,
                    order_type=OrderType.MARKET,
                    product_type=ProductType.INTRADAY, # Assuming Intraday based on user flow
                    price=0,
                    validity=Validity.DAY
                )
                
                if resp.get('status') == 'success':
                     return {"success": True, "order_id": resp.get('data', {}).get('orderId'), "error": None}
                else:
                     return {"success": False, "order_id": None, "error": resp.get('remarks', 'Unknown Error')}
            else:
                # Mock Mode
                return {"success": True, "order_id": "mock_id_999", "error": None}

        except Exception as e:
            logger.error(f"Order Placement FAILED: {e}")
            return {"success": False, "order_id": None, "error": str(e)}
