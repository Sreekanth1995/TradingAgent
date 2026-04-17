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

class SuperOrderEngine:
    """
    Direct Signal Trading Engine.
    Handles BUY/SELL signals to manage simulated bracket orders (Entry + SL + Target).
    """
    def __init__(self, broker=None, is_dry_run=False, redis_client=None, activity_logs=None):
        """
        Initializes the SuperOrderEngine with a broker and state storage.
        
        Args:
            broker: The broker client instance (e.g., DhanClient).
            is_dry_run: Boolean, true if we should skip real broker calls.
            redis_client: Optional Redis connection for persisting state across multiple workers.
            activity_logs: Optional deque for pushing live frontend logs.
        """
        self.broker = broker
        self.is_dry_run = is_dry_run
        self.redis = redis_client
        self.r = redis_client
        self.activity_logs = activity_logs
        self.use_redis = False
        self.memory_store = {}
        
        # Standard Risk Configurations (Target %, SL %, Trailing %)
        self.configs = {
            "DEFAULT": {"target": 55, "sl": 20, "trailing": 20, "slippage_buffer": 1.0}
        }
        
        # self.processing_locks = set() # MOVED TO REDIS

        if self.r:
            try:
                self.r.ping()
                logger.info("✅ SuperOrderEngine: Using shared Redis connection")
                self.use_redis = True
            except Exception as e:
                logger.warning(f"SuperOrderEngine: Injected Redis client failed ping ({e}). Using in-memory storage.")
        else:
            logger.warning("SuperOrderEngine: No Redis client provided. Using in-memory storage.")

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
        """Clears the state and cancels associated conditional orders."""
        state = self._get_state(underlying)
        self._cancel_active_conditional_orders(underlying, state)
        
        # Reset state
        new_state = {'side': 'NONE', 'last_signal': 'NONE'}
        self._set_state(underlying, new_state)
        logger.info(f"State cleared for {underlying}")

    def handle_signal(self, signal_type, leg_data, mode='regular'):
        """
        Public entry point for signals.
        Returns result dict containing 'status' and optionally 'order_id'.
        """
        underlying = leg_data.get('underlying', 'BASE')
        res = self.process_signal(underlying, signal_type, mode, leg_data)
        
        # Extract orderId if available from the internal execution result
        # Note: _finalize_signal_state might have it in 'entry_id'
        state = self._get_state(underlying)
        if res.get('status') == 'success':
            res['order_id'] = state.get('entry_id')
            
        return res

    def _add_activity_log(self, msg, prefix=""):
        """Logs to local deque and shared Redis if available."""
        from datetime import datetime
        timestamp = datetime.now().strftime('%H:%M:%S')
        full_msg = f"[{timestamp}] {prefix}{msg}"
        
        if self.activity_logs is not None:
            self.activity_logs.appendleft(full_msg)
            
        if self.r: # self.r is the shared redis_client
            try:
                pipe = self.r.pipeline()
                pipe.lpush("activity_logs", full_msg)
                pipe.ltrim("activity_logs", 0, 49)
                pipe.execute()
            except Exception as e:
                logger.error(f"Failed to persist activity log to Redis: {e}")

    def handle_order_update(self, payload):
        """
        Processes Dhan Webhook payloads for order status changes.
        """
        order_id = payload.get('orderId')
        status = payload.get('orderStatus')
        avg_price = float(payload.get('averagePrice', 0.0) or payload.get('price', 0.0))
        
        if status in ['TRADED', 'FILLED']:
            # 1. Check for Pending Brackets (Entry filled -> Place SL/TGT)
            pending_key = f"pending_bracket:{order_id}"
            pending_data = None
            
            if self.use_redis:
                val = self.r.get(pending_key)
                if val:
                    pending_data = json.loads(val)
                    self.r.delete(pending_key)
            elif pending_key in self.memory_store:
                pending_data = self.memory_store.get(pending_key)
                del self.memory_store[pending_key]

            if pending_data:
                underlying = pending_data.get('underlying')
                logger.info(f"📡 Entry Filled for {underlying}: {order_id} at {avg_price}. Placing protection legs...")
                self._place_protection_from_fill(underlying, order_id, avg_price, pending_data)
            else:
                # 2. Check for known entry fills (Native)
                self._handle_entry_leg_fill(order_id, avg_price)
                # 3. Check for Exit Leg fills (SL/TGT filled -> Cleanup Position)
                self._handle_exit_leg_fill(order_id, status)
                
        elif status in ['CANCELLED', 'REJECTED']:
            # Cleanup pending data if entry cancelled
            pending_key = f"pending_bracket:{order_id}"
            if self.use_redis: self.r.delete(pending_key)
            elif pending_key in self.memory_store: del self.memory_store[pending_key]
            logger.info(f"Order {order_id} was {status}. Pending data cleaned up.")

    def _place_protection_from_fill(self, underlying, entry_id, avg_price, pending_data):
        """Places SL and Target legs after an entry fill is confirmed via webhook."""
        symbol = pending_data['symbol']
        sec_id = pending_data['security_id']
        params = pending_data['params']
        itm_data = pending_data['itm_data']
        
        # Calculate Exit Levels
        sl_price = round(avg_price * (1 - params['sl']/100), 1)
        tgt_price = round(avg_price * (1 + params['target']/100), 1)
        if sl_price <= 0: sl_price = 0.05
        
        # Place Exit Legs
        order_leg = itm_data.copy()
        order_leg['quantity'] = pending_data.get('quantity', 1)
        
        tgt_id = self._place_exit_leg(symbol, order_leg, tgt_price, "LIMIT")
        sl_id = self._place_exit_leg(symbol, order_leg, sl_price, "STOP_LOSS_MARKET")
        
        # Update State
        state = {
            'side': pending_data['side'],
            'entry_id': entry_id,
            'symbol': symbol,
            'security_id': sec_id,
            'sl_id': sl_id, 
            'tgt_id': tgt_id,
            'sl_price': sl_price,
            'tgt_price': tgt_price,
            'quantity': order_leg['quantity']
        }
        self._set_state(underlying, state)
        self._add_activity_log(f"Position Active: {symbol} at {avg_price}. SL: {sl_price}, TGT: {tgt_price}", "⚡ ")

    def _handle_entry_leg_fill(self, order_id, avg_price):
        """Processes fills for known entry orders (Native)."""
        keys = []
        if self.use_redis:
            keys = self.r.keys("state:*")
        else:
            keys = [k for k in self.memory_store.keys() if k.startswith("state:")]

        for k in keys:
            underlying = k.split(":")[1] if ":" in k else k
            state = self._get_state(underlying)
            if state.get('entry_id') == order_id:
                symbol = state.get('symbol')
                logger.info(f"📡 Native Entry Filled for {underlying}: {order_id} at {avg_price}.")
                # For Native, SL/TGT already calculated during placement
                sl = state.get('sl_price')
                tgt = state.get('tgt_price')
                self._add_activity_log(f"Position Active: {symbol} at {avg_price}. SL: {sl}, TGT: {tgt}", "⚡ ")
                break

    def _handle_exit_leg_fill(self, order_id, status):
        """Checks if a filled order was a SL or Target leg and cleans up."""
        keys = []
        if self.use_redis:
            keys = self.r.keys("state:*")
        else:
            keys = [k for k in self.memory_store.keys() if k.startswith("state:")]

        for k in keys:
            underlying = k.split(":")[1] if ":" in k else k
            state = self._get_state(underlying)
            if state.get('sl_id') == order_id or state.get('tgt_id') == order_id:
                logger.info(f"📡 Exit Leg Filled: {order_id} ({status}) for {underlying}. Clearing position state.")
                self._add_activity_log(f"Exit Filled: {state.get('symbol')} via {status}", "🏁 ")
                # Cancel the remaining leg
                self._cancel_active_conditional_orders(underlying, state)
                # Clear state
                self._clear_state(underlying)
                break
        """Cancels associated Dhan Alert triggers (GTT) if they exist in state."""
        alert_keys = (
            'conditional_target_alert_id', 'conditional_sl_alert_id',
            'idx_target_alert_id', 'idx_sl_alert_id'
        )
        for key in alert_keys:
            alert_id = state.get(key)
            if alert_id:
                logger.info(f"Cleanup: Cancelling conditional order {alert_id} for {underlying}")
                self.broker.cancel_conditional_order(alert_id)

    def _get_params(self, underlying):
        """Returns the execution parameters."""
        # Index-blind lookup: relies on DEFAULT unless a specific security override exists
        return self.configs.get("DEFAULT")



    def _handle_update_sl(self, underlying):
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

        params = self._get_params(underlying)
        
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

    def _validate_market_volatility(self, underlying, now_ist):
        """
        Checks if the signal should be skipped due to initial market volatility.
        """
        market_start = now_ist.replace(hour=MARKET_OPEN_HOUR, minute=MARKET_OPEN_MINUTE, second=0, microsecond=0)
        delay_end = market_start.replace(minute=MARKET_OPEN_MINUTE + MARKET_VOLATILITY_DELAY_MINS)
        if market_start <= now_ist < delay_end:
            logger.info(f"Market Volatility Delay: Ignoring signal for {underlying} during first {MARKET_VOLATILITY_DELAY_MINS} mins.")
            return False, {"underlying": underlying, "action": "SKIPPED_MARKET_OPEN_DELAY", "time": now_ist.strftime('%H:%M:%S')}
        return True, None

    # --- Core Logic ---
    def process_signal(self, underlying, itm, signal_type, mode, leg_data):
        """
        Main entry point for processing BUY/SELL signals.
        Coordinates validation, locking, and execution.
        """
        now_ist = datetime.now(IST)

        # 2. Deduplication Check (DISABLED as per new strategy)
        state = self._get_state(underlying)
        # if signal_type == state.get('last_signal', 'NONE'):
        #     logger.info(f"Deduplication: Ignoring consecutive {signal_type} signal for {underlying}")
        #     return {"underlying": underlying, "signal": signal_type, "action": "SKIPPED_DUPLICATE", "time": now_ist.strftime('%H:%M:%S')}

        # 3. Market Volatility Check
        is_valid_vol, err_vol = self._validate_market_volatility(underlying, now_ist)
        if not is_valid_vol:
            return err_vol

        # 4. Locking & Execution
        lock_key = f"proc_lock:{underlying}"
        if self.use_redis:
            # Distributed Lock (set nx=True means only creates if not exists)
            if not self.r.set(lock_key, "locked", nx=True, ex=30):
                logger.warning(f"Execution Lock: Signal for {underlying} is already being processed by another worker. Skipping.")
                return {"underlying": underlying, "action": "SKIPPED_LOCKED", "time": now_ist.strftime('%H:%M:%S')}
        
        try:
            if signal_type in ['B', 'LONG', 'BUY']:
                result = self._execute_signal(underlying, itm, mode, leg_data, state, now_ist)
            elif signal_type in ['S', 'SHORT', 'SELL']:
                result = self._execute_signal(underlying, itm, mode, leg_data, state, now_ist)
            elif signal_type == 'LONG_EXIT':
                result = self._handle_directional_exit(underlying, 'CALL')
            elif signal_type == 'SHORT_EXIT':
                result = self._handle_directional_exit(underlying, 'PUT')
            elif signal_type in ['UPDATE_SL', 'LEVEL_CROSS', 'TRAIL', 'UPDATE']:
                result = self._handle_update_sl(underlying)
            else:
                logger.warning(f"Unknown signal type: {signal_type}")
                result = {"action": "NONE", "reason": f"Unknown signal type: {signal_type}"}
            
            # 5. Commit state only on successful outcomes
            self._finalize_signal_state(underlying, result, signal_type)
            return result
        finally:
            if self.use_redis:
                self.r.delete(lock_key)

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



    def _execute_signal(self, underlying, itm, mode, leg_data, state, now_ist):
        """
        Price-based Strategy Implementation:
        Manages orders based on provided security context (itm_ce, itm_pe).
        """
        action_log = []
        
        # 1. Access provided Security Context
        # itm_ce and itm_pe are still provided in leg_data for symmetric awareness,
        # but the primary 'itm' (target instrument) is now passed explicitly.
        itm_ce = leg_data.get('itm_ce')
        itm_pe = leg_data.get('itm_pe')
        
        # Determine current target side and instrument
        target_itm = itm
        signal_type = 'B' if target_itm == itm_ce else 'S' if target_itm == itm_pe else 'B' 

        if not target_itm:
            logger.error(f"Cannot execute price strategy for {underlying}: Missing target instrument context.")
            return {"underlying": underlying, "action": "FAILED_CONTEXT_MISSING", "time": now_ist.strftime('%H:%M:%S')}

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
            
            # Identify side using exact security map reference
            sec_id = leg.get('securityId')
            
            if sec_id == itm_ce['security_id']:
                orders_by_id[oid]['side'] = 'CE'
            elif sec_id == itm_pe['security_id']:
                orders_by_id[oid]['side'] = 'PE'
            else:
                # Robust reverse lookup: natively decode sec_id directly from Master Scrip map
                # This guarantees side mapping even if the Index spot price shifted the ITM baseline
                info = self.broker.get_security_info(sec_id)
                if info:
                    sym, _, opt_type, _ = info
                    if sym == underlying:
                        orders_by_id[oid]['side'] = opt_type
                else:
                    # Final fallback: Check tradingSymbol payload logic
                    t_sym = str(leg.get('tradingSymbol') or '').upper()
                    if underlying.upper() in t_sym:
                        if 'CE' in t_sym:
                            orders_by_id[oid]['side'] = 'CE'
                        elif 'PE' in t_sym:
                            orders_by_id[oid]['side'] = 'PE'

        # 4. Strategy Processing
        if signal_type == 'B': # BUY (CE Aligned, PE Opposite)
            # 4.1 Handle Opposite Side (PE)
            self._manage_opposite_orders(underlying, state, orders_by_id, 'PE', action_log)
            # 4.2 Handle Aligned Side (CE)
            self._manage_aligned_orders(underlying, itm_ce, orders_by_id, 'CE', action_log, mode, leg_data)
            
        elif signal_type == 'S': # SELL (PE Aligned, CE Opposite)
            # 4.1 Handle Opposite Side (CE)
            self._manage_opposite_orders(underlying, state, orders_by_id, 'CE', action_log)
            # 4.2 Handle Aligned Side (PE)
            self._manage_aligned_orders(underlying, itm_pe, orders_by_id, 'PE', action_log, mode, leg_data)

        elif signal_type == 'LONG_EXIT':
            logger.info(f"Strategy: Explicit LONG_EXIT for {underlying}")
            self._manage_opposite_orders(underlying, state, orders_by_id, 'CE', action_log)

        elif signal_type == 'SHORT_EXIT':
            logger.info(f"Strategy: Explicit SHORT_EXIT for {underlying}")
            self._manage_opposite_orders(underlying, state, orders_by_id, 'PE', action_log)

        state = self._get_state(underlying)
        return {
            "underlying": underlying,
            "signal": signal_type,
            "actions": action_log,
            "action": ", ".join(action_log) if action_log else "NO_ACTION",
            "order_id": state.get('entry_id') if state else None,
            "status": state.get('status') if state else "ACTIVE",
            "time": now_ist.strftime('%H:%M:%S')
        }

    def _manage_opposite_orders(self, underlying, state, orders_by_id, side_to_manage, action_log):
        """
        Opposite side logic:
        - Completely square off the opposite position.
        """
        closed_from_state = False
        for oid, order in orders_by_id.items():
            if order['side'] != side_to_manage:
                continue
            
            leg_names = [l['legName'] for l in order['legs']]
            sec_id = order['securityId']
            
            if 'ENTRY_LEG' in leg_names:
                logger.info(f"Strategy: Cancelling opposite {side_to_manage} super order {oid} (Entry active)")
                self.broker.cancel_super_order(oid, 'ENTRY_LEG')
                self._clear_state(underlying) # Clear state to reflect closure in UI
                action_log.append(f"CANCELLED_{side_to_manage}_ENTRY")
                state_sec_id = state.get('security_id')
                if state_sec_id and str(state_sec_id) == str(sec_id):
                    closed_from_state = True
            elif 'TARGET_LEG' in leg_names or 'STOP_LOSS_LEG' in leg_names:
                logger.info(f"Strategy: Closing opposite {side_to_manage} {oid}")
                # Check if it corresponds to the current state
                state_sec_id = state.get('security_id')
                if state_sec_id and str(state_sec_id) == str(sec_id):
                    self._close_position_market(underlying, state)
                    action_log.append(f"CLOSED_OPPOSITE_{side_to_manage}")
                    closed_from_state = True
                else:
                    # Manually close orphan position
                    if 'TARGET_LEG' in leg_names:
                        self.broker.cancel_super_order(oid, 'TARGET_LEG')
                    if 'STOP_LOSS_LEG' in leg_names:
                        self.broker.cancel_super_order(oid, 'STOP_LOSS_LEG')
                    
                    info = self.broker.get_security_info(sec_id)
                    if info:
                        sym = info[0]
                        qty = 0
                        for pos in self.broker.get_positions():
                            if str(pos.get('securityId')) == str(sec_id):
                                qty = abs(int(pos.get('netQty', 0)))
                                break
                        if qty > 0:
                            self.broker.place_order(sym, {
                                'security_id': sec_id,
                                'quantity': qty,
                                'transaction_type': 'SELL',
                                'order_type': 'MARKET',
                                'product_type': 'MARGIN'
                            })
                    self._clear_state(underlying)
                    action_log.append(f"CLOSED_OPPOSITE_{side_to_manage}")

        # Also check if opposite position is active in state (but wasn't in Super Orders)
        if not closed_from_state:
            state_side = state.get('side', 'NONE')
            target_state_side = 'CALL' if side_to_manage == 'CE' else 'PUT'
            if state_side == target_state_side:
                logger.info(f"Strategy: Closing opposite {target_state_side} position from state")
                self._close_position_market(underlying, state)
                action_log.append(f"CLOSED_OPPOSITE_{side_to_manage}")

    def _manage_aligned_orders(self, underlying, itm_data, orders_by_id, side_to_manage, action_log, mode, leg_data):
        """
        Aligned side logic:
        - If no order: Place new Native Super Order (Market Entry, 55/20/Config SL).
        - If existing order: No modifications (trust Native Legs).
        """
        params = self._get_params(underlying)
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
            entry_data = leg_data.copy() if hasattr(leg_data, 'copy') else {}
            if 'quantity' not in entry_data: entry_data['quantity'] = 1
            new_state = self._open_position(underlying, side, entry_data)
            if new_state:
                self._set_state(underlying, new_state) # Persist the new position state
                action_log.append(f"OPENED_{side}")
        else:
            # Manage Existing Order (Smart Exit / Modification)
            # In Phase 1/2, we only modify for reversals (handled in _manage_opposite)
            # or for volume-based updates. 
            # For now, we trust the existing Native Super Order legs unless a reversal happens.
            logger.info(f"Strategy: Aligned {side_to_manage} position already exists ({target_oid}). No modifications needed.")

    def _open_position(self, underlying, side, leg_data):
        """
        Opens a new position using provided ITM context.
        """
        # Distinguish side from leg_data injected context
        itm = leg_data.get('itm_ce') if side == 'CALL' else leg_data.get('itm_pe')
        if not itm:
            logger.error(f"Missing ITM context for {side} on {underlying}")
            return None
        
        symbol = itm['symbol']
        sec_id = itm['security_id']
        params = self._get_params(underlying)
        
        # 1. Try Native Super Order First
        ltp = self._wait_for_ltp(symbol, sec_id)
        if ltp:
            state = self._execute_native_super_order(symbol, sec_id, itm, ltp, params, leg_data)
            if state:
                return state

        # 2. Fallback: Simulated Bracket
        return self._execute_simulated_bracket(underlying, symbol, sec_id, itm, params, leg_data, ltp)

    def _wait_for_ltp(self, symbol, sec_id, max_retries=3):
        """Fetches LTP for a security with retries."""
        for attempt in range(max_retries):
            ltp = self.broker.get_ltp(sec_id)
            if ltp and ltp > 0:
                return ltp
            logger.warning(f"LTP fetch attempt {attempt+1} failed for {symbol}. Retrying...")
            time.sleep(1)
        return None

    def _execute_native_super_order(self, symbol, sec_id, itm_data, ltp, params, leg_data):
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
        if self.is_dry_run:
            msg = f"[BROKER] MOCK SUPER ORDER for {symbol}. EntryLimit={entry_limit_price} (LTP={ltp}), SL={sl_price}, TGT={tgt_price}"
            logger.info(msg)
            if self.activity_logs is not None:
                self.activity_logs.appendleft(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")
            logger.info(f"Native Super Order Placed: mock_bo_123")
            return {
                'side': 'CALL' if 'CE' in symbol else 'PUT',
                'entry_id': 'mock_bo_123',
                'symbol': symbol,
                'security_id': sec_id,
                'sl_id': "NATIVE_BO", 
                'tgt_id': "NATIVE_BO",
                'tgt_price': tgt_price,
                'sl_price': sl_price,
                'is_super_order': True,
                'quantity': so_leg['quantity']
            }

        resp = self.broker.place_super_order(symbol, so_leg)
        
        if resp.get('success'):
            msg = f"Native Super Order Placed: {resp.get('order_id')}"
            logger.info(msg)
            if self.activity_logs is not None:
                self.activity_logs.appendleft(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")
            return {
                'side': 'CALL' if 'CE' in symbol else 'PUT',
                'entry_id': resp.get('order_id'),
                'symbol': symbol,
                'security_id': sec_id,
                'sl_id': "NATIVE_BO", 
                'tgt_id': "NATIVE_BO",
                'tgt_price': tgt_price,
                'sl_price': sl_price,
                'is_super_order': True,
                'quantity': so_leg['quantity']
            }
        logger.warning(f"Native Super Order Failed: {resp.get('error')}. Falling back to Simulation.")
        return None

    def _execute_simulated_bracket(self, underlying, symbol, security_id, itm_data, params, leg_data, ltp=None):
        """Places a protected entry and stores metadata for async SL/Target placement via webhook."""
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
        side = 'CALL' if 'CE' in symbol else 'PUT'
        
        # Store metadata for Webhook Callback (Wait for TRADED status)
        pending_data = {
            'underlying': underlying,
            'side': side,
            'symbol': symbol,
            'security_id': security_id,
            'itm_data': itm_data,
            'params': params,
            'quantity': order_leg['quantity']
        }
        
        key = f"pending_bracket:{entry_id}"
        if self.use_redis:
            self.r.setex(key, 86400, json.dumps(pending_data))
        else:
            self.memory_store[key] = pending_data
            
        logger.info(f"Entry Sent: {entry_id}. Awaiting Webhook fill to place SL/Target.")
        
        return {
            'side': side,
            'entry_id': entry_id,
            'symbol': symbol,
            'security_id': security_id,
            'status': 'PENDING_FILL'
        }

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
                    self._modify_standard_leg(underlying, oid, otype, ltp, state, order)

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
        
        # 3. Clear Conditional Orders to prevent interlocking
        self._cancel_active_conditional_orders(underlying, state)
        
        # 4. Clear state
        self._clear_state(underlying)
        return {"action": "EXIT_MARKET", "symbol": symbol, "quantity": qty}

    def _modify_super_leg(self, oid, leg_name, ltp, order_data):
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

    def _modify_standard_leg(self, underlying, oid, otype, ltp, state, order_data):
        """Modifies a standard bracket leg."""
        is_so = state.get('is_super_order', False)
        # Standard brackets are always trailing-based logic
        offset = 5
        params = self._get_params(underlying)
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

