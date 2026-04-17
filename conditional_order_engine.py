import os
import logging
import json
import time

try:
    import redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False

logger = logging.getLogger(__name__)

class ConditionalOrderEngine:
    """
    Manages GTT (Good Till Triggered) and Alert-based Conditional Orders 
    for Index levels and Premium bounds.
    """
    def __init__(self, broker=None, is_dry_run=False, redis_client=None):
        self.broker = broker
        self.is_dry_run = is_dry_run
        self.redis = redis_client
        self.use_redis = False
        self.memory_store = {}

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
                logger.info("✅ ConditionalOrderEngine: Connected to Redis successfully")
                self.use_redis = True
            except Exception as e:
                logger.warning(f"ConditionalOrderEngine: Redis connection failed ({e}). Using in-memory storage.")
        else:
            logger.warning("ConditionalOrderEngine: Redis library not installed. Using in-memory storage.")

    # --- State Management ---
    def _get_state(self, underlying):
        key = f"cond_state:{underlying}"
        if self.use_redis:
            val = self.r.get(key)
            return json.loads(val) if val else {'side': 'NONE', 'last_signal': 'NONE'}
        else:
            return self.memory_store.get(key, {'side': 'NONE', 'last_signal': 'NONE'})

    def _set_state(self, underlying, state):
        key = f"cond_state:{underlying}"
        if self.use_redis:
            self.r.set(key, json.dumps(state))
        else:
            self.memory_store[key] = state

    # --- Pending Protection Helpers ---
    def store_pending_protection(self, order_id, metadata, ttl=86400):
        """
        Stores SL/Target levels for an order that hasn't filled yet.
        """
        key = f"pending_prot:{order_id}"
        if self.use_redis:
            self.r.setex(key, ttl, json.dumps(metadata))
        else:
            self.memory_store[key] = metadata
        logger.info(f"Stored pending Protection for Order {order_id}: {metadata}")

    def get_pending_protection(self, order_id):
        """Retrieves and clears pending protection."""
        key = f"pending_prot:{order_id}"
        if self.use_redis:
            val = self.r.get(key)
            if val:
                self.r.delete(key)
                return json.loads(val)
        else:
            val = self.memory_store.get(key)
            if val:
                del self.memory_store[key]
                return val
        return None

    def cancel_active_conditional_orders(self, underlying, state=None):
        """Cancels associated Dhan Alert triggers (GTT) if they exist in state."""
        if state is None:
            state = self._get_state(underlying)
            
        alert_keys = (
            'conditional_target_alert_id', 'conditional_sl_alert_id',
            'idx_target_alert_id', 'idx_sl_alert_id'
        )
        for key in alert_keys:
            alert_id = state.get(key)
            if alert_id:
                logger.info(f"Cleanup: Cancelling conditional order {alert_id} for {underlying}")
                self.broker.cancel_conditional_order(alert_id)
                state[key] = None
                
        self._set_state(underlying, state)

    def _clear_state(self, underlying):
        """Wipes the conditional state cleanly after exit."""
        state = self._get_state(underlying)
        self.cancel_active_conditional_orders(underlying, state)
        new_state = {'side': 'NONE', 'last_signal': 'NONE'}
        self._set_state(underlying, new_state)

    def handle_signal(self, signal_type, leg_data):
        """
        Independent entry/exit logic for Conditional Engine.
        Places basic entry orders without Super Order brackets.
        """
        underlying = leg_data.get('underlying', 'BASE')
        state = self._get_state(underlying)
        
        # Access provided Context
        itm = leg_data.get('itm')
        idx_sec_id = leg_data.get('idx_sec_id')
        spot_index = float(leg_data.get('spot_index', 0.0))
        
        if signal_type in ['B', 'S']:
            if not itm:
                return {"status": "error", "message": f"Missing ITM context for {underlying} {signal_type}"}
                
            symbol = itm['symbol']
            sec_id = itm['security_id']
            qty = leg_data.get('quantity', 1)
            
            order_payload = itm.copy()
            order_payload.update({
                'quantity': qty,
                'order_type': 'MARKET',
                'price': 0.0
            })
            
            logger.info(f"Conditional Engine: Placing Naked Entry for {symbol}")
            resp = self.broker.place_buy_order(symbol, order_payload)
            if resp.get('success') or resp.get('order_id'):
                state.update({
                    'side': 'CALL' if signal_type == 'B' else 'PUT',
                    'symbol': symbol,
                    'security_id': sec_id,
                    'idx_sec_id': idx_sec_id,
                    'entry_id': resp.get('order_id'),
                    'quantity': qty,
                    'last_signal': signal_type
                })
                self._set_state(underlying, state)
                return {"status": "success", "order_id": resp.get('order_id'), "symbol": symbol, "action": "OPENED_CONDITIONAL"}
            return {"status": "error", "message": f"Entry failed: {resp.get('error')}"}
            
        elif signal_type in ['LONG_EXIT', 'SHORT_EXIT']:
            target_side = 'CALL' if signal_type == 'LONG_EXIT' else 'PUT'
            if state.get('side') == target_side:
                logger.info(f"Conditional Engine: Exiting {target_side} for {underlying}")
                sec_id = state.get('security_id')
                if sec_id:
                    # Clean up conditional orders immediately
                    self.cancel_active_conditional_orders(underlying, state)
                    
                    # Ensure position is sold
                    sym = state.get('symbol')
                    qty_lots = state.get('quantity', 1)
                    
                    order_payload = {
                        'security_id': sec_id,
                        'quantity': qty_lots,
                        'transaction_type': 'SELL',
                        'order_type': 'MARKET',
                        'product_type': 'MARGIN'
                    }
                    self.broker.place_order(sym, order_payload)
                self._clear_state(underlying)
                return {"status": "success", "action": f"CLOSED_CONDITIONAL_{target_side}"}
            return {"status": "error", "message": "No matching position to exist"}
            
        return {"status": "error", "message": "Unsupported signal type"}

    # --- Core Logic ---
    def set_index_boundaries(self, underlying, target_level, sl_level, quantity=None):
        """
        Places SL and Target GTT index bounds.
        """
        try:
            state = self._get_state(underlying)
            if state.get('side', 'NONE') == 'NONE':
                return {"status": "error", "message": "No open position to protect"}

            opt_sec_id = state.get('security_id')
            qty = int(quantity or state.get('quantity', 1))
            idx_sec_id = state.get('idx_sec_id')
            
            if not idx_sec_id or not opt_sec_id:
                return {"status": "error", "message": "Could not resolve Index or Option security IDs from state"}

            lot_size = self.broker.lot_map.get(str(opt_sec_id), 1)
            actual_qty = qty * lot_size
            side = state.get('side') # CALL or PUT
            
            if side == 'CALL':
                tgt_op, sl_op = "ABOVE", "BELOW"
            else:
                tgt_op, sl_op = "BELOW", "ABOVE"

            # Cleanup existing GTTs
            self.cancel_active_conditional_orders(underlying, state)

            # Place SL GTT FIRST to get its ID
            sl_res = self.broker.place_conditional_order(
                sec_id=opt_sec_id,
                exchange_seg="NSE_FNO",
                quantity=actual_qty,
                operator=sl_op,
                comparing_value=float(sl_level),
                transaction_type="SELL",
                product_type="MARGIN",
                trigger_sec_id=idx_sec_id
            )
            
            if not sl_res.get('success'):
                logger.warning(f"GTT SL placement failed ({sl_res.get('error')}). Using Polling Protection Fallback.")
            else:
                sl_alert_id = sl_res.get('alert_id')
                state['idx_sl_alert_id'] = sl_alert_id
            
            # Place Target Dummy GTT if possible
            tgt_res = self.broker.place_conditional_order(
                sec_id="11006", # LiquidBees
                exchange_seg="NSE_EQ",
                quantity=1,
                operator=tgt_op,
                comparing_value=float(target_level),
                transaction_type="BUY",
                product_type="CNC",
                trigger_sec_id=idx_sec_id
            )
            
            if not tgt_res.get('success'):
                logger.warning(f"GTT Target placement failed ({tgt_res.get('error')}). Using Polling Protection Fallback.")
            else:
                state['idx_target_alert_id'] = tgt_res.get('alert_id')

            # MANDATORY: Save levels to state regardless of broker error for polling monitor
            state['idx_target_level'] = float(target_level)
            state['idx_sl_level'] = float(sl_level)
            self._set_state(underlying, state)

            return {
                "status": "success", 
                "message": "Boundaries saved. Polling Protection Active.",
                "gtt_error": sl_res.get('error') if not sl_res.get('success') else None
            }
        except Exception as e:
            logger.error(f"Internal Boundary Setting Error: {e}")
            return {"status": "error", "message": str(e)}

    def monitor_positions(self):
        """
        Background monitor: Fetches LTP for active indices and exits trades if SL/Target hit.
        This bypasses the need for broker-side GTT Alerts.
        """
        try:
            active_keys = []
            if self.use_redis:
                active_keys = self.r.keys("cond_state:*")
            else:
                active_keys = list(self.memory_store.keys())

            for key in active_keys:
                underlying = key.split(':')[-1] if ':' in key else key
                state = self._get_state(underlying)
                
                if state.get('side', 'NONE') == 'NONE': continue
                
                idx_id = state.get('idx_sec_id')
                sl_level = state.get('idx_sl_level')
                target_level = state.get('idx_target_level')
                side = state.get('side')
                
                if not idx_id or sl_level is None or target_level is None:
                    continue
                
                # Fetch Index LTP
                try:
                    current_ltp = self.broker.get_ltp(idx_id, exchange_segment="IDX_I")
                    if not current_ltp: continue
                    
                    hit = False
                    reason = ""
                    
                    if side == 'CALL':
                        if current_ltp >= target_level:
                            hit, reason = True, "TARGET_HIT"
                        elif current_ltp <= sl_level:
                            hit, reason = True, "SL_HIT"
                    else: # PUT
                        if current_ltp <= target_level:
                            hit, reason = True, "TARGET_HIT"
                        elif current_ltp >= sl_level:
                            hit, reason = True, "SL_HIT"
                            
                    if hit:
                        msg = f"🛡️ [POLLING MONITOR] {underlying} Index {reason} at {current_ltp}! (Tgt={target_level}, SL={sl_level})"
                        logger.info(msg)
                        from server import _add_activity_log
                        _add_activity_log(msg, "🚨 ")
                        
                        # Trigger exit signal
                        exit_signal = "LONG_EXIT" if side == 'CALL' else "SHORT_EXIT"
                        self.handle_signal(exit_signal, {'underlying': underlying})
                except Exception as monitor_err:
                    logger.error(f"Error monitoring {underlying}: {monitor_err}")
                    
        except Exception as e:
            logger.error(f"Monitor Loop Error: {e}")

    def handle_postback(self, data):
        """
        Handles Dhan Postback notifications specifically related to Condition Alerts.
        """
        try:
            user_note = data.get('userNote') or (data.get('data') or {}).get('userNote')
            alert_id = str(data.get('alertId') or (data.get('data') or {}).get('alertId'))
            order_status = data.get('orderStatus')
            order_id = data.get('orderId')
            
            # 1. Handle Order Fill (TRADED) status mapping for Entry
            if order_status == "TRADED" and order_id:
                logger.info(f"Order {order_id} TRADED. Checking for pending conditional triggers.")
                pending = self.get_pending_protection(order_id)
                if pending:
                    # Update entry price into cond_state
                    traded_price = data.get('tradedPrice') or (data.get('data') or {}).get('tradedPrice')
                    if traded_price:
                        state = self._get_state(pending['underlying'])
                        state['entry_price'] = float(traded_price)
                        self._set_state(pending['underlying'], state)

                    logger.info(f"Triggering GTT placement for filled order {order_id} ({pending['underlying']})")
                    gtt_res = self.set_index_boundaries(
                        underlying=pending['underlying'],
                        target_level=pending['target_level'],
                        sl_level=pending['sl_level'],
                        quantity=pending['quantity']
                    )
                    logger.info(f"Fill-Triggered GTT Result: {gtt_res}")
                return {"status": "success", "source": "order_fill"}

            if not alert_id or alert_id == "None":
                return {"status": "ignored", "message": "No alertId found"}

            logger.info(f"Dhan Postback received. alertId: {alert_id}, userNote: {user_note}")
            
            # Identify which instrument this belongs to by checking active states
            # This logic avoids hardcoding index names
            active_keys = (self.r.keys("cond_state:*") if self.use_redis else self.memory_store.keys())
            
            for key in active_keys:
                # Extract underlying from key (state:SYMBOL or cond_state:SYMBOL)
                underlying = key.split(':')[-1]
                state = self._get_state(underlying)
                # Match target alert ID
                is_target_hit = (state.get('idx_target_alert_id') == alert_id)
                
                if is_target_hit:
                    logger.info(f"Target Alert Hit for {underlying}! Triggering SL modification.")
                    # Use SL ID from user_note if available (stateless) or dictionary state fallback
                    sl_alert_id = user_note if (user_note and len(user_note) > 5) else state.get('idx_sl_alert_id')
                    
                    if sl_alert_id:
                        idx_id = state.get('idx_sec_id')
                        current_idx_ltp = self.broker.get_ltp(idx_id, exchange_segment="IDX_I") if idx_id else None
                        
                        if current_idx_ltp:
                            # Update SL dynamically tracking market movements
                            res = self.broker.modify_conditional_order(
                                alert_id=sl_alert_id,
                                quantity=state.get('quantity', 1) * self.broker.lot_map.get(str(state.get('security_id')), 1),
                                comparing_value=current_idx_ltp
                            )
                            logger.info(f"SL Modification result for {underlying} using ID {sl_alert_id}: {res}")
                    
                    state['idx_target_alert_id'] = None
                    self._set_state(underlying, state)
                    target_found = True
                    break
            
            if not target_found:
                 logger.debug(f"AlertId {alert_id} not mapped to any active target.")

            return {"status": "success"}

        except Exception as e:
            logger.error(f"Dhan Conditional Postback Error: {e}")
            return {"status": "error", "message": str(e)}
