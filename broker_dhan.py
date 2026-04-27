import logging
import os
import csv
import requests
import pyotp
import threading
import time
from datetime import datetime

from dhanhq import dhanhq
from dhanhq.orderupdate import OrderSocket

# Define constants locally as they are missing in dhanhq 2.0.2
class ExchangeSegment:
    NSE_FNO = "NSE_FNO"
    NSE_EQ = "NSE_EQ"
    BSE_EQ = "BSE_EQ"
    INDEX = "IDX_I" # Alias for index LTP fetching

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
    def __init__(self, redis_client=None):
        self.client_id = os.getenv("DHAN_CLIENT_ID")
        self.access_token = os.getenv("DHAN_ACCESS_TOKEN")
        self.api_id = os.getenv("DHAN_API_ID")
        self.api_secret = os.getenv("DHAN_API_SECRET")
        
        # Redis for Token Persistence
        self.r = redis_client
        
        if self.r:
            try:
                cached_token = self.r.get("dhan_access_token")
                if cached_token:
                    self.access_token = cached_token
                    logger.info("✅ Access Token loaded from Redis.")
            except Exception as e:
                logger.warning(f"Failed to load token from Redis: {e}")
        else:
            logger.warning("Redis client not provided to DhanClient. Persistence disabled.")

        self.dry_run = os.getenv("DRY_RUN", "false").lower() == "true"
        self.scrip_map = {}
        self.lot_map = {}
        self.exact_symbol_map = {}
        self.scrip_loaded = False

        # Load Scrip Master in background thread to prevent startup timeout
        def load_scrip_background():
            try:
                self._load_scrip_master()
                self.scrip_loaded = True
                logger.info("✅ Scrip Master loaded successfully in background")
            except Exception as e:
                logger.error(f"Failed to load Scrip Master: {e}")

        threading.Thread(target=load_scrip_background, daemon=True).start()

        self.dhan = None
        if self.client_id and self.access_token and DHAN_AVAILABLE:
            if not self.dry_run:
                self.dhan = dhanhq(self.client_id, self.access_token)
        elif not DHAN_AVAILABLE:
            logger.warning("dhanhq library not found. Install with `pip install dhanhq`.")
        else:
            logger.warning("No Dhan credentials found. Running in SIMULATION mode.")

    def save_access_token(self, token):
        """Persists the access token to Redis and reinitializes the broker client."""
        self.access_token = token
        if self.r:
            try:
                self.r.set("dhan_access_token", token)
                logger.info("✅ Access Token saved to Redis.")
            except Exception as e:
                logger.error(f"Failed to save token to Redis: {e}")

        # Reinitialize broker client with the new token
        if self.client_id and DHAN_AVAILABLE and not self.dry_run:
            self.dhan = dhanhq(self.client_id, self.access_token)
            logger.info("✅ Dhan client reinitialized with new token.")

    def start_order_update_listener(self, on_update):
        """Start Dhan Live Order Update WebSocket in a daemon thread.

        on_update(order_id, status, avg_price) is called for each order event.
        Reconnects automatically on disconnect with exponential backoff.
        """
        if not self.client_id or not self.access_token or self.dry_run:
            logger.warning("Order update listener skipped (no credentials or dry-run mode).")
            return

        import asyncio

        class _AppSocket(OrderSocket):
            def __init__(self_, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self_._on_update = on_update

            async def handle_order_update(self_, order_update):
                try:
                    if order_update.get('Type') == 'order_alert':
                        data = order_update.get('Data', {})
                        order_id = str(data.get('orderNo', ''))
                        status = data.get('status', '')
                        avg_price = data.get('averageTradedPrice') or data.get('tradedPrice')
                        if order_id:
                            self_._on_update(order_id, status, avg_price)
                except Exception as e:
                    logger.error(f"Order update handler error: {e}")

        def _run():
            import asyncio as _asyncio
            backoff = 5
            while True:
                try:
                    sock = _AppSocket(self.client_id, self.access_token)
                    loop = _asyncio.new_event_loop()
                    _asyncio.set_event_loop(loop)
                    loop.run_until_complete(sock.connect_order_update())
                except Exception as e:
                    logger.warning(f"Order update WS disconnected: {e}. Reconnecting in {backoff}s…")
                    time.sleep(backoff)
                    backoff = min(backoff * 2, 120)
                else:
                    backoff = 5

        t = threading.Thread(target=_run, daemon=True, name="dhan-order-ws")
        t.start()
        logger.info("✅ Dhan Live Order Update listener started.")

    def get_index_id(self, symbol):
        """Returns standard Dhan Security ID for indices."""
        mapping = {
            "NIFTY": "13",
            "BANKNIFTY": "25",
            "FINNIFTY": "27"
        }
        return mapping.get(symbol.upper())

    def _load_scrip_master(self):
        """
        Downloads and parses the Dhan Scrip Master CSV.
        """
        csv_file = "dhan_scrip_master.csv"
        url = "https://images.dhan.co/api-data/api-scrip-master.csv"
        
        # Download if not exists or older than 12 hours
        file_age_hours = 999
        if os.path.exists(csv_file):
            import time
            file_age_hours = (time.time() - os.path.getmtime(csv_file)) / 3600

        if file_age_hours > 12:
            logger.info(f"Downloading fresh Scrip Master from {url}...")
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
                        sec_id = row.get('SEM_SMST_SECURITY_ID', '').strip()
                        self.scrip_map[key] = sec_id
                        
                        # Store lot size
                        try:
                            self.lot_map[sec_id] = int(float(row.get('SEM_LOT_UNITS', 1)))
                        except:
                            self.lot_map[sec_id] = 1
                            
                        # Store exact trading symbol for explicit option strings
                        trading_sym = row.get('SEM_TRADING_SYMBOL', '').strip()
                        if trading_sym:
                            self.exact_symbol_map[trading_sym] = {
                                "security_id": sec_id,
                                "strike": strike,
                                "expiry": expiry_raw,
                                "symbol": trading_sym,
                                "opt_type": opt_type,
                                "underlying": sym
                            }
                            
                        count += 1
            
            # --- Identify Expiry Days for Indices ---
            self.expiry_indices = set()
            today_str = datetime.now().strftime('%Y-%m-%d')
            for (sym, strike, opt_type, exp) in self.scrip_map.keys():
                if exp == today_str and sym in ['NIFTY', 'BANKNIFTY', 'FINNIFTY']:
                    self.expiry_indices.add(sym)
            
            if self.expiry_indices:
                logger.info(f"Today is Expiry Day for: {list(self.expiry_indices)}")
            else:
                logger.debug(f"Today ({today_str}) is not an expiry day for major indices.")

            logger.info(f"Loaded {count} instruments into Scrip Map.")
        except Exception as e:
            logger.error(f"Error parsing CSV: {e}")

    def is_expiry_day(self, underlying):
        """
        Checks if today is an expiry day for the given underlying index.
        """
        return underlying.upper() in getattr(self, 'expiry_indices', set())

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

        # Get only today's or future expiries using IST
        from datetime import datetime
        import pytz
        IST = pytz.timezone('Asia/Kolkata')
        today_str = datetime.now(IST).strftime('%Y-%m-%d')

        future_expiries = [e for e in expiries if e >= today_str]

        if not future_expiries:
            logger.warning(f"No future expiries found for {symbol} among {len(expiries)} total. Using earliest available.")
            return sorted(list(expiries))[0]

        # Sort YYYY-MM-DD
        sorted_exp = sorted(future_expiries)
        # Return the first one (nearest)
        return sorted_exp[0]

    def get_next_expiry(self, symbol):
        """
        Returns the second-nearest future expiry for a symbol.
        Used on expiry day to trade next week's contracts and avoid expiry-day risk.
        Falls back to nearest expiry if only one future expiry exists.
        """
        expiries = set()
        for key in self.scrip_map.keys():
            if key[0] == symbol:
                expiries.add(key[3])

        if not expiries:
            return None

        import pytz
        IST = pytz.timezone('Asia/Kolkata')
        today_str = datetime.now(IST).strftime('%Y-%m-%d')

        sorted_future = sorted(e for e in expiries if e >= today_str)

        if len(sorted_future) >= 2:
            return sorted_future[1]
        elif sorted_future:
            logger.warning(f"Only one future expiry for {symbol}; using it as next expiry fallback.")
            return sorted_future[0]

        logger.warning(f"No future expiries found for {symbol}. Using latest available.")
        return sorted(expiries)[-1]

    def calculate_lots_by_margin(self, security_id, transaction_type='BUY', ltp=0):
        """
        Computes the maximum number of lots tradeable given available margin.
        Fetches fund limits and margin required for 1 lot, then returns floor(available / per_lot).
        Returns at least 1 lot on any failure.
        """
        try:
            fund_resp = self.get_fund_limits()
            if fund_resp.get('status') != 'success':
                logger.warning(f"Fund limits unavailable ({fund_resp}); defaulting to 1 lot.")
                return 1

            fund_data = fund_resp.get('data', {})
            # Dhan API has a typo: 'availabelBalance'; also accept the correct spelling
            available = float(
                fund_data.get('availabelBalance') or
                fund_data.get('availableBalance') or 0
            )
            if available <= 0:
                logger.warning(f"Available margin is {available}; defaulting to 1 lot.")
                return 1

            lot_size = self.lot_map.get(str(security_id), 1)

            if not ltp or float(ltp) <= 0:
                logger.warning(f"calculate_lots_by_margin: LTP is {ltp} for {security_id} — fetching live.")
                ltp = self.get_ltp(security_id) or 0
            if float(ltp) <= 0:
                logger.warning(f"calculate_lots_by_margin: LTP still 0 for {security_id}; defaulting to 1 lot.")
                return 1

            margin_resp = self.margin_calculator({
                'security_id': security_id,
                'exchange_segment': ExchangeSegment.NSE_FNO,
                'transaction_type': transaction_type,
                'quantity': lot_size,
                'product_type': 'INTRADAY',
                'price': float(ltp),
            })

            if margin_resp.get('status') != 'success':
                logger.warning(f"Margin calc failed ({margin_resp}); defaulting to 1 lot.")
                return 1

            margin_per_lot = float(margin_resp.get('data', {}).get('totalMarginRequired', 0))
            if margin_per_lot <= 0:
                logger.warning(f"Margin per lot = {margin_per_lot} for {security_id}; defaulting to 1 lot.")
                return 1

            max_lots = int(available / margin_per_lot)
            lots = max(1, max_lots)
            logger.info(
                f"Margin-based qty [{security_id}]: available={available:.0f}, "
                f"per_lot={margin_per_lot:.0f}, lots={lots}"
            )
            return lots

        except Exception as e:
            logger.error(f"calculate_lots_by_margin error: {e}")
            return 1

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
                
            if self.is_expiry_day(underlying):
                expiry = self.get_next_expiry(underlying)
                logger.info(f"Expiry day for {underlying} — using next-week expiry: {expiry}")
            else:
                expiry = self.get_nearest_expiry(underlying)
            if not expiry:
                logger.error(f"No expiry found for {underlying}")
                return None
            
            sec_id = self._get_security_id(underlying, strike, side, expiry)
            if sec_id:
                logger.info(f"Selected ITM for {underlying} ({side}): {strike} Exp: {expiry} -> ID: {sec_id}")
                # TradingView format: NSE:NIFTY260421P24150 (underlying + YYMMDD + C/P + strike)
                exp_dt = expiry.replace("-", "")  # YYYYMMDD
                tv_exp = exp_dt[2:]  # YYMMDD
                tv_cp = "C" if side == "CE" else "P"
                tv_symbol = f"NSE:{underlying}{tv_exp}{tv_cp}{int(strike)}"
                return {
                    "security_id": sec_id,
                    "strike": strike,
                    "expiry": expiry,
                    "symbol": f"{underlying}_{int(strike)}_{side}",
                    "tv_symbol": tv_symbol,
                }
            else:
                logger.error(f"Could not find exact ITM contract for {underlying} {strike} {side} {expiry}")
                return None
        except Exception as e:
            logger.error(f"Error in ITM Selection: {e}")
            return None

    def get_security_info_by_symbol(self, exact_symbol):
        """Returns the dictionary mapping for an exact option string (e.g. NIFTY24DEC22500CE)."""
        return self.exact_symbol_map.get(exact_symbol.strip().upper())

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

    def place_order(self, symbol, leg_data):
        """Generic order placement wrapper."""
        txn_type = leg_data.get('transaction_type', TransactionType.BUY)
        return self._place_order(symbol, leg_data, txn_type)

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
                elif resp.get('errorCode') == 'DH-901' or 'Unauthorized' in str(resp):
                     logger.warning("Order Placement: 401 Unauthorized detected. Syncing token...")
                     if self._sync_token_from_redis():
                         # Retry placement with re-initialized self.dhan
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
                     
                     return {"success": False, "order_id": None, "error": resp.get('remarks', 'Authentication Failed')}
                else:
                     err = resp.get('remarks') or resp.get('errorCode') or str(resp)
                     logger.error(f"Order Placement failed: {err} | full response: {resp}")
                     return {"success": False, "order_id": None, "error": err}
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

    def _round_to_tick(self, price, tick=0.05):
        """Rounds price to the nearest tick size."""
        if not price: return 0.0
        return round(round(float(price) / tick) * tick, 2)

    def get_index_spot_fallback(self, symbol):
        """
        Fetches live index spot price from Yahoo Finance.
        Works reliably without authentication — used when Dhan is unavailable.
        Returns the last traded price as float, or None on failure.
        """
        yahoo_map = {
            "NIFTY": "^NSEI",
            "BANKNIFTY": "^NSEBANK",
            "FINNIFTY": "NIFTY_FIN_SERVICE.NS",
        }
        ticker = yahoo_map.get(symbol.upper())
        if not ticker:
            logger.warning(f"No Yahoo ticker mapping for {symbol}")
            return None

        try:
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1m&range=1d"
            resp = requests.get(
                url,
                headers={"User-Agent": "Mozilla/5.0 (compatible; TradingAgent/1.0)"},
                timeout=8
            )
            if resp.status_code == 200:
                data = resp.json()
                price = data['chart']['result'][0]['meta'].get('regularMarketPrice')
                if price and float(price) > 0:
                    logger.info(f"Yahoo Fallback: {symbol} ({ticker}) spot = {price}")
                    return float(price)
            logger.warning(f"Yahoo Fallback: Empty response for {ticker} ({resp.status_code})")
            return None
        except Exception as e:
            logger.error(f"Yahoo Fallback failed for {symbol}: {e}")
            return None

    def get_ltp(self, security_id, exchange_segment=ExchangeSegment.NSE_FNO):
        """
        Fetches the Last Traded Price (LTP) using Dhan API v2.
        Falls back to NSE public API for index prices when Dhan is unavailable.
        """
        # For index LTP requests (IDX_I segment), always try NSE public fallback
        # since it works without authentication
        if exchange_segment == "IDX_I":
            # Map known Dhan index security IDs to symbols
            index_id_map = {"13": "NIFTY", "25": "BANKNIFTY", "27": "FINNIFTY"}
            sym = index_id_map.get(str(security_id))
            if sym:
                # Try Dhan API first (if credentials available and not dry_run)
                if self.access_token and self.client_id and not self.dry_run:
                    try:
                        url = "https://api.dhan.co/v2/marketfeed/ltp"
                        headers = {
                            'Content-Type': 'application/json',
                            'access-token': self.access_token,
                            'client-id': self.client_id
                        }
                        payload = {exchange_segment: [int(security_id)]}
                        resp = requests.post(url, headers=headers, json=payload, timeout=5)
                        if resp.status_code == 200:
                            data = resp.json()
                            seg_data = data.get('data', {}).get(exchange_segment, {})
                            inst_data = seg_data.get(str(security_id), {})
                            price = inst_data.get('last_price')
                            if price and float(price) > 0:
                                return float(price)
                    except Exception as e:
                        logger.warning(f"Dhan index LTP failed: {e}")

                # Always fall back to NSE public API for index prices
                price = self.get_index_spot_fallback(sym)
                if price:
                    return price
            logger.error(f"Index LTP unavailable for ID {security_id}")
            return None

        if self.dry_run:
            return 100.0  # Mock Price for options (not used for index)

        if not self.access_token or not self.client_id:
            return None

        url = "https://api.dhan.co/v2/marketfeed/ltp"
        headers = {
            'Content-Type': 'application/json',
            'access-token': self.access_token,
            'client-id': self.client_id
        }

        # Dhan API v2 'marketfeed/ltp' expects:
        # { "NSE_FNO": [sec_id1, sec_id2], "NSE_EQ": [sec_id3] }
        # securityId MUST be sent as an integer in the list.
        payload = {
            exchange_segment: [int(security_id)]
        }

        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                # Response Structure: { "data": { "NSE_FNO": { "123": { "last_price": 100 } } }, "status": "success" }
                seg_data = data.get('data', {}).get(exchange_segment, {})
                inst_data = seg_data.get(str(security_id), {})
                return inst_data.get('last_price')
            elif resp.status_code == 401:
                logger.warning("LTP Fetch: 401 Unauthorized. Attempting token sync from Redis...")
                if self._sync_token_from_redis():
                    # Retry once with new token
                    headers['access-token'] = self.access_token
                    resp = requests.post(url, headers=headers, json=payload, timeout=5)
                    if resp.status_code == 200:
                        data = resp.json()
                        seg_data = data.get('data', {}).get(exchange_segment, {})
                        inst_data = seg_data.get(str(security_id), {})
                        return inst_data.get('last_price')
                
                logger.error(f"LTP Fetch Failed after sync attempt: {resp.status_code} {resp.text}")
                return None
            else:
                logger.error(f"LTP Fetch Failed: {resp.status_code} {resp.text}")
                return None
        except Exception as e:
            logger.error(f"LTP Exception: {e}")
            return None

    def get_fund_limits(self):
        """
        Retrieves available fund limits from Dhan.
        Useful for checking available balance before placement.
        """
        if self.dry_run:
            return {"status": "success", "data": {"availabelBalance": 50000.00}}
        
        if self.dhan:
            try:
                resp = self.dhan.get_fund_limits()
                if resp.get('status') == 'success':
                    return resp
                elif resp.get('errorCode') == 'DH-901' or 'Unauthorized' in str(resp):
                    logger.warning("Get Fund Limits: 401 Unauthorized. Syncing token...")
                    if self._sync_token_from_redis():
                        return self.dhan.get_fund_limits()
                else:
                    logger.error(f"Failed to fetch fund limits: {resp}")
                    return {"status": "error", "message": resp.get('remarks')}
            except Exception as e:
                logger.error(f"Exception fetching fund limits: {e}")
                return {"status": "error", "message": str(e)}
        return {"status": "error", "message": "Broker not initialized"}

    def margin_calculator(self, order_data):
        """
        Calculates margin required for a specific order.
        order_data: { security_id, exchange_segment, transaction_type, quantity, product_type, price }
        """
        if self.dry_run:
            # Simple mock calculation: 5000 per lot (quantity)
            qty = int(order_data.get('quantity', 1))
            return {"status": "success", "data": {"totalMarginRequired": qty * 5000.0}}
            
        if self.dhan:
            try:
                # Default productType to INTRADAY if not specified
                if 'productType' not in order_data:
                    order_data['productType'] = 'INTRADAY'
                    
                # SDK expects individual arguments, not a dictionary
                def _call_margin():
                    return self.dhan.margin_calculator(
                        security_id=order_data.get('security_id'),
                        exchange_segment=order_data.get('exchange_segment'),
                        transaction_type=order_data.get('transaction_type'),
                        quantity=order_data.get('quantity'),
                        product_type=order_data.get('product_type', 'INTRADAY'),
                        price=order_data.get('price', 0)
                    )

                resp = _call_margin()
                if resp.get('status') == 'success':
                    return resp
                elif resp.get('errorCode') == 'DH-901' or 'Unauthorized' in str(resp):
                    logger.warning("Margin Calculator: 401 Unauthorized. Syncing token...")
                    if self._sync_token_from_redis():
                        return _call_margin()
                
                return {"status": "error", "message": resp.get('remarks') or resp.get('errorMessage')}
            except Exception as e:
                logger.error(f"Exception in margin calculator: {e}")
                return {"status": "error", "message": str(e)}
        return {"status": "error", "message": "Broker not initialized"}

    def get_multi_margin_calculator(self, orders_list):
        """
        Calculates margin for multiple orders using the Dhan v2 multi endpoint.
        """
        if self.dry_run:
            total = sum(int(o.get('quantity', 1)) * 4500.0 for o in orders_list)
            return {"status": "success", "data": {"totalMarginRequired": total}}

        if not self.access_token:
             return {"status": "error", "message": "Missing info"}

        url = "https://api.dhan.co/v2/margincalculator/multi"
        headers = {
            'Content-Type': 'application/json',
            'access-token': self.access_token
        }
        
        # Ensure all orders have dhanClientId and default INTRADAY
        payload = []
        for o in orders_list:
             item = o.copy()
             item['dhanClientId'] = self.client_id
             if 'productType' not in item:
                 item['productType'] = 'INTRADAY'
             payload.append(item)

        try:
            resp = requests.post(url, headers=headers, json=payload)
            if resp.status_code == 200:
                return resp.json()
            elif resp.status_code == 401:
                logger.warning("Multi Margin: 401 Unauthorized. Syncing...")
                if self._sync_token_from_redis():
                    headers['access-token'] = self.access_token
                    resp = requests.post(url, headers=headers, json=payload)
                    if resp.status_code == 200:
                        return resp.json()
                return {"status": "error", "message": "Auth failed"}
            else:
                return {"status": "error", "message": resp.text}
        except Exception as e:
            logger.error(f"Multi Margin Exception: {e}")
            return {"status": "error", "message": str(e)}

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
                elif resp.get('errorCode') == 'DH-901' or 'Unauthorized' in str(resp):
                    logger.warning("Get Positions: 401 Unauthorized. Syncing token...")
                    if self._sync_token_from_redis():
                        return self.dhan.get_positions()
                else:
                    logger.error(f"Failed to fetch positions: {resp}")
                    return []
            except Exception as e:
                logger.error(f"Exception fetching positions: {e}")
                return []
        return []

    def get_all_orders(self):
        """Fetches the full order book from Dhan."""
        if self.dry_run:
            return []
        if not self.dhan:
            return []
        try:
            resp = self.dhan.get_order_list()
            if resp.get('status') == 'success':
                return resp.get('data', [])
            if resp.get('errorCode') == 'DH-901' or 'Unauthorized' in str(resp):
                logger.warning("Get Orders: 401 Unauthorized. Syncing token...")
                if self._sync_token_from_redis():
                    resp = self.dhan.get_order_list()
                    return resp.get('data', []) if resp.get('status') == 'success' else []
            logger.error(f"Failed to fetch order list: {resp}")
            return []
        except Exception as e:
            logger.error(f"Exception fetching order list: {e}")
            return []

    def kill_switch(self):
        """
        Emergency kill switch.
        Step 1 — square off every net-open position with a market order.
        Step 2 — cancel every TRANSIT / PENDING / PART_TRADED order.
        Returns a result summary dict.
        """
        CANCELLABLE = {"TRANSIT", "PENDING", "PART_TRADED"}
        results = {"squaredoff": [], "cancelled": [], "errors": []}

        # --- Step 1: Square off positions ---
        try:
            positions = self.get_positions()
            for pos in positions:
                net_qty = int(pos.get('netQty', 0))
                if net_qty == 0:
                    continue

                sec_id = pos.get('securityId')
                exchange_seg = pos.get('exchangeSegment', ExchangeSegment.NSE_FNO)
                product_type = pos.get('productType', ProductType.INTRADAY)
                symbol = pos.get('tradingSymbol', sec_id)
                txn_type = TransactionType.SELL if net_qty > 0 else TransactionType.BUY
                qty = abs(net_qty)

                logger.warning(f"Kill Switch: Squaring off {txn_type} {qty} × {symbol}")

                if self.dhan and not self.dry_run:
                    try:
                        resp = self.dhan.place_order(
                            security_id=sec_id,
                            exchange_segment=exchange_seg,
                            transaction_type=txn_type,
                            quantity=qty,
                            order_type=OrderType.MARKET,
                            product_type=product_type,
                            price=0.0
                        )
                        if resp.get('status') == 'success':
                            results["squaredoff"].append({"symbol": symbol, "qty": qty, "side": txn_type})
                        else:
                            err = f"Squareoff failed for {symbol}: {resp.get('remarks', resp)}"
                            logger.error(err)
                            results["errors"].append(err)
                    except Exception as e:
                        err = f"Exception squaring off {symbol}: {e}"
                        logger.error(err)
                        results["errors"].append(err)
                else:
                    results["squaredoff"].append({"symbol": symbol, "qty": qty, "side": txn_type, "mock": True})

        except Exception as e:
            err = f"Position fetch failed: {e}"
            logger.error(f"Kill Switch: {err}")
            results["errors"].append(err)

        # --- Step 2: Cancel all open/pending orders ---
        try:
            orders = self.get_all_orders()
            for order in orders:
                if order.get('orderStatus') not in CANCELLABLE:
                    continue
                order_id = order.get('orderId')
                symbol = order.get('tradingSymbol', order_id)
                logger.warning(f"Kill Switch: Cancelling order {order_id} ({symbol})")
                resp = self.cancel_order(order_id)
                if resp.get('success'):
                    results["cancelled"].append({"order_id": order_id, "symbol": symbol})
                else:
                    err = f"Cancel failed for {order_id}: {resp.get('error')}"
                    logger.error(err)
                    results["errors"].append(err)
        except Exception as e:
            err = f"Order cancel sweep failed: {e}"
            logger.error(f"Kill Switch: {err}")
            results["errors"].append(err)

        logger.warning(
            f"Kill Switch complete — squared_off={len(results['squaredoff'])}, "
            f"cancelled={len(results['cancelled'])}, errors={len(results['errors'])}"
        )
        return results

    def get_order_status(self, order_id):
        """
        Retrieves order status and details. Handles both SDK dict and raw list responses.
        """
        if self.dry_run:
            return {"orderStatus": "TRADED", "averagePrice": 100.0}
        
        if self.dhan:
            try:
                resp = self.dhan.get_order_by_id(order_id)
                # Handle List response (often returned on 429 or SDK edge cases)
                if isinstance(resp, list):
                    logger.warning(f"Dhan API returned LIST for order {order_id}: {resp}")
                    if len(resp) > 0 and isinstance(resp[0], dict):
                        return resp[0]
                    return None

                if isinstance(resp, dict) and resp.get('status') == 'success':
                    return resp.get('data', {})
                elif isinstance(resp, dict) and (resp.get('errorCode') == 'DH-901' or 'Unauthorized' in str(resp)):
                    logger.warning("Get Order Status: 401 Unauthorized. Syncing token...")
                    if self._sync_token_from_redis():
                        return self.dhan.get_order_by_id(order_id)
                else:
                    logger.error(f"Failed to fetch order status for {order_id}: {resp}")
                    return None
            except Exception as e:
                logger.error(f"Exception fetching order status {order_id}: {e}")
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
        Fetches all PENDING standard orders.
        """
        if self.dry_run:
            return []

        if self.dhan:
            try:
                resp = self.dhan.get_order_list() 
                
                if isinstance(resp, list):
                    all_orders = resp
                elif isinstance(resp, dict) and resp.get('status') == 'success':
                    all_orders = resp.get('data', [])
                elif isinstance(resp, dict) and (resp.get('errorCode') == 'DH-901' or 'Unauthorized' in str(resp)):
                    logger.warning("Get Pending Orders: 401 Unauthorized. Syncing token...")
                    if self._sync_token_from_redis():
                        # Retry once
                        resp = self.dhan.get_order_list()
                        if isinstance(resp, list): all_orders = resp
                        elif isinstance(resp, dict) and resp.get('status') == 'success':
                            all_orders = resp.get('data', [])
                        else: all_orders = []
                    else:
                        all_orders = []
                else:
                    all_orders = []

                pending = [o for o in all_orders if o.get('orderStatus') in ['PENDING', 'TRIGGER_PENDING', 'TRANSIT', 'PARTIALLY_FILLED', 'MODIFY_PENDING']]
                
                if security_id:
                    sid_str = str(security_id).strip()
                    return [o for o in pending if str(o.get('securityId') or o.get('security_id') or '').strip() == sid_str]
                return pending
            except Exception as e:
                logger.error(f"Exception fetching order list: {e}")
                return []
        return []

    def get_super_orders(self, security_id=None):
        """
        Fetches Super Orders from the dedicated endpoint.
        Returns a list of legs extracted from active super orders.
        """
        if self.dry_run:
            return []
            
        url = "https://api.dhan.co/v2/super/orders"
        headers = {
            'Content-Type': 'application/json',
            'access-token': self.access_token
        }
        
        try:
            resp = requests.get(url, headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                # data is expected to be a list of Super Orders
                if not isinstance(data, list):
                    # Sometimes wrapped in status/data dict
                    if isinstance(data, dict):
                        data = data.get('data', [])
                    else:
                        return []
                
                active_legs = []
                for so in data:
                    # Filter by security_id if provided
                    so_sid = str(so.get('securityId') or '').strip()
                    if security_id and so_sid != str(security_id).strip():
                        continue
                        
                    status = so.get('orderStatus')
                    # We only care about PENDING or PART_TRADED super orders
                    if status not in ['PENDING', 'PART_TRADED', 'TRANSIT', 'TRADED']:
                         # TRADED is fine because legs might still be pending
                         pass
                         
                    # Extract Legs
                    # The main order might be the ENTRY_LEG
                    main_oid = so.get('orderId')
                    
                    for leg in so.get('legDetails', []):
                         leg_status = leg.get('orderStatus')
                         if leg_status in ['PENDING', 'TRIGGER_PENDING', 'TRANSIT']:
                             leg_info = {
                                 'orderId': main_oid, # modification uses Parent OID for Super Orders
                                 'legName': leg.get('legName'),
                                 'orderType': leg.get('orderType') or ('LIMIT' if leg.get('legName') == 'TARGET_LEG' else 'STOP_LOSS_LEG'),
                                 'transactionType': leg.get('transactionType'),
                                 'price': leg.get('price'),
                                 'triggerPrice': leg.get('triggerPrice'),
                                 'trailingJump': leg.get('trailingJump'),
                                 'quantity': leg.get('quantity') or leg.get('totalQuatity') or so.get('quantity'),
                                 'securityId': so_sid,
                                 'tradingSymbol': so.get('tradingSymbol'),
                                 'is_super_order': True
                             }

                             active_legs.append(leg_info)
                
                return active_legs
            else:
                logger.error(f"Failed to fetch Super Order list: {resp.status_code} {resp.text}")
                return []
        except Exception as e:
            logger.error(f"Exception fetching Super Orders: {e}")
            return []


    def place_conditional_order(self, sec_id, exchange_seg, quantity, operator, comparing_value, transaction_type="SELL", product_type="MARGIN", trigger_sec_id=None, user_note=None):
        """
        Places a Dhan Conditional Trigger Order (GTT-style).
        If trigger_sec_id is provided, the alert triggers on THAT instrument (e.g. Index), 
        but the order is placed for `sec_id` (e.g. Option).
        """
        # Ensure price is rounded to 0.05 tick
        comparing_value = self._round_to_tick(comparing_value)

        if self.dry_run:
            mock_id = f"DRY_{operator}_{comparing_value}"
            logger.info(f"[DRY RUN] Conditional Order: {transaction_type} {operator} @ {comparing_value} secId={sec_id} TriggerId={trigger_sec_id or sec_id} Note={user_note}")
            return {"success": True, "alert_id": mock_id, "error": None}

        if not self.client_id or not self.access_token:
            return {"success": False, "alert_id": None, "error": "Missing credentials"}

        import pytz
        IST = pytz.timezone('Asia/Kolkata')
        exp_date = datetime.now(IST).strftime('%Y-%m-%d')

        url = "https://api.dhan.co/v2/alerts/orders"
        headers = {
            'Content-Type': 'application/json',
            'access-token': self.access_token,
            'client-id': self.client_id
        }
        
        # Use trigger_sec_id if provided, otherwise default to the order's sec_id
        actual_trigger_id = str(trigger_sec_id) if trigger_sec_id else str(sec_id)

        # When trigger is an index (sec IDs: 13=NIFTY, 25=BANKNIFTY, 27=FINNIFTY),
        # the condition block MUST use IDX_I exchange segment — not NSE_FNO.
        # Using NSE_FNO for index IDs causes Dhan DH-905 Input_Exception.
        INDEX_IDS = {"13", "25", "27"}
        condition_exchange_seg = "IDX_I" if str(actual_trigger_id) in INDEX_IDS else exchange_seg

        payload = {
            "dhanClientId": self.client_id,
            "userNote": user_note if user_note else "GTT Trigger",
            "condition": {
                "comparisonType": "LTP_WITH_VALUE",
                "exchangeSegment": condition_exchange_seg,
                "securityId": str(actual_trigger_id),
                "operator": operator,
                "comparingValue": str(comparing_value),
                "frequency": "ONCE"
            },
            "orders": [{
                "transactionType": transaction_type,
                "exchangeSegment": exchange_seg,
                "productType": product_type,
                "orderType": "MARKET",
                "securityId": str(sec_id),
                "quantity": str(quantity),
                "validity": "DAY",
                "price": "0",
                "disclosedQuantity": "0",
                "triggerPrice": "0",
                "afterMarketOrder": False,
                "amo": False
            }]
        }
        
        # High visibility payload logging for production debugging
        import json
        payload_json = json.dumps(payload)
        logger.info(f"$$$ SENDING GTT ALERT PAYLOAD: {payload_json}")
        try:
            resp = requests.post(url, headers=headers, json=payload)
            if resp.status_code in [200, 201]:
                data = resp.json()
                alert_id = data.get('alertId') or (data.get('data') or {}).get('alertId')
                logger.info(f"Conditional order placed: alertId={alert_id}, op={operator}, val={comparing_value}, triggerSec={actual_trigger_id}")
                return {"success": True, "alert_id": alert_id, "error": None}
            else:
                logger.error(f"Conditional order failed: {resp.status_code} {resp.text}")
                return {"success": False, "alert_id": None, "error": resp.text}
        except Exception as e:
            logger.error(f"Conditional order exception: {e}")
            return {"success": False, "alert_id": None, "error": str(e)}

    def cancel_conditional_order(self, alert_id):
        """
        Cancels an active Dhan Conditional Trigger by alertId.
        Returns: {"success": bool}
        """
        if self.dry_run:
            logger.info(f"[DRY RUN] Cancel conditional order alertId={alert_id}")
            return {"success": True}

        if not self.access_token:
            return {"success": False, "error": "Missing credentials"}

        url = f"https://api.dhan.co/v2/alerts/orders/{alert_id}"
        headers = {
            'Content-Type': 'application/json',
            'access-token': self.access_token,
            'client-id': self.client_id
        }
        try:
            resp = requests.delete(url, headers=headers)
            if resp.status_code in [200, 204]:
                logger.info(f"Conditional order cancelled: alertId={alert_id}")
                return {"success": True}
            else:
                logger.error(f"Cancel conditional order failed: {resp.status_code} {resp.text}")
                return {"success": False, "error": resp.text}
        except Exception as e:
            logger.error(f"Cancel conditional order exception: {e}")
            return {"success": False, "error": str(e)}

    def modify_conditional_order(self, alert_id, quantity, comparing_value):
        """
        Modifies an existing Dhan Conditional Trigger Order (GTT).
        Endpoint: PUT /alerts/orders/{alertId}
        """
        comparing_value = self._round_to_tick(comparing_value)

        if self.dry_run:
            logger.info(f"[DRY RUN] Modifying Conditional Order {alert_id}: Qty={quantity}, Val={comparing_value}")
            return {"success": True, "alert_id": alert_id, "error": None}

        if not self.access_token:
            return {"success": False, "error": "Missing access token"}

        url = f"https://api.dhan.co/v2/alerts/orders/{alert_id}"
        headers = {
            'Content-Type': 'application/json',
            'access-token': self.access_token,
        }
        
        # Dhan API typically requires the FULL structure for PUT modification.
        existing = self.get_conditional_order_details(alert_id)
        if not existing:
             return {"success": False, "error": "Could not fetch existing alert details for modification"}

        payload = {
            "dhanClientId": self.client_id,
            "condition": existing.get("condition", {}),
            "orders": existing.get("orders", [])
        }

        # Update values
        if "condition" in payload:
            payload["condition"]["comparingValue"] = float(comparing_value)
        
        if "orders" in payload and len(payload["orders"]) > 0:
            payload["orders"][0]["quantity"] = int(quantity)

        try:
            resp = requests.put(url, headers=headers, json=payload, timeout=5)
            if resp.status_code == 200:
                logger.info(f"Conditional Order {alert_id} modified successfully.")
                return {"success": True, "alert_id": alert_id, "error": None}
            else:
                logger.error(f"Modify Conditional Failed: {resp.status_code} {resp.text}")
                return {"success": False, "error": resp.text}
        except Exception as e:
            logger.error(f"Modify Conditional Exception: {e}")
            return {"success": False, "error": str(e)}

    def get_conditional_order_details(self, alert_id):
        """Fetches details for a specific alert."""
        if self.dry_run: return {}
        url = f"https://api.dhan.co/v2/alerts/orders/{alert_id}"
        headers = {
            'access-token': self.access_token,
            'client-id': self.client_id
        }
        try:
            resp = requests.get(url, headers=headers)
            if resp.status_code == 200:
                return resp.json().get('data', {})
        except:
            pass
        return None



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
        product_type = "INTRADAY" # Super Orders must be INTRADAY, MARGIN or CNC. BO is not a valid productType here.
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
            if tp > 10000 and len(str(sec_id)) >= 5:
                logger.error(f"ABNORMAL PRICE detected for Super Order: TGT={tp}. Likely Index spot passed to Option. REJECTING.")
                return {"success": False, "error": "Invalid Price: Index spot passed as Option price"}
        except (TypeError, ValueError) as e:
            logger.warning(f"Price validation skipped — could not cast target_price to float: {e}")

        # Round all prices to 0.05 tick size
        price = self._round_to_tick(price)
        target_price = self._round_to_tick(target_price)
        stop_loss_price = self._round_to_tick(stop_loss_price)
        trailing_jump = self._round_to_tick(trailing_jump) if trailing_jump else 1.0 # Mandatory 1.0 default if None
        
        payload = {
            "dhanClientId": self.client_id,
            "correlationId": str(f"b_{int(time.time())}"),
            "transactionType": txn_type,
            "exchangeSegment": exchange_segment,
            "productType": product_type,
            "orderType": order_type,
            "securityId": str(sec_id), # Spec shows string in example, but get_ltp required int. I'll test with str first as per doc.
            "quantity": int(final_qty),
            "price": float(price) if order_type == "LIMIT" else 0.0,
            "targetPrice": float(target_price),
            "stopLossPrice": float(stop_loss_price),
            "trailingJump": float(trailing_jump)
        }
        
        logger.info(f"$$$ [BROKER] PLACING SUPER ORDER: {payload} $$$")

        try:
            resp = requests.post(url, headers=headers, json=payload)
            if resp.status_code == 200:
                data = resp.json()
                # Super Order API v2 response might have orderId at top level or in 'data'
                order_id = data.get('orderId') or data.get('data', {}).get('orderId')
                status = data.get('orderStatus') or data.get('data', {}).get('orderStatus')
                if order_id:
                    return {"success": True, "order_id": order_id, "status": status}
                else:
                    return {"success": False, "error": f"No orderId in response: {resp.text}"}
            elif resp.status_code == 401:
                logger.warning("Super Order Placement: 401 Unauthorized. Syncing token...")
                if self._sync_token_from_redis():
                    headers['access-token'] = self.access_token # Retry once
                    resp = requests.post(url, headers=headers, json=payload)
                    if resp.status_code == 200:
                        data = resp.json()
                        order_id = data.get('orderId') or data.get('data', {}).get('orderId')
                        status = data.get('orderStatus') or data.get('data', {}).get('orderStatus')
                        return {"success": True, "order_id": order_id, "status": status}
                
                return {"success": False, "error": f"Auth failed after sync: {resp.text}"}
            elif resp.status_code == 500:
                logger.warning(f"Super Order: 500 Internal Server Error from Dhan. Retrying in 2s... | Body: {resp.text[:200]}")
                time.sleep(2)
                resp = requests.post(url, headers=headers, json=payload)
                if resp.status_code == 200:
                    data = resp.json()
                    order_id = data.get('orderId') or data.get('data', {}).get('orderId')
                    status = data.get('orderStatus') or data.get('data', {}).get('orderStatus')
                    if order_id:
                        logger.info(f"Super Order retry succeeded: {order_id}")
                        return {"success": True, "order_id": order_id, "status": status}
                logger.error(f"Super Order: Retry after 500 also failed: {resp.status_code} {resp.text}")
                return {"success": False, "error": f"Dhan 500 after retry: {resp.text}"}
            else:
                 logger.error(f"Super Order Failed: {resp.status_code} {resp.text}")
                 return {"success": False, "error": resp.text}
        except Exception as e:
            logger.error(f"Super Order Exception: {e}")
            return {"success": False, "error": str(e)}

    def modify_super_target_leg(self, order_id, target_price):
        """
        Modifies the Target Leg of a Super Order.
        """
        if self.dry_run:
            logger.info(f"$$$ [BROKER] MOCK MODIFY SUPER TARGET {order_id} -> {target_price} $$$")
            return {"success": True}

        if not self.access_token or not self.client_id:
            return {"success": False, "error": "Missing Info"}

        url = f"https://api.dhan.co/v2/super/orders/{order_id}"
        headers = {
            'Content-Type': 'application/json',
            'access-token': self.access_token
        }

        payload = {
            "dhanClientId": self.client_id,
            "orderId": str(order_id),
            "legName": "TARGET_LEG",
            "targetPrice": float(self._round_to_tick(target_price))
        }

        logger.info(f"$$$ [BROKER] MODIFYING SUPER TARGET LEG: {payload} $$$")

        try:
            resp = requests.put(url, headers=headers, json=payload)
            if resp.status_code == 200:
                return {"success": True, "data": resp.json()}
            elif resp.status_code == 401:
                logger.warning("Modify Super Target: 401 Unauthorized. Syncing token...")
                if self._sync_token_from_redis():
                    headers['access-token'] = self.access_token
                    resp = requests.put(url, headers=headers, json=payload)
                    if resp.status_code == 200:
                        return {"success": True, "data": resp.json()}
                return {"success": False, "error": f"Auth failed after sync: {resp.text}"}
            else:
                logger.error(f"Modify Super Target Failed: {resp.status_code} {resp.text}")
                return {"success": False, "error": resp.text}
        except Exception as e:
            logger.error(f"Modify Super Target Exception: {e}")
            return {"success": False, "error": str(e)}

    def modify_super_sl_leg(self, order_id, stop_loss_price, trailing_jump=1.0):
        """
        Modifies the Stop Loss Leg of a Super Order.
        """
        if self.dry_run:
            logger.info(f"$$$ [BROKER] MOCK MODIFY SUPER SL {order_id} ->SL:{stop_loss_price}, TJ:{trailing_jump} $$$")
            return {"success": True}

        if not self.access_token or not self.client_id:
            return {"success": False, "error": "Missing Info"}

        url = f"https://api.dhan.co/v2/super/orders/{order_id}"
        headers = {
            'Content-Type': 'application/json',
            'access-token': self.access_token
        }

        payload = {
            "dhanClientId": self.client_id,
            "orderId": str(order_id),
            "legName": "STOP_LOSS_LEG",
            "stopLossPrice": float(self._round_to_tick(stop_loss_price)),
            "trailingJump": float(self._round_to_tick(trailing_jump))
        }

        logger.info(f"$$$ [BROKER] MODIFYING SUPER SL LEG: {payload} $$$")

        try:
            resp = requests.put(url, headers=headers, json=payload)
            if resp.status_code == 200:
                return {"success": True, "data": resp.json()}
            elif resp.status_code == 401:
                logger.warning("Modify Super SL: 401 Unauthorized. Syncing token...")
                if self._sync_token_from_redis():
                    headers['access-token'] = self.access_token
                    resp = requests.put(url, headers=headers, json=payload)
                    if resp.status_code == 200:
                        return {"success": True, "data": resp.json()}
                return {"success": False, "error": f"Auth failed after sync: {resp.text}"}
            else:
                logger.error(f"Modify Super SL Failed: {resp.status_code} {resp.text}")
                return {"success": False, "error": resp.text}
        except Exception as e:
            logger.error(f"Modify Super SL Exception: {e}")
            return {"success": False, "error": str(e)}

    def modify_super_entry_leg(self, order_id, price, quantity=None):
        """
        Modifies the Entry Leg of a Super Order.
        """
        if self.dry_run:
            logger.info(f"$$$ [BROKER] MOCK MODIFY SUPER ENTRY {order_id} -> P:{price}, Q:{quantity} $$$")
            return {"success": True}

        if not self.access_token or not self.client_id:
            return {"success": False, "error": "Missing Info"}

        url = f"https://api.dhan.co/v2/super/orders/{order_id}"
        headers = {
            'Content-Type': 'application/json',
            'access-token': self.access_token
        }

        # Round price to 0.05
        rounded_price = float(self._round_to_tick(price))

        payload = {
            "dhanClientId": self.client_id,
            "orderId": str(order_id),
            "legName": "ENTRY_LEG",
            "price": rounded_price,
            "quantity": int(quantity) if quantity else None
        }
        # Remove None quantity
        if payload["quantity"] is None:
            del payload["quantity"]

        logger.info(f"$$$ [BROKER] MODIFYING SUPER ENTRY LEG: {payload} $$$")

        try:
            resp = requests.put(url, headers=headers, json=payload)
            if resp.status_code == 200:
                return {"success": True, "data": resp.json()}
            elif resp.status_code == 401:
                logger.warning("Modify Super Entry: 401 Unauthorized. Syncing token...")
                if self._sync_token_from_redis():
                    headers['access-token'] = self.access_token
                    resp = requests.put(url, headers=headers, json=payload)
                    if resp.status_code == 200:
                        return {"success": True, "data": resp.json()}
                return {"success": False, "error": f"Auth failed after sync: {resp.text}"}
            else:
                logger.error(f"Modify Super Entry Failed: {resp.status_code} {resp.text}")
                return {"success": False, "error": resp.text}
        except Exception as e:
            logger.error(f"Modify Super Entry Exception: {e}")
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
            elif resp.status_code == 401:
                logger.warning("Cancel Super Order: 401 Unauthorized. Syncing token...")
                if self._sync_token_from_redis():
                    headers['access-token'] = self.access_token
                    resp = requests.delete(url, headers=headers)
                    if resp.status_code in [200, 202]:
                        return {"success": True, "data": resp.json() if resp.text else {}}
                return {"success": False, "error": f"Auth failed after sync: {resp.text}"}
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

    def _sync_token_from_redis(self):
        """
        Checks Redis for a potentially newer token and refreshes the client if found.
        Used to recover from 401 errors if another process updated the token.
        """
        if not self.r:
            return False
            
        try:
            latest_token = self.r.get("dhan_access_token")
            if latest_token and latest_token != self.access_token:
                logger.info("🔄 Newer token found in Redis. Syncing...")
                return self.refresh_client(latest_token)
        except Exception as e:
            logger.error(f"Failed to sync token from Redis: {e}")
        return False

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
