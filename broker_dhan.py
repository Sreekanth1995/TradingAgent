import logging
import os
import csv
import requests
from datetime import datetime

from dhanhq import dhanhq

# Define constants locally as they are missing in dhanhq 2.0.2
class ExchangeSegment:
    NSE_FNO = "NSE_FNO"
    NSE_EQ = "NSE_EQ"
    BSE_EQ = "BSE_EQ"

class TransactionType:
    BUY = "BUY"
    SELL = "SELL"

class OrderType:
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP_LOSS = "STOP_LOSS"
    STOP_LOSS_MARKET = "STOP_LOSS_MARKET"

class ProductType:
    INTRADAY = "INTRADAY"
    CNC = "CNC"
    MARGIN = "MARGIN"
    CO = "CO"
    BO = "BO"

class Validity:
    DAY = "DAY"
    IOC = "IOC"

DHAN_AVAILABLE = True

logger = logging.getLogger(__name__)

class DhanClient:
    def __init__(self):
        self.client_id = os.getenv("DHAN_CLIENT_ID")
        self.access_token = os.getenv("DHAN_ACCESS_TOKEN")
        
        # Redis for Token Persistence
        self.r = None
        redis_host = os.getenv("REDIS_HOST", "localhost")
        redis_port = int(os.getenv("REDIS_PORT", 6379))
        try:
            import redis
            self.r = redis.Redis(host=redis_host, port=redis_port, decode_responses=True)
            cached_token = self.r.get("dhan_access_token")
            if cached_token:
                self.access_token = cached_token
                logger.info("Access Token loaded from Redis.")
        except Exception as e:
            logger.warning(f"Redis not available for Token Persistence: {e}")

        self.dry_run = os.getenv("DRY_RUN", "false").lower() == "true"
        self.dhan = None
        self.scrip_map = {} # (symbol, strike, opt_type, expiry_date) -> security_id
        self.lot_map = {}   # security_id -> lot_size (int)

        
        # Load Scrip Master
        try:
            self._load_scrip_master()
        except Exception as e:
            logger.error(f"Failed to load Scrip Master: {e}")

        if self.client_id and self.access_token and DHAN_AVAILABLE:
            if self.dry_run:
                logger.info("!!!! DRY RUN MODE ENABLED !!!! - No real orders will be placed, state will update normally.")
            else:
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
                        sym = row.get('SM_SYMBOL_NAME', '').strip()
                        if not sym:
                             # Fallback for Options where SM_SYMBOL_NAME is often empty
                             # e.g., BANKNIFTY-Dec2025-69700-CE -> BANKNIFTY
                             sym = row.get('SEM_TRADING_SYMBOL', '').split('-')[0]
                        
                        sym = sym.strip()
                        strike = float(row.get('SEM_STRIKE_PRICE', 0)) # 26000.00
                        opt_type = row.get('SEM_OPTION_TYPE') # CE
                        
                        # Handle Expiry Date Format: "2024-08-28 14:30:00" -> "2024-08-28"
                        expiry_raw = row.get('SEM_EXPIRY_DATE', '').split(" ")[0]
                        
                        key = (sym, strike, opt_type, expiry_raw)
                        sec_id = row.get('SEM_SMST_SECURITY_ID')
                        self.scrip_map[key] = sec_id
                        
                        # Store lot size
                        try:
                            self.lot_map[sec_id] = int(float(row.get('SEM_LOT_UNITS', 1)))
                        except:
                            self.lot_map[sec_id] = 1
                            
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
            base_symbol = leg_data.get('symbol', symbol)
            strike = leg_data.get('strike_price')
            opt_type = leg_data.get('option_type')
            expiry = leg_data.get('expiry_date')
            sec_id = self._get_security_id(base_symbol, strike, opt_type, expiry)
            
            # 2. Convert Lots to actual Quantity
            lots = int(leg_data.get('quantity', 1))
            lot_size = self.lot_map.get(sec_id, 1)
            final_qty = lots * lot_size
            
            logger.info(f"$$$ [BROKER] PLACING {transaction_type} ORDER: {lots} Lots ({final_qty} units) x {symbol} (ID: {sec_id}, LotSize: {lot_size}) $$$")

            if self.dhan and not self.dry_run:
                # Real API Call
                resp = self.dhan.place_order(
                    security_id=sec_id,
                    exchange_segment=ExchangeSegment.NSE_FNO,
                    transaction_type=transaction_type,
                    quantity=final_qty,
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

    def refresh_client(self, new_token):
        """
        Updates the access token and re-initializes the Dhan client.
        """
        self.access_token = new_token
        # Persist to Redis if available
        if self.r:
            try:
                self.r.set("dhan_access_token", new_token)
                logger.info("New Access Token persisted to Redis.")
            except Exception as e:
                logger.error(f"Failed to persist token to Redis: {e}")

        # Re-initialize
        if self.client_id and self.access_token and DHAN_AVAILABLE:
            if not self.dry_run:
                self.dhan = dhanhq(self.client_id, self.access_token)
                logger.info("Dhan Client Re-initialized with new token.")
            return True
        return False
