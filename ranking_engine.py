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

# Market Hours Configuration (IST)
MARKET_OPEN_HOUR = 9
MARKET_OPEN_MINUTE = 15
MARKET_VOLATILITY_DELAY_MINS = 10

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
        
        # Instrument Configurations (Target, SL, Trailing Jump)
        self.configs = {
            "NIFTY": {"target": 75, "sl": 20, "trailing": 15},
            "BANKNIFTY": {"target": 75, "sl": 20, "trailing": 15},
            "FINNIFTY": {"target": 75, "sl": 20, "trailing": 15},
            "DEFAULT": {"target": 75, "sl": 20, "trailing": 15}
        }
        
        # Scalping Mode Configuration (Target 20%, SL 20%, Trailing 5%)
        self.scalping_configs = {
            "target": 75,
            "sl": 20,
            "trailing": 5
        }
        
        self.processing_locks = set()

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
            return json.loads(val) if val else {'side': 'NONE', 'last_signal': 'NONE'}
        else:
            return self.memory_store.get(key, {'side': 'NONE', 'last_signal': 'NONE'})

    def _set_state(self, underlying, state):
        key = f"state:{underlying}"
        if self.use_redis:
            self.r.set(key, json.dumps(state))
        else:
            self.memory_store[key] = state

    def _clear_state(self, underlying):
        self._set_state(underlying, {'side': 'NONE'})

    def _get_params(self, underlying, is_scalping=False):
        """Returns the configuration for the given underlying."""
        if is_scalping:
            return self.scalping_configs
        return self.configs.get(underlying.upper(), self.configs["DEFAULT"])

    def activate_scalping_mode(self, duration_mins=5):
        """
        Activates scalping mode for a specific duration.
        """
        expiry = int(time.time()) + (duration_mins * 60)
        if self.use_redis:
            self.r.set("scalping_until", expiry)
        else:
            self.memory_store["scalping_until"] = expiry
        logger.info(f"🚀 Scalping Mode ACTIVATED for {duration_mins} minutes (until {datetime.fromtimestamp(expiry).strftime('%H:%M:%S')})")
        return True

    def _is_scalping_active(self, underlying=None):
        """
        Checks if scalping mode is currently active or eligible.
        Priority:
        1. Volume Trigger (Bypasses Window/Expiry)
        2. Standard Rules (Inside Window AND on Expiry Day)
        """
        # 1. Volume Trigger Check (Always Priority)
        if self.use_redis:
            val = self.r.get("scalping_until")
        else:
            val = self.memory_store.get("scalping_until")
        
        if val and int(val) > time.time():
            return True
        
        # 2. Standard Window/Expiry Rules
        if underlying:
            now_ist = datetime.now(IST)
            h, m = now_ist.hour, now_ist.minute
            in_window1 = (h == 9 and m >= 20) or (h == 10 and m <= 35)
            in_window2 = (h == 14 and m >= 45) or (h == 15 and m <= 30)
            
            if (in_window1 or in_window2) and self.broker.is_expiry_day(underlying):
                return True
                
        return False

    # --- Core Logic ---
    def process_signal(self, underlying, signal_type, timeframe, leg_data):
        """
        Process BUY/SELL signals.
        signal_type: 'B' (Buy/Long), 'S' (Sell/Short)
        timeframe: 1 or 5
        """
        now_ist = datetime.now(IST)
        
        # --- Timeframe Segregation & Mode Logic ---
        timeframe = int(timeframe)
        is_scalping = False
        
        if timeframe == 1:
            # --- Scalping Mode Logic ---
            if self._is_scalping_active(underlying):
                is_scalping = True
                logger.info(f"⚡ SCALPING MODE ACTIVE for {underlying} (1m signal)")
            else:
                logger.info(f"Scalping Mode: Ignoring 1m signal for {underlying} (Conditions not met).")
                return {"underlying": underlying, "action": "SKIPPED_SCALPING_INACTIVE", "time": now_ist.strftime('%H:%M:%S')}

        elif timeframe == 5:
            if self._is_scalping_active(underlying):
                logger.info(f"Scalping Mode: Ignoring 5m signal for {underlying} (Scalping mode IS active).")
                return {"underlying": underlying, "action": "SKIPPED_SCALPING_ACTIVE", "time": now_ist.strftime('%H:%M:%S')}
            logger.info(f"Standard Mode processing for {underlying} (5m signal)")
        else:
            logger.warning(f"Unknown timeframe {timeframe} for {underlying}. Defaulting to Standard Mode logic.")

        state = self._get_state(underlying)
        current_side = state.get('side', 'NONE')
        last_signal = state.get('last_signal', 'NONE')
        
        # Deduplication Check
        if signal_type == last_signal:
            logger.info(f"Deduplication: Ignoring consecutive {signal_type} signal for {underlying}")
            return {
                "underlying": underlying,
                "signal": signal_type,
                "action": "SKIPPED_DUPLICATE",
                "time": now_ist.strftime('%H:%M:%S')
            }

        # 0.1 Check for Market Volatility Delay (Normal Mode only?)
        # User specified "Scalping mode should be between 9:20AM...", 
        # Volatility delay ends at 09:25.
        # Let's keep it for Normal Mode (5m).
        if not is_scalping:
            market_start = now_ist.replace(hour=MARKET_OPEN_HOUR, minute=MARKET_OPEN_MINUTE, second=0, microsecond=0)
            delay_end = market_start.replace(minute=MARKET_OPEN_MINUTE + MARKET_VOLATILITY_DELAY_MINS)
            if market_start <= now_ist < delay_end:
                logger.info(f"Market Volatility Delay: Ignoring {signal_type} signal for {underlying} during first {MARKET_VOLATILITY_DELAY_MINS} mins.")
                return {"underlying": underlying, "action": "SKIPPED_MARKET_OPEN_DELAY", "time": now_ist.strftime('%H:%M:%S')}

        if underlying in self.processing_locks:
            logger.warning(f"Execution Lock: Signal for {underlying} is already being processed. Skipping.")
            return {"underlying": underlying, "action": "SKIPPED_LOCKED", "time": now_ist.strftime('%H:%M:%S')}
        
        self.processing_locks.add(underlying)
        try:
            result = self._execute_signal(underlying, signal_type, timeframe, leg_data, state, current_side, now_ist, is_scalping)
            
            # Update last_signal ONLY if execution was successful or it was already open
            # Conditions for committing signal:
            # - Reversal succeeded (CLOSED_X, OPENED_Y)
            # - New position opened (OPENED_X)
            # - Position already matches signal (NO_ACTION) - though Duplication handles this earlier
            
            actions = result.get('actions', [])
            success_indicators = ['OPENED_CALL', 'OPENED_PUT', 'CLOSED_CALL', 'CLOSED_PUT']
            
            # If we attempted an open and failed, do NOT update last_signal
            if any(a in actions for a in success_indicators) or not actions:
                new_state = self._get_state(underlying)
                new_state['last_signal'] = signal_type
                self._set_state(underlying, new_state)
                logger.debug(f"State Updated: last_signal={signal_type} for {underlying}")
            else:
                logger.warning(f"Execution failed for {underlying}. last_signal NOT updated. Will allow retry.")
                
            return result
        finally:
            self.processing_locks.remove(underlying)

    def _execute_signal(self, underlying, signal_type, timeframe, leg_data, state, current_side, now_ist, is_scalping=False):
        action_log = []

        # Logic Matrix
        # Signal: BUY ('B')
        if signal_type == 'B':
            # 1. Close PUT if Open
            if current_side == 'PUT':
                logger.info(f"Reversal detected: Closing PUT for {underlying}")
                self._close_position(underlying, state)
                state = {'side': 'NONE'} 
                action_log.append("CLOSED_PUT")

            # 2. Open CALL if not already open
            if current_side != 'CALL':
                logger.info(f"Opening CALL for {underlying} ({'Scalping' if is_scalping else 'Normal'})")
                new_state = self._open_position(underlying, 'CALL', leg_data, is_scalping)
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
                logger.info(f"Opening PUT for {underlying} ({'Scalping' if is_scalping else 'Normal'})")
                new_state = self._open_position(underlying, 'PUT', leg_data, is_scalping)
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

    def _open_position(self, underlying, side, leg_data, is_scalping=False):
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
        ltp = None
        for attempt in range(3):
            ltp = self.broker.get_ltp(sec_id)
            if ltp and ltp > 0:
                break
            logger.warning(f"LTP fetch attempt {attempt+1} failed for {symbol}. Retrying...")
            time.sleep(1)

        if not ltp or ltp <= 0:
            logger.warning(f"LTP fetch failed for {symbol} after retries. Cannot place Super Order. Falling back to Simulation.")
            ltp = None

        if ltp and ltp > 0:
            params = self._get_params(underlying, is_scalping)
            # Calculate levels using percentages
            sl_price = round(ltp * (1 - params['sl']/100), 1)
            tgt_price = round(ltp * (1 + params['target']/100), 1)
            trailing_val = round(ltp * (params['trailing']/100), 1)
            
            if sl_price <= 0: sl_price = 0.05
            if trailing_val <= 0: trailing_val = 1.0 # Minimum 1 tick jump
            
            # Smart Entry: Limit Order at LTP - 5
            entry_limit_price = round(ltp - 5, 1)
            if entry_limit_price <= 0.05: entry_limit_price = 0.05 # Safety

            so_leg = itm.copy()
            so_leg['quantity'] = leg_data.get('quantity', 1)
            so_leg['target_price'] = tgt_price
            so_leg['stop_loss_price'] = sl_price
            so_leg['trailing_jump'] = trailing_val
            is_scalping_flag = is_scalping # To store in state
            
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
                    'is_scalping': is_scalping,
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
            try:
                status = self.broker.get_order_status(entry_id)
                if status and isinstance(status, dict):
                    st = status.get('orderStatus') 
                    if st in ['TRADED', 'FILLED']:
                        avg_price = float(status.get('averagePrice', 0.0) or status.get('price', 0.0))
                        if avg_price > 0:
                            break
                elif status:
                    logger.warning(f"Unexpected status format for {entry_id}: {status}")
            except Exception as e:
                logger.error(f"Error polling order status for {entry_id}: {e}")
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
        
        # 4. Calculate Levels using percentages
        params = self._get_params(underlying, is_scalping)
        sl_price = round(avg_price * (1 - params['sl']/100), 1)
        tgt_price = round(avg_price * (1 + params['target']/100), 1)
        
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
            'is_scalping': is_scalping,
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
             # Fallback: Check if there is an actual open position that needs closing
             positions = self.broker.get_positions()
             has_position = False
             for pos in positions:
                 # Dhan positions use securityId (str)
                 if str(pos.get('securityId')) == str(sec_id):
                     net_qty = int(pos.get('netQty', 0))
                     if net_qty != 0:
                         logger.info(f"Smart Exit: Found open position for {symbol} (Qty: {net_qty}). Placing Market Exit.")
                         exit_leg = { 
                             "symbol": symbol, 
                             "security_id": sec_id, 
                             "quantity": abs(net_qty),
                             "order_type": "MARKET"
                         }
                         self.broker.place_sell_order(symbol, exit_leg)
                         has_position = True
                         break
             
             if not has_position:
                 logger.info(f"Smart Exit: No active position found for {symbol} after checking. State cleared.")
        else:
            logger.info(f"Smart Exit: Modifying {len(pending_orders)} pending orders for {symbol} at LTP {ltp}")
            
            # Use Parent ID for Super Orders if available
            parent_id = state.get('entry_id')

            for order in pending_orders:
                oid = order.get('orderId')
                # Dhan API might use orderType or order_type
                otype = order.get('orderType') or order.get('order_type')
                txn = order.get('transactionType') or order.get('transaction_type')
                
                # 1. If it's a BUY order (Unfilled Start), we MUST CANCEL it.
                if txn == 'BUY':
                    logger.info(f"Smart Exit: Found Unfilled BUY Entry {oid}. Cancelling.")
                    if is_super_order and parent_id:
                        self.broker.cancel_super_order(parent_id, 'ENTRY_LEG')
                    else:
                        self.broker.cancel_order(oid)
                
                # 2. If it's a SELL order (Target/SL legs), we MODIFY it (Smart Exit).
                elif txn == 'SELL':
                    if is_super_order and parent_id:
                        # SUPER ORDER SMART EXIT logic:
                        # Leg modification according to Dhan API v2 requires explicit targeting of legs.
                        if otype == 'LIMIT': # TARGET (Sell Limit)
                            new_target = round(ltp + 5, 1)
                            logger.info(f"Smart Exit SuperOrder: Modifying TARGET_LEG for {parent_id} to {new_target} (LTP+5)")
                            self.broker.modify_super_order(parent_id, 'TARGET_LEG', {'target_price': new_target})
                        
                        elif otype in ['STOP_LOSS', 'STOP_LOSS_MARKET']: # SL
                            new_sl = round(ltp - 5, 1)
                            if new_sl <= 0.05: new_sl = 0.05
                            logger.info(f"Smart Exit SuperOrder: Modifying STOP_LOSS_LEG for {parent_id} to {new_sl} (LTP-5)")
                            # Note: We bypass normal trailing logic here as per User Request for Smart Exit Target/SL values.
                            self.broker.modify_super_order(parent_id, 'STOP_LOSS_LEG', {'stop_loss_price': new_sl})
                    
                    else:
                        # STANDARD BRACKET SMART EXIT
                        if otype == 'LIMIT': # TARGET (Sell Limit)
                            new_price = round(ltp + 5, 1)
                            logger.info(f"Smart Exit: Modifying Target {oid} to {new_price} (LTP+5)")
                            self.broker.modify_order(oid, 'LIMIT', {'price': new_price})
                        
                        elif otype in ['STOP_LOSS', 'STOP_LOSS_MARKET']: # SL
                            # Trail UP if needed
                            is_scalping = state.get('is_scalping', False)
                            params = self._get_params(underlying, is_scalping)
                            trail_percent = params['trailing']
                            trail_offset = round(ltp * (trail_percent/100), 1)
                            barrier = round(ltp - trail_offset, 1)
                            if getattr(self, 'trailing_sl_enabled', True):
                                # Dhan API might use triggerPrice or trigger_price
                                curr_trigger = float(order.get('triggerPrice') or order.get('trigger_price') or 0)
                                if curr_trigger < barrier:
                                    logger.info(f"Smart Exit: Trailing SL {oid} to {barrier} (offset {trail_offset})")
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
