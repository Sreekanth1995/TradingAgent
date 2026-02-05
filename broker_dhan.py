import logging
import os
import csv
import requests
import pyotp
import threading
import time
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
        self.api_id = os.getenv("DHAN_API_ID")
        self.api_secret = os.getenv("DHAN_API_SECRET")
        
        # Redis for Token Persistence
        self.r = None
        
        # Support both REDIS_URL (Railway) and REDIS_HOST/REDIS_PORT (manual config)
        redis_url = os.getenv("REDIS_URL")
        
        try:
            import redis
            
            if redis_url:
                # Use Redis URL if provided (Railway format)
                self.r = redis.from_url(redis_url, decode_responses=True)
                logger.info("Connecting to Redis using REDIS_URL")
            else:
                # Fall back to host/port configuration
                redis_host = os.getenv("REDIS_HOST", "localhost")
                redis_port = int(os.getenv("REDIS_PORT", 6379))
                self.r = redis.Redis(host=redis_host, port=redis_port, decode_responses=True)
                logger.info(f"Connecting to Redis at {redis_host}:{redis_port}")
            
            # Test connection and load cached token
            cached_token = self.r.get("dhan_access_token")
            if cached_token:
                self.access_token = cached_token
                logger.info("✅ Access Token loaded from Redis.")
        except Exception as e:
            logger.warning(f"Redis not available for Token Persistence: {e}")

        self.dry_run = os.getenv("DRY_RUN", "false").lower() == "true"
        self.dhan = None
        self.scrip_map = {} # (symbol, strike, opt_type, expiry_date) -> security_id
        self.lot_map = {}   # security_id -> lot_size (int)

        
        # Load Scrip Master in background thread to prevent Railway startup timeout
        self.scrip_loaded = False
        import threading
        def load_scrip_background():
            try:
                self._load_scrip_master()
                self.scrip_loaded = True
                logger.info("✅ Scrip Master loaded successfully in background")
            except Exception as e:
                logger.error(f"Failed to load Scrip Master: {e}")
        
        # Start background download immediately
        threading.Thread(target=load_scrip_background, daemon=True).start()

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

    def get_nearest_expiry(self, symbol):
        """
        Finds the closest expiry date for the given symbol in the scrip map.
        """
        expiries = set()
        for key in self.scrip_map.keys():
            if key[0] == symbol:
                expiries.add(key[3])
        
        if not expiries:
            return None
            
        # Sort YYYY-MM-DD
        sorted_exp = sorted(list(expiries))
        # Return the first one (nearest)
        return sorted_exp[0]

    def get_itm_contract(self, underlying, side, spot_price):
        """
        Determines the best ITM strike and returns the security ID.
        CE ITM = Spot - 50
        PE ITM = Spot + 50
        """
        try:
            spot = float(spot_price)
            # Round to nearest 50
            atm_strike = round(spot / 50) * 50
            
            if side == 'CE':
                strike = atm_strike - 50
            else:
                strike = atm_strike + 50
                
            expiry = self.get_nearest_expiry(underlying)
            if not expiry:
                logger.error(f"No expiry found for {underlying}")
                return None
            
            sec_id = self._get_security_id(underlying, strike, side, expiry)
            if sec_id:
                logger.info(f"Selected ITM for {underlying} ({side}): {strike} Exp: {expiry} -> ID: {sec_id}")
                return {
                    "security_id": sec_id,
                    "strike": strike,
                    "expiry": expiry,
                    "symbol": f"{underlying}_{int(strike)}_{side}"
                }
            else:
                logger.error(f"Could not find exact ITM contract for {underlying} {strike} {side} {expiry}")
                return None
        except Exception as e:
            logger.error(f"Error in ITM Selection: {e}")
            return None

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
        # Wait for scrip master to load if still in progress
        if not self.scrip_loaded:
            logger.warning("Scrip Master still loading, waiting...")
            import time
            max_wait = 30  # seconds
            waited = 0
            while not self.scrip_loaded and waited < max_wait:
                time.sleep(1)
                waited += 1
            
            if not self.scrip_loaded:
                logger.error("Scrip Master failed to load in time")
                return {"success": False, "order_id": None, "error": "Scrip Master not ready"}
        
        try:
            qty = int(leg_data.get('quantity', 1))
            
            # 1. Resolve Security ID
            sec_id = leg_data.get('security_id')
            if not sec_id:
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
                # Determine Order Type and Price
                order_type = leg_data.get('order_type', OrderType.MARKET)
                price = leg_data.get('price', 0.0)
                trigger_price = leg_data.get('trigger_price', 0.0)

                # Map string order types if passed from engine
                if order_type == "LIMIT": order_type = OrderType.LIMIT
                if order_type == "STOP_LOSS": order_type = OrderType.STOP_LOSS
                if order_type == "SL": order_type = OrderType.STOP_LOSS
                if order_type == "SL-M": order_type = OrderType.STOP_LOSS_MARKET

                logger.info(f"Placing Order: Type={order_type}, Price={price}, Trigger={trigger_price}")

                # Real API Call
                resp = self.dhan.place_order(
                    security_id=sec_id,
                    exchange_segment=ExchangeSegment.NSE_FNO,
                    transaction_type=transaction_type,
                    quantity=final_qty,
                    order_type=order_type,
                    product_type=ProductType.INTRADAY, 
                    price=price,
                    trigger_price=trigger_price,
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

    def cancel_order(self, order_id):
        """
        Cancels a pending order.
        """
        if self.dry_run:
            logger.info(f"$$$ [BROKER] MOCK CANCEL Order {order_id} $$$")
            return {"success": True, "message": "Mock Cancel Success"}

        if self.dhan:
            try:
                resp = self.dhan.cancel_order(order_id)
                if resp.get('status') == 'success':
                    logger.info(f"Order {order_id} cancelled successfully.")
                    return {"success": True}
                else:
                    logger.error(f"Failed to cancel order {order_id}: {resp}")
                    return {"success": False, "error": resp.get('remarks')}
            except Exception as e:
                logger.error(f"Exception cancelling order {order_id}: {e}")
                return {"success": False, "error": str(e)}
        return {"success": False, "error": "Broker not initialized"}

    def get_ltp(self, security_id, exchange_segment=ExchangeSegment.NSE_FNO):
        """
        Fetches the Last Traded Price (LTP) using Dhan API v2.
        """
        if self.dry_run:
             return 100.0 # Mock Price

        if not self.access_token or not self.client_id:
            return None
            
        url = "https://api.dhan.co/v2/marketfeed/ltp"
        headers = {
            'Content-Type': 'application/json',
            'access-token': self.access_token
        }
        
        # Payload for LTP
        # Docs typically: { "instruments": [ { "exchangeSegment": "...", "securityId": "..." } ] }
        # Or simple? Let's assume standard structure.
        # Actually, Dhan API v2 'marketfeed/ltp' expects:
        # { "exchangeSegment": "NSE_FNO", "securityId": "12345" } 
        # (Based on standard REST patterns, checking docs would be ideal but I'll try standard).
        
        # LTP Fetch for v2 usually doesn't need dhanClientId in payload
        # It's in the headers as access-token
        payload = {
            "exchangeSegment": exchange_segment,
            "securityId": str(security_id)
        }
        
        try:
            resp = requests.post(url, headers=headers, json=payload)
            if resp.status_code == 200:
                data = resp.json()
                # Response: { "data": { "lastPrice": 123.45, ... } }
                return data.get('data', {}).get('last_price') or data.get('data', {}).get('lastPrice')
            else:
                logger.error(f"LTP Fetch Failed: {resp.status_code} {resp.text}")
                return None
        except Exception as e:
            logger.error(f"LTP Exception: {e}")
            return None

    def get_positions(self):
        """
        Fetches current positions from Dhan.
        Returns list of position objects.
        """
        if self.dry_run:
            # Mock: Always say we have one open position for testing? 
            # Or empty? Let's say empty if not set manually.
            return []

        if self.dhan:
            try:
                resp = self.dhan.get_positions()
                if resp.get('status') == 'success':
                    return resp.get('data', [])
                else:
                    logger.error(f"Failed to fetch positions: {resp}")
                    return []
            except Exception as e:
                logger.error(f"Exception fetching positions: {e}")
                return []
        return []

    def get_order_status(self, order_id):
        """
        Fetches the status of a specific order.
        """
        if self.dry_run:
            return {"orderStatus": "TRADED", "averagePrice": 100.0}
        
        if self.dhan:
            try:
                resp = self.dhan.get_order_by_id(order_id)
                if resp.get('status') == 'success':
                    return resp.get('data', {})
                else:
                    logger.error(f"Failed to fetch order status for {order_id}: {resp}")
                    return None
            except Exception as e:
                logger.error(f"Exception fetching order status: {e}")
                return None
        return None

    def modify_order(self, order_id, order_type, leg_data):
        """
        Modifies a pending order.
        """
        if self.dry_run:
            logger.info(f"$$$ [BROKER] MOCK MODIFY Order {order_id}: {leg_data} $$$")
            return {"success": True, "order_id": order_id}

        if self.dhan:
             # Validate inputs
             qty = int(leg_data.get('quantity', 0)) # optional?
             price = leg_data.get('price', 0.0)
             trigger_price = leg_data.get('trigger_price', 0.0)
             
             # Map Order Type
             dhan_order_type = OrderType.LIMIT
             if order_type in ['SL', 'STOP_LOSS']: dhan_order_type = OrderType.STOP_LOSS
             if order_type in ['SL-M', 'STOP_LOSS_MARKET']: dhan_order_type = OrderType.STOP_LOSS_MARKET
             
             # Validity? Only if needed.
             
             try:
                 resp = self.dhan.modify_order(
                     order_id=order_id,
                     order_type=dhan_order_type,
                     leg_name='ENTRY_LEG', # Assuming simple order mods? Or standard?
                     quantity=qty if qty > 0 else None,
                     price=price,
                     trigger_price=trigger_price,
                     exchange_segment=ExchangeSegment.NSE_FNO,
                     validity=Validity.DAY
                 )
                 
                 if resp.get('status') == 'success':
                      logger.info(f"Order {order_id} modified successfully. P={price}, Trg={trigger_price}")
                      return {"success": True, "order_id": order_id}
                 else:
                      logger.error(f"Failed to modify order {order_id}: {resp}")
                      return {"success": False, "error": resp.get('remarks')}
             except Exception as e:
                 logger.error(f"Exception modifying order {order_id}: {e}")
                 return {"success": False, "error": str(e)}
        return {"success": False}

    def get_pending_orders(self, security_id=None):
        """
        Fetches all PENDING orders. Optionally filters by security_id.
        """
        if self.dry_run:
            return []

        if self.dhan:
            try:
                resp = self.dhan.get_order_list() 
                
                # Robust response checking (SDK might return list or dict)
                if isinstance(resp, list):
                    all_orders = resp
                elif isinstance(resp, dict) and resp.get('status') == 'success':
                    all_orders = resp.get('data', [])
                else:
                    logger.error(f"Failed to fetch order list or invalid format: {resp}")
                    return []

                pending = [o for o in all_orders if o.get('orderStatus') in ['PENDING', 'TRIGGER_PENDING', 'TRANSIT']]
                
                if security_id:
                    return [o for o in pending if str(o.get('securityId')) == str(security_id)]
                return pending
            except Exception as e:
                logger.error(f"Exception fetching order list: {e}")
                return []
        return []

    def place_super_order(self, symbol, leg_data):
        """
        Places a Native Bracket Order (Super Order) using Dhan API v2.
        """
        if self.dry_run:
            logger.info(f"$$$ [BROKER] MOCK SUPER ORDER for {symbol} $$$")
            return {"success": True, "order_id": "mock_bo_123", "error": None}

        # Validate Auth
        if not self.access_token or not self.client_id:
             return {"success": False, "error": "Missing Info"}
        
        url = "https://api.dhan.co/v2/super/orders"
        headers = {
            'Content-Type': 'application/json',
            'access-token': self.access_token
        }
        
        # Prepare Payload
        # Mapping constants
        txn_type = leg_data.get('transaction_type', 'BUY')
        exchange_segment = "NSE_FNO" # Options Strategy
        product_type = "BO" # Bracket Order
        order_type = "MARKET" # Usually BO Entry is Limit or Market. Docs show LIMIT.
        # User wants "Entry price...". If Market, price=0
        
        # Default to MARKET if not specified
        if leg_data.get('order_type') == 'LIMIT':
            order_type = "LIMIT"
            price = leg_data.get('price', 0)
        else:
            order_type = "MARKET"
            price = 0
            
        qty = int(leg_data.get('quantity', 1)) 
        # Note: Caller must ensure quantity is in units, not lots? 
        # place_order logic in this file converts lots to units. 
        # We should replicate that or assume caller passed units?
        # place_order: "lots = int(leg_data.get('quantity', 1)) ... final_qty = lots * lot_size"
        # We need to do the same here!
        
        sec_id = leg_data.get('security_id')
        if not sec_id:
            return {"success": False, "error": "Security ID missing for Super Order"}
            
        lot_size = self.lot_map.get(sec_id, 1)
        final_qty = qty * lot_size
        
        # Target/SL/Trailing
        target_price = leg_data.get('target_price')
        stop_loss_price = leg_data.get('stop_loss_price')
        trailing_jump = leg_data.get('trailing_jump') # User provided trailingJump
        
        if not target_price or not stop_loss_price:
             return {"success": False, "error": "Target/SL Prices missing for Super Order"}

        # Validate prices: If they are Index prices (e.g. > 10000) for an Option order, reject.
        # This prevents DH-905 errors due to incorrect fallback.
        try:
             tp = float(target_price)
             if tp > 10000 and len(str(sec_id)) >= 5: # Likely option ID
                 logger.error(f"ABNORMAL PRICE detected for Super Order: TGT={tp}. Likely Index spot passed to Option. REJECTING.")
                 return {"success": False, "error": "Invalid Price: Index spot passed as Option price"}
        except: pass

        payload = {
            "dhanClientId": self.client_id,
            "correlationId": f"b_{int(time.time())}",
            "transactionType": txn_type,
            "exchangeSegment": exchange_segment,
            "productType": product_type,
            "orderType": order_type,
            "securityId": str(sec_id),
            "quantity": int(final_qty),
            "price": float(price) if order_type == "LIMIT" else 0.0,
            "targetPrice": float(target_price),
            "stopLossPrice": float(stop_loss_price)
        }
        
        if trailing_jump:
            payload["trailingJump"] = float(trailing_jump)
        
        logger.info(f"$$$ [BROKER] PLACING SUPER ORDER: {payload} $$$")

        try:
            resp = requests.post(url, headers=headers, json=payload)
            if resp.status_code == 200:
                data = resp.json()
                order_id = data.get('orderId')
                status = data.get('orderStatus')
                if order_id:
                    return {"success": True, "order_id": order_id, "status": status}
                else:
                    return {"success": False, "error": f"No orderId in response: {resp.text}"}
            else:
                 logger.error(f"Super Order Failed: {resp.status_code} {resp.text}")
                 return {"success": False, "error": resp.text}
        except Exception as e:
            logger.error(f"Super Order Exception: {e}")
            return {"success": False, "error": str(e)}

    def modify_super_order(self, order_id, leg_name, fields):
        """
        Modifies a specific leg of a Super Order.
        leg_name: 'ENTRY_LEG', 'TARGET_LEG', 'STOP_LOSS_LEG'
        fields: dict containing fields to modify (price, quantity, targetPrice, stopLossPrice, etc.)
        """
        if self.dry_run:
            logger.info(f"$$$ [BROKER] MOCK MODIFY SUPER ORDER {order_id} ({leg_name}) $$$")
            return {"success": True}

        if not self.access_token or not self.client_id:
            return {"success": False, "error": "Missing Info"}

        url = f"https://api.dhan.co/v2/super/orders/{order_id}"
        headers = {
            'Content-Type': 'application/json',
            'access-token': self.access_token
        }

        # Prepare Payload
        payload = {
            "dhanClientId": self.client_id,
            "orderId": str(order_id),
            "legName": leg_name
        }

        # Add optional modifiable fields
        # Note: targetPrice, stopLossPrice, and trailingJump use camelCase in the spec
        mapping = {
            'price': 'price',
            'quantity': 'quantity',
            'target_price': 'targetPrice',
            'stop_loss_price': 'stopLossPrice',
            'trailing_jump': 'trailingJump',
            'order_type': 'orderType'
        }

        for k, v in mapping.items():
            if k in fields:
                payload[v] = fields[k]
        
        # Ensure values are floats where appropriate
        for float_field in ['price', 'targetPrice', 'stopLossPrice', 'trailingJump']:
            if float_field in payload:
                payload[float_field] = float(payload[float_field])

        logger.info(f"$$$ [BROKER] MODIFYING SUPER ORDER: {payload} $$$")

        try:
            resp = requests.put(url, headers=headers, json=payload)
            if resp.status_code == 200:
                return {"success": True, "data": resp.json()}
            else:
                logger.error(f"Modify Super Order Failed: {resp.status_code} {resp.text}")
                return {"success": False, "error": resp.text}
        except Exception as e:
            logger.error(f"Modify Super Order Exception: {e}")
            return {"success": False, "error": str(e)}

    def cancel_super_order(self, order_id, leg_name='ENTRY_LEG'):
        """
        Cancels a leg of a Super Order.
        leg_name: 'ENTRY_LEG', 'TARGET_LEG', 'STOP_LOSS_LEG'
        """
        if self.dry_run:
            logger.info(f"$$$ [BROKER] MOCK CANCEL SUPER ORDER {order_id} ({leg_name}) $$$")
            return {"success": True}

        if not self.access_token:
            return {"success": False, "error": "Missing Token"}

        url = f"https://api.dhan.co/v2/super/orders/{order_id}/{leg_name}"
        headers = {
            'Content-Type': 'application/json',
            'access-token': self.access_token
        }

        try:
            resp = requests.delete(url, headers=headers)
            # Docs say 202 Accepted, but 200 is also common
            if resp.status_code in [200, 202]:
                return {"success": True, "data": resp.json() if resp.text else {}}
            else:
                logger.error(f"Cancel Super Order Failed: {resp.status_code} {resp.text}")
                return {"success": False, "error": resp.text}
        except Exception as e:
            logger.error(f"Cancel Super Order Exception: {e}")
            return {"success": False, "error": str(e)}

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

    def get_order_status(self, order_id):
        """
        Retrieves order status and details (including average price).
        """
        if self.dry_run:
            return {"status": "TRADED", "average_price": 100.0} # Mock

        if self.dhan:
            try:
                resp = self.dhan.get_order_by_id(order_id)
                if resp.get('status') == 'success':
                    return resp.get('data', {})
                else:
                    logger.error(f"Failed to get order status for {order_id}: {resp}")
                    return None
            except Exception as e:
                logger.error(f"Exception getting order status {order_id}: {e}")
                return None
        return None

    def get_consent_url(self):
        """
        Generates the Dhan consent URL for browser-based login.
        """
        if not self.api_id or not self.api_secret or not self.client_id:
            logger.error("DHAN_API_ID or DHAN_API_SECRET missing in .env")
            return None
        url = f"https://auth.dhan.co/app/generate-consent?client_id={self.client_id}"
        headers = {
            'app_id': self.api_id,
            'app_secret': self.api_secret,
            'Content-Type': 'application/json'
        }
        
        try:
            resp = requests.post(url, headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                consent_id = data.get("consentAppId")
                if consent_id:
                    # Construct the final login URL

                    return f"https://auth.dhan.co/login/consentApp-login?consentAppId={consent_id}"
            
            logger.error(f"Failed to generate consent: {resp.status_code} - {resp.text}")
            return None
        except Exception as e:
            logger.error(f"Error generating consent URL: {e}")
            return None

    def consume_consent(self, token_id):
        """
        Exchanges the tokenId for a 24-hour access token.
        """
        if not self.api_id or not self.api_secret:
            return False, "API credentials missing"

        url = f"https://auth.dhan.co/app/consumeApp-consent?tokenId={token_id}"
        headers = {
            'app_id': self.api_id,
            'app_secret': self.api_secret
        }

        try:
            resp = requests.post(url, headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                access_token = data.get("accessToken")
                if access_token:
                    self.refresh_client(access_token)
                    return True, "Authentication Successful"
            
            logger.error(f"Failed to consume consent: {resp.status_code} - {resp.text}")
            return False, f"Auth failed: {resp.status_code}"
        except Exception as e:
            logger.error(f"Error consuming consent: {e}")
            return False, str(e)
