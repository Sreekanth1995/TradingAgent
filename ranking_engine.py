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
        
        # Instrument Configurations (Target 55%, SL 20%, Trailing 10%, Slippage Buffer 1%)
        self.configs = {
            "NIFTY": {"target": 55, "sl": 20, "trailing": 20, "slippage_buffer": 1.0},
            "BANKNIFTY": {"target": 55, "sl": 20, "trailing": 20, "slippage_buffer": 1.0},
            "FINNIFTY": {"target": 55, "sl": 20, "trailing": 20, "slippage_buffer": 1.0},
            "DEFAULT": {"target": 55, "sl": 20, "trailing": 20, "slippage_buffer": 1.0}
        }
        
        # Scalping Mode Configuration (Trailing 5%, Slippage 0.5%)
        self.scalping_configs = {
            "target": 55,
            "sl": 20,
            "trailing": 5,
            "slippage_buffer": 0.5
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
        Checks if scalping mode is currently active based on volume trigger.
        Time-based windows and expiry day rules have been removed.
        
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
                
        return False

    def _handle_update_sl(self, underlying, is_scalping):
        """
        Calculates new SL based on active option's LTP and updates the pending
        SL order only if the new SL price is greater than the existing SL price.
        """
        state = self._get_state(underlying)
        side = state.get('side', 'NONE')
        if side not in ['CALL', 'PUT']:
            logger.info(f"UPDATE_SL ignored: No active position for {underlying}")
            return {"action": "NONE", "reason": "No active position to trail"}

        symbol = state.get('symbol')
        sec_id = state.get('security_id')
        if not symbol or not sec_id:
            return {"action": "NONE", "reason": "Missing security details"}

        ltp = self.broker.get_ltp(sec_id)
        if not ltp or ltp <= 0:
            logger.warning(f"UPDATE_SL failed: Could not fetch LTP for {symbol}")
            return {"action": "FAILED_LTP_FETCH", "symbol": symbol}

        params = self._get_params(underlying, is_scalping)
        
        is_super_order = state.get('is_super_order', False)
        pending_orders = self._get_pending_legs(sec_id, is_super_order)

        if not pending_orders:
            logger.info(f"UPDATE_SL ignored: No pending orders found for {symbol}")
            return {"action": "NONE", "reason": "No pending orders"}

        sl_updated = False
        action_log = []

        for order in pending_orders:
            oid = order.get('orderId')
            leg_name = order.get('legName', '')
            otype = order.get('orderType') or order.get('order_type', '')

            trail_offset = round(ltp * (params['trailing']/100), 1)
            new_sl = round(ltp - trail_offset, 1)
            
            if new_sl <= 0.05: new_sl = 0.05

            if is_super_order and leg_name == 'STOP_LOSS_LEG':
                existing_trigger = float(order.get('triggerPrice') or order.get('price') or 0.0)
                if new_sl > existing_trigger and existing_trigger > 0:
                    logger.info(f"LEVEL_CROSS: Updating Super Order SL {oid} from {existing_trigger} to {new_sl} (LTP: {ltp})")
                    tj = order.get('trailingJump', 1.0)
                    self.broker.modify_super_sl_leg(oid, new_sl, tj)
                    sl_updated = True
                    action_log.append(f"UPDATED_SL_{new_sl}")
                else:
                    logger.info(f"LEVEL_CROSS: New SL {new_sl} not > existing {existing_trigger}. Skipping.")

            elif not is_super_order and otype in ['STOP_LOSS', 'STOP_LOSS_MARKET']:
                existing_trigger = float(order.get('triggerPrice') or order.get('trigger_price') or 0.0)
                if new_sl > existing_trigger and existing_trigger > 0:
                    logger.info(f"LEVEL_CROSS: Updating Standard SL {oid} from {existing_trigger} to {new_sl} (LTP: {ltp})")
                    self.broker.modify_order(oid, 'SL', {'trigger_price': new_sl})
                    sl_updated = True
                    action_log.append(f"UPDATED_SL_{new_sl}")
                else:
                    logger.info(f"LEVEL_CROSS: New SL {new_sl} not > existing {existing_trigger}. Skipping.")

        if sl_updated:
            return {"underlying": underlying, "action": "UPDATED_SL", "actions": action_log, "symbol": symbol, "ltp": ltp}
        else:
            return {"action": "NONE", "reason": "New SL not greater than existing SL"}

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
    def process_signal(self, underlying, signal_type, mode, leg_data):
        """
        Main entry point for processing BUY/SELL signals.
        Coordinates validation, locking, and execution.
        """
        now_ist = datetime.now(IST)
        is_scalping = (str(mode).lower() == 'scalping')

        # 2. Deduplication Check (DISABLED as per new strategy)
        state = self._get_state(underlying)
        # if signal_type == state.get('last_signal', 'NONE'):
        #     logger.info(f"Deduplication: Ignoring consecutive {signal_type} signal for {underlying}")
        #     return {"underlying": underlying, "signal": signal_type, "action": "SKIPPED_DUPLICATE", "time": now_ist.strftime('%H:%M:%S')}

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
            if signal_type in ['B', 'LONG', 'BUY']:
                result = self._execute_signal(underlying, 'B', mode, leg_data, state, current_side, now_ist, is_scalping)
            elif signal_type in ['S', 'SHORT', 'SELL']:
                result = self._execute_signal(underlying, 'S', mode, leg_data, state, current_side, now_ist, is_scalping)
            elif signal_type == 'LONG_EXIT':
                result = self._handle_directional_exit(underlying, 'CALL')
            elif signal_type == 'SHORT_EXIT':
                result = self._handle_directional_exit(underlying, 'PUT')
            elif signal_type in ['UPDATE_SL', 'LEVEL_CROSS', 'TRAIL', 'UPDATE']:
                result = self._handle_update_sl(underlying, is_scalping)
            else:
                logger.warning(f"Unknown signal type: {signal_type}")
                result = {"action": "NONE", "reason": f"Unknown signal type: {signal_type}"}
            
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
        success_indicators = [
            'OPENED_CALL', 'OPENED_PUT', 'CLOSED_CALL', 'CLOSED_PUT',
            'PLACED_NEW_CE', 'PLACED_NEW_PE',
            'CANCELLED_CE_ENTRY', 'CANCELLED_PE_ENTRY',
            'MODIFIED_ALIGNED_CE_ALL', 'MODIFIED_ALIGNED_PE_ALL',
            'MODIFIED_ALIGNED_CE_EXIT', 'MODIFIED_ALIGNED_PE_EXIT',
            'MODIFIED_OPPOSITE_CE_EXIT', 'MODIFIED_OPPOSITE_PE_EXIT'
        ]
        
        if any(a in actions for a in success_indicators) or not actions:
            new_state = self._get_state(underlying)
            new_state['last_signal'] = signal_type
            self._set_state(underlying, new_state)
            logger.debug(f"State Updated: last_signal={signal_type} for {underlying}")
        else:
            logger.warning(f"Execution failed for {underlying}. last_signal NOT updated.")



    def _execute_signal(self, underlying, signal_type, mode, leg_data, state, current_side, now_ist, is_scalping=False):
        """
        Advanced Strategy Implementation:
        Manages Super Orders based on signal alignment and leg status.
        """
        action_log = []
        
        # 1. Fetch Index LTP for ITM resolution
        # We need to resolve both CE and PE contracts for management
        index_ids = {"NIFTY": "13", "BANKNIFTY": "25", "FINNIFTY": "27"} 
        idx_id = index_ids.get(underlying.upper())
        
        # Prioritize payload price if available from TradingView/Webhook
        spot_price = float(leg_data.get('current_price', 0))
        
        if spot_price <= 0 and idx_id:
            # Note: For Index LTP, Dhan API v2 expects exchange_segment="IDX_I"
            spot_price = self.broker.get_ltp(idx_id, exchange_segment="IDX_I") or 0.0
        
        if spot_price <= 0:
            logger.error(f"Cannot execute strategy for {underlying}: Index LTP failed.")
            return {"underlying": underlying, "action": "FAILED_INDEX_LTP", "time": now_ist.strftime('%H:%M:%S')}

        # 2. Resolve ITM CE and PE targets
        itm_ce = self.broker.get_itm_contract(underlying, 'CE', spot_price)
        itm_pe = self.broker.get_itm_contract(underlying, 'PE', spot_price)
        
        if not itm_ce or not itm_pe:
            logger.error(f"Failed to resolve ITM contracts for {underlying}")
            return {"underlying": underlying, "action": "FAILED_ITM_RESOLUTION", "time": now_ist.strftime('%H:%M:%S')}

        # 3. Fetch all active Super Orders
        # We group them by Side (CE/PE) using their securityId or Symbol
        all_legs = self.broker.get_super_orders()
        
        # Group legs by Parent Order ID
        orders_by_id = {}
        for leg in all_legs:
            oid = leg['orderId']
            if oid not in orders_by_id:
                orders_by_id[oid] = {'legs': [], 'side': None, 'securityId': leg.get('securityId')}
            orders_by_id[oid]['legs'].append(leg)
            
            # Identify side based on securityId or tradingSymbol (heuristic)
            if leg.get('securityId') == itm_ce['security_id']:
                orders_by_id[oid]['side'] = 'CE'
            elif leg.get('securityId') == itm_pe['security_id']:
                orders_by_id[oid]['side'] = 'PE'
            else:
                # Fallback: Check tradingSymbol for Side identification
                t_sym = str(leg.get('tradingSymbol') or '').upper()
                if underlying.upper() in t_sym:
                    if 'CE' in t_sym:
                        orders_by_id[oid]['side'] = 'CE'
                    elif 'PE' in t_sym:
                        orders_by_id[oid]['side'] = 'PE'

        # 4. Strategy Processing
        if signal_type == 'B': # BUY (CE Aligned, PE Opposite)
            # 4.1 Handle Opposite Side (PE)
            self._manage_opposite_orders(orders_by_id, 'PE', action_log)
            # 4.2 Handle Aligned Side (CE)
            self._manage_aligned_orders(underlying, itm_ce, orders_by_id, 'CE', action_log, mode, is_scalping)
            
        elif signal_type == 'S': # SELL (PE Aligned, CE Opposite)
            # 4.1 Handle Opposite Side (CE)
            self._manage_opposite_orders(orders_by_id, 'CE', action_log)
            # 4.2 Handle Aligned Side (PE)
            self._manage_aligned_orders(underlying, itm_pe, orders_by_id, 'PE', action_log, mode, is_scalping)

        elif signal_type == 'LONG_EXIT':
            logger.info(f"Strategy: Explicit LONG_EXIT for {underlying}")
            self._manage_opposite_orders(orders_by_id, 'CE', action_log)

        elif signal_type == 'SHORT_EXIT':
            logger.info(f"Strategy: Explicit SHORT_EXIT for {underlying}")
            self._manage_opposite_orders(orders_by_id, 'PE', action_log)

        return {
            "underlying": underlying,
            "signal": signal_type,
            "actions": action_log,
            "action": ", ".join(action_log) if action_log else "NO_ACTION",
            "time": now_ist.strftime('%H:%M:%S')
        }

    def _manage_opposite_orders(self, orders_by_id, side_to_manage, action_log):
        """
        Opposite side logic:
        - If Entry Leg exists: Cancel.
        - If only Target/SL legs exist: Modify Target=LTP+1, SL=LTP-5.
        """
        for oid, order in orders_by_id.items():
            if order['side'] != side_to_manage:
                continue
            
            leg_names = [l['legName'] for l in order['legs']]
            sec_id = order['securityId']
            ltp = self.broker.get_ltp(sec_id) if sec_id else None
            
            if 'ENTRY_LEG' in leg_names:
                logger.info(f"Strategy: Cancelling opposite {side_to_manage} super order {oid} (Entry active)")
                self.broker.cancel_super_order(oid, 'ENTRY_LEG')
                self._clear_state(underlying) # Clear state to reflect closure in UI
                action_log.append(f"CANCELLED_{side_to_manage}_ENTRY")
            elif 'TARGET_LEG' in leg_names and 'STOP_LOSS_LEG' in leg_names:
                if ltp:
                    new_tgt = ltp + 5
                    new_sl = ltp - 5
                    logger.info(f"Strategy: Modifying opposite {side_to_manage} {oid} -> TGT:{new_tgt}, SL:{new_sl}")
                    self.broker.modify_super_target_leg(oid, new_tgt)
                    self.broker.modify_super_sl_leg(oid, new_sl)
                    action_log.append(f"MODIFIED_OPPOSITE_{side_to_manage}_EXIT")

    def _manage_aligned_orders(self, underlying, itm_data, orders_by_id, side_to_manage, action_log, mode, is_scalping):
        """
        Aligned side logic:
        - If no order: Place new Native Super Order (Market Entry, 55/20/Config SL).
        - If existing order: No modifications (trust Native Legs).
        """
        params = self._get_params(underlying, is_scalping)
        target_oid = None
        for oid, order in orders_by_id.items():
            if order['side'] == side_to_manage:
                target_oid = oid
                break
        
        if not target_oid:
            # Resolve CALL/PUT side for _open_position
            # side_to_manage is 'CE' or 'PE'
            side = 'CALL' if side_to_manage == 'CE' else 'PUT'
            logger.info(f"Strategy: Placing NEW {side} position for {underlying}")
            new_state = self._open_position(underlying, side, {"quantity": 1}, is_scalping) # Default 1 lot
            if new_state:
                self._set_state(underlying, new_state) # Persist the new position state
                action_log.append(f"OPENED_{side}")
        else:
            # Manage Existing Order (Smart Exit / Modification)
            # In Phase 1/2, we only modify for reversals (handled in _manage_opposite)
            # or for volume-based updates. 
            # For now, we trust the existing Native Super Order legs unless a reversal happens.
            logger.info(f"Strategy: Aligned {side_to_manage} position already exists ({target_oid}). No modifications needed.")

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
        return self._execute_simulated_bracket(underlying, symbol, sec_id, itm, params, leg_data, is_scalping, ltp)

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
        
        slippage = params.get('slippage_buffer', 1.0)
        entry_limit_price = round(ltp * (1 + slippage/100), 1)
        
        so_leg = itm_data.copy()
        so_leg.update({
            'quantity': leg_data.get('quantity', 1),
            'target_price': tgt_price,
            'stop_loss_price': sl_price,
            'trailing_jump': trailing_val,
            'order_type': 'LIMIT',
            'price': entry_limit_price
        })
        
        logger.info(f"Attempting Native Super Order for {symbol}. EntryLimit={entry_limit_price} (LTP={ltp}), SL={sl_price}, TGT={tgt_price}")
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

    def _execute_simulated_bracket(self, underlying, symbol, sec_id, itm_data, params, leg_data, is_scalping, ltp=None):
        """Places a protected entry and separate exit orders (Simulation mode)."""
        order_leg = itm_data.copy()
        order_leg['quantity'] = leg_data.get('quantity', 1)

        if ltp and ltp > 0:
            slippage = params.get('slippage_buffer', 1.0)
            entry_limit_price = round(ltp * (1 + slippage/100), 1)
            order_leg['order_type'] = 'LIMIT'
            order_leg['price'] = entry_limit_price
            logger.info(f"Placing LIMIT Entry (Simulated Bracket) for {symbol} at {entry_limit_price}")
        else:
            order_leg['order_type'] = 'MARKET'
            logger.info(f"Placing MARKET Entry (Simulated Bracket) for {symbol} (LTP missing)")
        
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
                    self._modify_super_leg(oid, leg_name, ltp, order, state.get('is_scalping', False))
                else:
                    self._modify_standard_leg(underlying, oid, otype, ltp, state)

    def _cancel_entry_leg(self, oid, parent_id, is_super_order):
        """Cancels an unfilled entry leg."""
        logger.info(f"Smart Exit: Cancelling Entry {oid}")
        if is_super_order and parent_id:
            self.broker.cancel_super_order(parent_id, 'ENTRY_LEG')
        else:
            self.broker.cancel_order(oid)

    def _handle_directional_exit(self, underlying, side):
        """
        Handles specific LONG_EXIT or SHORT_EXIT signals for a side.
        Performs immediate Market Exit if the side matches.
        """
        state = self._get_state(underlying)
        if not state or state.get('side') != side:
            logger.info(f"Directional Exit ({side}) ignored: No matching position found for {underlying}.")
            return {"action": "NONE", "reason": "No matching side active"}
            
        logger.info(f"Directional Exit ({side}) triggered for {underlying}. Performing Market Square-off.")
        res = self._close_position_market(underlying, state)
        self._clear_state(underlying)  # Clear state for UI
        return res

    def _close_position_market(self, underlying, state):
        """
        Closes a position immediately using a MARKET order.
        Squares off any filled quantity after cancelling pending legs.
        """
        symbol = state.get('symbol')
        sec_id = state.get('security_id')
        qty = state.get('quantity', 0)
        parent_id = state.get('entry_id')
        is_so = state.get('is_super_order', False)
        
        # 1. Cancel all pending legs for this Super Order
        if is_so and parent_id:
            logger.info(f"Market Exit: Cancelling Super Order legs for {parent_id}")
            # Cancelling the parent order cancels all pending legs
            self.broker.cancel_super_order(parent_id, 'ENTRY_LEG')
            self.broker.cancel_super_order(parent_id, 'TARGET_LEG')
            self.broker.cancel_super_order(parent_id, 'STOP_LOSS_LEG')
        
        # 2. Square off filled quantity
        # In a real scenario, we might need to fetch the actual net position from broker.
        # For now, we use the quantity tracked in our state.
        if qty > 0:
            logger.info(f"Market Exit: Placing square-off MARKET order for {symbol}, Qty: {qty}")
            # Square off logic: Opposite transaction type
            # State tracks the original ENTRY side: CALL (Long CE) or PUT (Long PE)
            # Both are technically Buy entries in this bot (Long Options strategy)
            # So square off is always a SELL.
            resp = self.broker.place_order(symbol, {
                'security_id': sec_id,
                'quantity': qty,
                'transaction_type': 'SELL',
                'order_type': 'MARKET',
                'product_type': 'MARGIN' # Or whatever matches the original
            })
            
            if resp.get('success'):
                logger.info(f"Market Square-off successful for {symbol}")
            else:
                logger.error(f"Market Square-off FAILED for {symbol}: {resp.get('error')}")
                # We still clear state to avoid stuck loops, but log the error
        
        # 3. Clear state
        self._clear_state(underlying)
        return {"action": "EXIT_MARKET", "symbol": symbol, "quantity": qty}

    def _modify_super_leg(self, oid, leg_name, ltp, order_data, is_scalping=False):
        """Modifies a leg of a Native Super Order for Smart Exit (LTP +/- 5)."""
        offset = 5
        if leg_name == 'TARGET_LEG':
            new_target = round(ltp + offset, 1)
            self.broker.modify_super_target_leg(oid, new_target)
        elif leg_name == 'STOP_LOSS_LEG':
            new_sl = round(ltp - offset, 1)
            if new_sl <= 0.05: new_sl = 0.05
            tj = order_data.get('trailingJump', 1.0)
            self.broker.modify_super_sl_leg(oid, new_sl, tj)

    def _modify_standard_leg(self, underlying, oid, otype, ltp, state):
        """Modifies a standard bracket leg."""
        is_scalping = state.get('is_scalping', False)
        if otype == 'LIMIT':
            offset = 1 if is_scalping else 5
            new_price = round(ltp + offset, 1)
            self.broker.modify_order(oid, 'LIMIT', {'price': new_price})
        elif otype in ['STOP_LOSS', 'STOP_LOSS_MARKET']:
            params = self._get_params(underlying, state.get('is_scalping', False))
            trail_offset = round(ltp * (params['trailing']/100), 1)
            barrier = round(ltp - trail_offset, 1)
            
            # Fetch existing trigger price if available
            existing_trigger = float(order_data.get('triggerPrice') or order_data.get('trigger_price') or 0)
            
            if barrier > existing_trigger:
                logger.info(f"Smart Exit: Updating SL {oid} from {existing_trigger} to {barrier}")
                self.broker.modify_order(oid, 'SL', {'trigger_price': barrier})
            else:
                logger.info(f"Smart Exit: New SL {barrier} is not higher than existing {existing_trigger} for {oid}. Skipping.")

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
            self._close_position_market(underlying, state)
            self._clear_state(underlying) # Clear state for UI

