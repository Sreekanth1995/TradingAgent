import os
import logging
import json
import time
from datetime import datetime
import pytz

IST = pytz.timezone('Asia/Kolkata')

try:
    import redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False

logger = logging.getLogger(__name__)

class RankingEngine:
    """
    Direct Signal Trading Engine.
    Handles BUY/SELL signals to manage simulated bracket orders (Entry + SL + Target).
    """
    def __init__(self, broker):
        self.broker = broker
        self.use_redis = False
        self.memory_store = {}
        
        # Configuration
        self.points_target = 30
        self.points_sl = 20

        if REDIS_AVAILABLE:
            redis_url = os.getenv("REDIS_URL")
            try:
                if redis_url:
                    self.r = redis.from_url(redis_url, decode_responses=True)
                else:
                    redis_host = os.getenv("REDIS_HOST", "localhost")
                    redis_port = int(os.getenv("REDIS_PORT", 6379))
                    self.r = redis.Redis(host=redis_host, port=redis_port, decode_responses=True)
                
                self.r.ping()
                logger.info("✅ RankingEngine: Connected to Redis successfully")
                self.use_redis = True
            except Exception as e:
                logger.warning(f"RankingEngine: Redis connection failed ({e}). Using in-memory storage.")
        else:
            logger.warning("RankingEngine: Redis library not installed. Using in-memory storage.")

    # --- State Management ---
    def _get_state(self, underlying):
        """Returns dict: { 'side': 'CALL'/'PUT'/'NONE', 'entry_id': ..., 'sl_id': ..., 'tgt_id': ..., 'symbol': ... }"""
        key = f"state:{underlying}"
        if self.use_redis:
            val = self.r.get(key)
            return json.loads(val) if val else {'side': 'NONE'}
        else:
            return self.memory_store.get(key, {'side': 'NONE'})

    def _set_state(self, underlying, state):
        key = f"state:{underlying}"
        if self.use_redis:
            self.r.set(key, json.dumps(state))
        else:
            self.memory_store[key] = state

    def _clear_state(self, underlying):
        self._set_state(underlying, {'side': 'NONE'})

    # --- Core Logic ---
    def process_signal(self, underlying, signal_type, timeframe, leg_data):
        """
        Process BUY/SELL signals.
        signal_type: 'B' (Buy/Long), 'S' (Sell/Short)
        """
        now_ist = datetime.now(IST)
        
        # 0. Check for Daily Reset (if needed, or just let signals drive)
        # Assuming explicit signals, we don't auto-reset unless manual.

        state = self._get_state(underlying)
        current_side = state.get('side', 'NONE')
        
        logger.info(f"Processing Signal: {signal_type} for {underlying}. Current Side: {current_side}")
        
        action_log = []

        # Logic Matrix
        # Signal: BUY ('B')
        if signal_type == 'B':
            # 1. Close PUT if Open
            if current_side == 'PUT':
                logger.info(f"Reversal detected: Closing PUT for {underlying}")
                self._close_position(underlying, state)
                state = {'side': 'NONE'} # Reset local state after close
                action_log.append("CLOSED_PUT")

            # 2. Open CALL if not already open
            if current_side != 'CALL':
                logger.info(f"Opening CALL for {underlying}")
                new_state = self._open_position(underlying, 'CALL', leg_data)
                if new_state:
                    self._set_state(underlying, new_state)
                    action_log.append("OPENED_CALL")
                else:
                    action_log.append("FAILED_OPEN_CALL")

        # Signal: SELL ('S')
        elif signal_type == 'S':
            # 1. Close CALL if Open
            if current_side == 'CALL':
                logger.info(f"Reversal detected: Closing CALL for {underlying}")
                self._close_position(underlying, state)
                state = {'side': 'NONE'}
                action_log.append("CLOSED_CALL")

            # 2. Open PUT if not already open
            if current_side != 'PUT':
                logger.info(f"Opening PUT for {underlying}")
                new_state = self._open_position(underlying, 'PUT', leg_data)
                if new_state:
                    self._set_state(underlying, new_state)
                    action_log.append("OPENED_PUT")
                else:
                    action_log.append("FAILED_OPEN_PUT")
        
        # Summarize Action for Server Compatibility
        summary_action = "NO_ACTION"
        if action_log:
            summary_action = ", ".join(action_log)
        
        return {
            "underlying": underlying,
            "signal": signal_type,
            "actions": action_log,
            "action": summary_action, # For server.py error checking
            "time": now_ist.strftime('%H:%M:%S')
        }

    def _open_position(self, underlying, side, leg_data):
        """
        Opens a position and places simulated bracket orders.
        Returns new state dict or None on failure.
        """
        # 1. Select ITM Contract
        spot = leg_data.get('current_price', 0)
        opt_type = 'CE' if side == 'CALL' else 'PE'
        
        itm = self.broker.get_itm_contract(underlying, opt_type, spot)
        if not itm:
            logger.error(f"Failed to resolve ITM for {underlying} {side}")
            return None
        
        symbol = itm['symbol']
        sec_id = itm['security_id']
        
        # --- Native Super Order Attempt ---
        # 1. Fetch LTP for Reference
        ltp = self.broker.get_ltp(sec_id)
        if not ltp or ltp <= 0:
            logger.warning(f"LTP fetch failed for {symbol}. Cannot place Super Order. Falling back to Simulation.")
            # DO NOT use current_price as fallback - it's the Index spot price, not Option LTP!
            # Skip to fallback simulation instead.
            ltp = None

        if ltp and ltp > 0:
            sl_price = round(ltp - self.points_sl, 1)
            tgt_price = round(ltp + self.points_target, 1)
            if sl_price <= 0: sl_price = 0.05
            
            # Smart Entry: Limit Order at LTP - 5
            entry_limit_price = round(ltp - 5, 1)
            if entry_limit_price <= 0.05: entry_limit_price = 0.05 # Safety

            so_leg = itm.copy()
            so_leg['quantity'] = leg_data.get('quantity', 1)
            so_leg['target_price'] = tgt_price
            so_leg['stop_loss_price'] = sl_price
            
            # Use Limit Order for Entry
            so_leg['order_type'] = 'LIMIT'
            so_leg['price'] = entry_limit_price
            
            logger.info(f"Attempting Native Super Order for {symbol}. EntryLimit={entry_limit_price} (LTP-5), SL={sl_price}, TGT={tgt_price}")
            resp = self.broker.place_super_order(symbol, so_leg)
            
            if resp.get('success'):
                logger.info(f"Native Super Order Placed: {resp.get('order_id')}")
                return {
                    'side': side,
                    'entry_id': resp.get('order_id'),
                    'symbol': symbol,
                    'security_id': sec_id,
                    'sl_id': "NATIVE_BO", 
                    'tgt_id': "NATIVE_BO",
                    'is_super_order': True,
                    'quantity': so_leg['quantity']
                }
            else:
                logger.warning(f"Native Super Order Failed: {resp.get('error')}. Falling back to Simulation.")

        # --- Fallback: Simulated Bracket (Market Entry + Separate Exit Orders) ---
        logger.info(f"Placing Market Entry (Simulated Bracket) for {symbol}")
        order_leg = itm.copy()
        
        # ... (rest of old code below) ... 
        order_leg['quantity'] = leg_data.get('quantity', 1)
        
        resp = self.broker.place_buy_order(symbol, order_leg)
        if not resp.get('success'):
            logger.error(f"Entry Failed: {resp.get('error')}")
            return None
        
        entry_id = resp['order_id']
        
        # 3. Wait for Fill (Polling) to get Avg Price
        avg_price = 0.0
        max_retries = 5  # 2.5 seconds max wait
        for i in range(max_retries):
            status = self.broker.get_order_status(entry_id)
            if status:
                st = status.get('orderStatus') # Dhan Status keys e.g. 'TRADED', 'PENDING'
                # Note: Dhan API keys might vary (camelCase vs snake_case). Using .get loosely.
                # Assuming 'status' field in 'data' or similar. 
                # Our mock wrapper returns the raw data dict from 'get_order_by_id'.
                # Usually: 'orderStatus': 'TRADED'
                if st == 'TRADED' or st == 'FILLED':
                    avg_price = float(status.get('averagePrice', 0.0) or status.get('price', 0.0))
                    if avg_price > 0:
                        break
            time.sleep(0.5)
            
        if avg_price <= 0:
            logger.warning(f"Could not fetch fill price for {entry_id} in time. Using Spot/Mock? Skipping SL/Target placement to avoid bad orders.")
            # Critical: If we can't get price, we can't place safe limits.
            # We record the position but mark orders as missing.
            return {
                'side': side,
                'entry_id': entry_id,
                'symbol': symbol,
                'security_id': sec_id,
                'sl_id': None,
                'tgt_id': None
            }
        
        logger.info(f"Entry Filled at {avg_price}. Placing Bracket Orders...")
        
        # 4. Calculate Levels
        sl_price = round(avg_price - self.points_sl, 1)
        tgt_price = round(avg_price + self.points_target, 1)
        
        if sl_price <= 0: sl_price = 0.05
        
        # 5. Place Target (Limit Sell)
        tgt_leg = order_leg.copy()
        tgt_leg['price'] = tgt_price
        tgt_leg['order_type'] = "LIMIT"
        
        logger.info(f"Placing Target Limit Sell at {tgt_price}")
        resp_tgt = self.broker.place_sell_order(symbol, tgt_leg)
        tgt_id = resp_tgt.get('order_id')
        if not resp_tgt.get('success'):
            logger.error(f"Target Placement Failed: {resp_tgt.get('error')}")

        # 6. Place Stop Loss (SL-M)
        sl_leg = order_leg.copy()
        sl_leg['trigger_price'] = sl_price
        sl_leg['order_type'] = "STOP_LOSS_MARKET" 
        # Note: Dhan uses STOP_LOSS_MARKET for SL-M. 
        
        logger.info(f"Placing Stop Loss Trigger at {sl_price}")
        resp_sl = self.broker.place_sell_order(symbol, sl_leg)
        sl_id = resp_sl.get('order_id')
        if not resp_sl.get('success'):
            logger.error(f"SL Placement Failed: {resp_sl.get('error')}")
        
        return {
            'side': side,
            'entry_id': entry_id,
            'symbol': symbol,
            'security_id': sec_id,
            'sl_id': sl_id, 
            'tgt_id': tgt_id,
            'sl_price': sl_price,
            'tgt_price': tgt_price,
            'quantity': order_leg['quantity']
        }

    def _close_position(self, underlying, state):
        """
        Closes current position and cancels pending SL/Target orders.
        """
        symbol = state.get('symbol')
        sec_id = state.get('security_id')
        entry_id = state.get('entry_id')
        sl_id = state.get('sl_id')
        tgt_id = state.get('tgt_id')
        is_super_order = state.get('is_super_order', False)
        side = state.get('side')
        
        if not symbol or not sec_id:
            return

        # 1. Cancel Pending Orders
        # Smart Exit Strategy:
        # Instead of Canceling + Market Exit, we Modify pending Target/SL orders to capture spread.
        
        ltp = self.broker.get_ltp(sec_id)
        if not ltp or ltp <= 0:
            logger.warning(f"Smart Exit Failed: Could not fetch LTP for {symbol}. Proceeding with Standard Exit.")
            # Fallback to Old Logic: Cancel All + Market Close
            pending_orders = self.broker.get_pending_orders(sec_id)
            for order in pending_orders:
                 self.broker.cancel_order(order.get('orderId'))
            
            # Place Market Exit
            exit_leg = { "symbol": symbol, "security_id": sec_id, "quantity": state.get('quantity', 1) }
            self.broker.place_sell_order(symbol, exit_leg)
            self._clear_state(underlying)
            return

        # Fetch Pending Legs
        pending_orders = self.broker.get_pending_orders(sec_id)
        if not pending_orders:
             logger.warning(f"Smart Exit: No pending orders found for {symbol}. Checking Position.")
             # If no pending orders, maybe we are already flat? Check Pos using old logic.
             # Or just Place Market Exit to be safe?
             # Let's use standard verification below.
        else:
            logger.info(f"Smart Exit: Modifying {len(pending_orders)} pending orders for {symbol} at LTP {ltp}")
            
            for order in pending_orders:
                oid = order.get('orderId')
                otype = order.get('orderType') # LIMIT / STOP_LOSS
                txn = order.get('transactionType') 
                curr_price = float(order.get('price', 0))
                curr_trigger = float(order.get('triggerPrice', 0))
                
                # Determine Position Side we are closing
                # If we were Long (Call), we are Selling.
                # If we were Short (Put), we are Buying. (Assuming we Short Options? No, we Buy Options).
                # Strategy is Buy Call / Buy Put. So we always SELL to close.
                
                # Consolidated Logic:
                # 1. If it's a BUY order (Unfilled Start of Native BO), we MUST CANCEL it.
                #    Otherwise we leave a stale entry order.
                if txn == 'BUY':
                    logger.info(f"Smart Exit: Found Unfilled BUY Entry {oid}. Cancelling.")
                    self.broker.cancel_order(oid)
                
                # 2. If it's a SELL order (Target/SL legs of a filled order), we MODIFY it (Smart Exit).
                elif txn == 'SELL':
                    if otype == 'LIMIT': # TARGET (Sell Limit)
                        new_price = round(ltp + 5, 1)
                        logger.info(f"Smart Exit: Modifying Target {oid} to {new_price} (LTP+5)")
                        self.broker.modify_order(oid, 'LIMIT', {'price': new_price})
                    
                    elif otype in ['STOP_LOSS', 'STOP_LOSS_MARKET']: # SL
                        # Trail UP if needed
                        barrier = round(ltp - 10, 1)
                        if getattr(self, 'trailing_sl_enabled', True): 
                             if curr_trigger < barrier:
                                 logger.info(f"Smart Exit: Trailing SL {oid} to {barrier} (LTP-10)")
                                 self.broker.modify_order(oid, 'SL', {'trigger_price': barrier})

        # Do NOT place Market Exit Order.
        # We rely on the Modified Limit Order to fill.
        # But we DO clear the state because we are "done" with this position from Engine perspective?
        # NO. If we clear state, we lose track of it.
        # But Engine needs to open NEW position immediately.
        # Strategy: "Open position will be closed... by Signal".
        # We modify old orders. Open new one.
        # Old position becomes "Legacy" managed by Broker orders.
        # We can clear state because we don't need to track it anymore active-ly.
        
        logger.info(f"Smart Exit Initiated. Pending Orders Modified. Clearing State for {underlying}.")
        self._clear_state(underlying)

    def manual_exit_all(self):
        """
        Emergency: Close all keys starting with state:*
        """
        logger.warning("MANUAL EXIT ALL TRIGGERED")
        keys = []
        if self.use_redis:
            keys = self.r.keys("state:*")
        else:
            keys = [k for k in self.memory_store.keys() if k.startswith("state:")]
            
        for k in keys:
            underlying = k.split(":")[1]
            state = self._get_state(underlying)
            self._close_position(underlying, state)
