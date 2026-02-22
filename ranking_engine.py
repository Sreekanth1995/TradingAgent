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
        """
        Initializes the RankingEngine with a broker and state storage.
        
        Args:
            broker: The broker client instance (e.g., DhanClient).
        """
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
        
        # Scalping Mode Configuration (Target 75%, SL 20%, Trailing 5%)
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
        
        Args:
            underlying (str): The underlying instrument symbol (e.g., NIFTY).
            
        Returns:
            bool: True if scalping mode should be used.
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

    def _validate_signal_timeframe(self, underlying, timeframe, now_ist):
        """
        Validates signal timeframe against current market mode (Scalping vs Standard).
        
        Args:
            underlying (str): The underlying symbol.
            timeframe (int): 1 or 5.
            now_ist (datetime): Current IST time.
            
        Returns:
            tuple: (is_valid, is_scalping, error_response)
        """
        is_scalping = self._is_scalping_active(underlying)
        
        if timeframe == 1:
            if not is_scalping:
                logger.info(f"Scalping Mode: Ignoring 1m signal for {underlying} (Conditions not met).")
                return False, False, {"underlying": underlying, "action": "SKIPPED_SCALPING_INACTIVE", "time": now_ist.strftime('%H:%M:%S')}
            logger.info(f"⚡ SCALPING MODE ACTIVE for {underlying} (1m signal)")
            return True, True, None

        elif timeframe == 5:
            if is_scalping:
                logger.info(f"Scalping Mode: Ignoring 5m signal for {underlying} (Scalping mode IS active).")
                return False, True, {"underlying": underlying, "action": "SKIPPED_SCALPING_ACTIVE", "time": now_ist.strftime('%H:%M:%S')}
            logger.info(f"Standard Mode processing for {underlying} (5m signal)")
            return True, False, None

        logger.warning(f"Unknown timeframe {timeframe} for {underlying}. Defaulting to Standard Mode logic.")
        return True, False, None

    def _validate_market_volatility(self, underlying, is_scalping, now_ist):
        """
        Checks if the signal should be skipped due to initial market volatility.
        
        Args:
            underlying (str): The underlying symbol.
            is_scalping (bool): Whether we are in scalping mode.
            now_ist (datetime): Current IST time.
            
        Returns:
            tuple: (is_valid, error_response)
        """
        if not is_scalping:
            market_start = now_ist.replace(hour=MARKET_OPEN_HOUR, minute=MARKET_OPEN_MINUTE, second=0, microsecond=0)
            delay_end = market_start.replace(minute=MARKET_OPEN_MINUTE + MARKET_VOLATILITY_DELAY_MINS)
            if market_start <= now_ist < delay_end:
                logger.info(f"Market Volatility Delay: Ignoring signal for {underlying} during first {MARKET_VOLATILITY_DELAY_MINS} mins.")
                return False, {"underlying": underlying, "action": "SKIPPED_MARKET_OPEN_DELAY", "time": now_ist.strftime('%H:%M:%S')}
        return True, None

    # --- Core Logic ---
    def process_signal(self, underlying, signal_type, timeframe, leg_data):
        """
        Main entry point for processing BUY/SELL signals.
        Coordinates validation, locking, and execution.
        """
        now_ist = datetime.now(IST)
        timeframe = int(timeframe)

        # 1. Timeframe & Mode Validation
        is_valid_tf, is_scalping, err_tf = self._validate_signal_timeframe(underlying, timeframe, now_ist)
        if not is_valid_tf:
            return err_tf

        # 2. Deduplication Check
        state = self._get_state(underlying)
        if signal_type == state.get('last_signal', 'NONE'):
            logger.info(f"Deduplication: Ignoring consecutive {signal_type} signal for {underlying}")
            return {"underlying": underlying, "signal": signal_type, "action": "SKIPPED_DUPLICATE", "time": now_ist.strftime('%H:%M:%S')}

        # 3. Market Volatility Check
        is_valid_vol, err_vol = self._validate_market_volatility(underlying, is_scalping, now_ist)
        if not is_valid_vol:
            return err_vol

        # 4. Locking & Execution
        if underlying in self.processing_locks:
            logger.warning(f"Execution Lock: Signal for {underlying} is already being processed. Skipping.")
            return {"underlying": underlying, "action": "SKIPPED_LOCKED", "time": now_ist.strftime('%H:%M:%S')}
        
        self.processing_locks.add(underlying)
        try:
            current_side = state.get('side', 'NONE')
            result = self._execute_signal(underlying, signal_type, timeframe, leg_data, state, current_side, now_ist, is_scalping)
            
            # 5. Commit state only on successful outcomes
            self._finalize_signal_state(underlying, result, signal_type)
            return result
        finally:
            self.processing_locks.remove(underlying)

    def _finalize_signal_state(self, underlying, result, signal_type):
        """
        Updates the engine state with the last processed signal if execution succeeded.
        """
        actions = result.get('actions', [])
        success_indicators = ['OPENED_CALL', 'OPENED_PUT', 'CLOSED_CALL', 'CLOSED_PUT']
        
        if any(a in actions for a in success_indicators) or not actions:
            new_state = self._get_state(underlying)
            new_state['last_signal'] = signal_type
            self._set_state(underlying, new_state)
            logger.debug(f"State Updated: last_signal={signal_type} for {underlying}")
        else:
            logger.warning(f"Execution failed for {underlying}. last_signal NOT updated.")



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
        Main orchestrator for opening a new position.
        
        Args:
            underlying (str): The underlying symbol.
            side (str): 'CALL' or 'PUT'.
            leg_data (dict): Signal payload data.
            is_scalping (bool): Scalping mode flag.
            
        Returns:
            dict: New state dictionary or None on failure.
        """
        # 1. Resolve Instrument
        itm = self._resolve_entry_instrument(underlying, side, leg_data)
        if not itm:
            return None
        
        symbol = itm['symbol']
        sec_id = itm['security_id']
        params = self._get_params(underlying, is_scalping)
        
        # 2. Try Native Super Order First
        ltp = self._wait_for_ltp(symbol, sec_id)
        if ltp:
            state = self._execute_native_super_order(symbol, sec_id, itm, ltp, params, leg_data, is_scalping)
            if state:
                return state

        # 3. Fallback: Simulated Bracket
        return self._execute_simulated_bracket(underlying, symbol, sec_id, itm, params, leg_data, is_scalping)

    def _resolve_entry_instrument(self, underlying, side, leg_data):
        """Resolves the ITM contract for the given side."""
        spot = leg_data.get('current_price', 0)
        opt_type = 'CE' if side == 'CALL' else 'PE'
        itm = self.broker.get_itm_contract(underlying, opt_type, spot)
        if not itm:
            logger.error(f"Failed to resolve ITM for {underlying} {side}")
        return itm

    def _wait_for_ltp(self, symbol, sec_id, max_retries=3):
        """Fetches LTP for a security with retries."""
        for attempt in range(max_retries):
            ltp = self.broker.get_ltp(sec_id)
            if ltp and ltp > 0:
                return ltp
            logger.warning(f"LTP fetch attempt {attempt+1} failed for {symbol}. Retrying...")
            time.sleep(1)
        return None

    def _execute_native_super_order(self, symbol, sec_id, itm_data, ltp, params, leg_data, is_scalping):
        """Calculates levels and places a Native Super Order."""
        sl_price = round(ltp * (1 - params['sl']/100), 1)
        tgt_price = round(ltp * (1 + params['target']/100), 1)
        trailing_val = round(ltp * (params['trailing']/100), 1)
        
        if sl_price <= 0: sl_price = 0.05
        if trailing_val <= 0: trailing_val = 1.0 # Minimum 1 tick jump
        
        entry_limit_price = round(ltp - 5, 1)
        if entry_limit_price <= 0.05: entry_limit_price = 0.05

        so_leg = itm_data.copy()
        so_leg.update({
            'quantity': leg_data.get('quantity', 1),
            'target_price': tgt_price,
            'stop_loss_price': sl_price,
            'trailing_jump': trailing_val,
            'order_type': 'LIMIT',
            'price': entry_limit_price
        })
        
        logger.info(f"Attempting Native Super Order for {symbol}. EntryLimit={entry_limit_price} (LTP-5), SL={sl_price}, TGT={tgt_price}")
        resp = self.broker.place_super_order(symbol, so_leg)
        
        if resp.get('success'):
            logger.info(f"Native Super Order Placed: {resp.get('order_id')}")
            return {
                'side': 'CALL' if 'CE' in symbol else 'PUT',
                'entry_id': resp.get('order_id'),
                'symbol': symbol,
                'security_id': sec_id,
                'sl_id': "NATIVE_BO", 
                'tgt_id': "NATIVE_BO",
                'is_super_order': True,
                'is_scalping': is_scalping,
                'quantity': so_leg['quantity']
            }
        logger.warning(f"Native Super Order Failed: {resp.get('error')}. Falling back to Simulation.")
        return None

    def _execute_simulated_bracket(self, underlying, symbol, sec_id, itm_data, params, leg_data, is_scalping):
        """Places a market entry and separate exit orders (Simulation mode)."""
        logger.info(f"Placing Market Entry (Simulated Bracket) for {symbol}")
        order_leg = itm_data.copy()
        order_leg['quantity'] = leg_data.get('quantity', 1)
        
        resp = self.broker.place_buy_order(symbol, order_leg)
        if not resp.get('success'):
            logger.error(f"Entry Failed: {resp.get('error')}")
            return None
        
        entry_id = resp['order_id']
        avg_price = self._wait_for_fill(entry_id)
        
        if avg_price <= 0:
            logger.warning(f"Could not fetch fill price for {entry_id}. Skipping SL/Target placement.")
            return {
                'side': 'CALL' if 'CE' in symbol else 'PUT',
                'entry_id': entry_id,
                'symbol': symbol,
                'security_id': sec_id,
                'sl_id': None,
                'tgt_id': None
            }
        
        # Calculate Exit Levels
        sl_price = round(avg_price * (1 - params['sl']/100), 1)
        tgt_price = round(avg_price * (1 + params['target']/100), 1)
        if sl_price <= 0: sl_price = 0.05
        
        # Place Exit Legs
        tgt_id = self._place_exit_leg(symbol, order_leg, tgt_price, "LIMIT")
        sl_id = self._place_exit_leg(symbol, order_leg, sl_price, "STOP_LOSS_MARKET")
        
        return {
            'side': 'CALL' if 'CE' in symbol else 'PUT',
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

    def _wait_for_fill(self, entry_id, max_retries=5):
        """Polls order status for average fill price."""
        for i in range(max_retries):
            try:
                status = self.broker.get_order_status(entry_id)
                if status and isinstance(status, dict):
                    st = status.get('orderStatus') 
                    if st in ['TRADED', 'FILLED']:
                        avg_price = float(status.get('averagePrice', 0.0) or status.get('price', 0.0))
                        if avg_price > 0:
                            return avg_price
            except Exception as e:
                logger.error(f"Error polling order status for {entry_id}: {e}")
            time.sleep(0.5)
        return 0.0

    def _place_exit_leg(self, symbol, order_leg, price, order_type):
        """Helper to place Target/SL sell orders."""
        leg = order_leg.copy()
        leg['order_type'] = order_type
        if order_type == "LIMIT":
            leg['price'] = price
        else:
            leg['trigger_price'] = price
            
        logger.info(f"Placing {order_type} Sell at {price}")
        resp = self.broker.place_sell_order(symbol, leg)
        if not resp.get('success'):
            logger.error(f"{order_type} Placement Failed: {resp.get('error')}")
        return resp.get('order_id')

    def _close_position(self, underlying, state):
        """
        Orchestrates closing of current position and handling Smart Exit.
        """
        symbol = state.get('symbol')
        sec_id = state.get('security_id')
        if not symbol or not sec_id:
            return

        ltp = self.broker.get_ltp(sec_id)
        if not ltp or ltp <= 0:
            return self._execute_emergency_exit(underlying, symbol, sec_id, state)

        # Smart Exit: Fetch and Modify Pending Legs
        is_super_order = state.get('is_super_order', False)
        pending_orders = self._get_pending_legs(sec_id, is_super_order)

        if not pending_orders:
             self._handle_missing_orders_exit(symbol, sec_id, state)
        else:
            logger.info(f"Smart Exit: Modifying {len(pending_orders)} pending orders for {symbol} at LTP {ltp}")
            self._handle_smart_exit_legs(pending_orders, ltp, underlying, state)
        
        logger.info(f"Smart Exit Initiated. State cleared for {underlying}.")
        self._clear_state(underlying)

    def _get_pending_legs(self, sec_id, is_super_order):
        """Fetches pending orders for the security."""
        if is_super_order:
            legs = self.broker.get_super_orders(sec_id)
            return legs if legs else self.broker.get_pending_orders(sec_id)
        return self.broker.get_pending_orders(sec_id)

    def _execute_emergency_exit(self, underlying, symbol, sec_id, state):
        """Standard Market Exit when Smart Exit is not possible."""
        logger.warning(f"Emergency Exit: Market closing {symbol} due to LTP fetch failure.")
        pending_orders = self.broker.get_pending_orders(sec_id)
        for order in pending_orders:
             self.broker.cancel_order(order.get('orderId'))
        
        exit_leg = { "symbol": symbol, "security_id": sec_id, "quantity": state.get('quantity', 1) }
        self.broker.place_sell_order(symbol, exit_leg)
        self._clear_state(underlying)

    def _handle_missing_orders_exit(self, symbol, sec_id, state):
        """Check positions and close if no pending orders are found."""
        logger.warning(f"Smart Exit: No pending orders for {symbol}. Checking Position.")
        positions = self.broker.get_positions()
        for pos in positions:
            if str(pos.get('securityId')) == str(sec_id):
                net_qty = int(pos.get('netQty', 0))
                if net_qty != 0:
                    exit_leg = { "symbol": symbol, "security_id": sec_id, "quantity": abs(net_qty), "order_type": "MARKET" }
                    self.broker.place_sell_order(symbol, exit_leg)
                    return True
        return False

    def _handle_smart_exit_legs(self, pending_orders, ltp, underlying, state):
        """Iterates through legs and applies smart modification logic."""
        parent_id = state.get('entry_id')
        is_super_order = state.get('is_super_order', False)

        for order in pending_orders:
            oid = order.get('orderId')
            leg_name = order.get('legName')
            otype = order.get('orderType') or order.get('order_type')
            txn = order.get('transactionType') or order.get('transaction_type')
            
            if txn == 'BUY':
                self._cancel_entry_leg(oid, parent_id, is_super_order)
            elif txn == 'SELL':
                if is_super_order and oid:
                    self._modify_super_leg(oid, leg_name, ltp, order)
                else:
                    self._modify_standard_leg(underlying, oid, otype, ltp, state)

    def _cancel_entry_leg(self, oid, parent_id, is_super_order):
        """Cancels an unfilled entry leg."""
        logger.info(f"Smart Exit: Cancelling Entry {oid}")
        if is_super_order and parent_id:
            self.broker.cancel_super_order(parent_id, 'ENTRY_LEG')
        else:
            self.broker.cancel_order(oid)

    def _modify_super_leg(self, oid, leg_name, ltp, order_data):
        """Modifies a leg of a Native Super Order."""
        if leg_name == 'TARGET_LEG':
            new_target = round(ltp + 5, 1)
            self.broker.modify_super_target_leg(oid, new_target)
        elif leg_name == 'STOP_LOSS_LEG':
            new_sl = round(ltp - 5, 1)
            if new_sl <= 0.05: new_sl = 0.05
            tj = order_data.get('trailingJump', 1.0)
            self.broker.modify_super_sl_leg(oid, new_sl, tj)

    def _modify_standard_leg(self, underlying, oid, otype, ltp, state):
        """Modifies a standard bracket leg."""
        if otype == 'LIMIT':
            new_price = round(ltp + 5, 1)
            self.broker.modify_order(oid, 'LIMIT', {'price': new_price})
        elif otype in ['STOP_LOSS', 'STOP_LOSS_MARKET']:
            params = self._get_params(underlying, state.get('is_scalping', False))
            trail_offset = round(ltp * (params['trailing']/100), 1)
            barrier = round(ltp - trail_offset, 1)
            self.broker.modify_order(oid, 'SL', {'trigger_price': barrier})

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

