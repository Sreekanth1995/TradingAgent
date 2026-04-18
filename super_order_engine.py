import os
import logging
import json
import time
from datetime import datetime
import pytz

IST = pytz.timezone('Asia/Kolkata')

logger = logging.getLogger(__name__)

class SuperOrderEngine:
    """
    Streamlined Native Super Order Engine.
    Handles Native Bracket Orders using Dhan API v2.
    Operations: 1. Place, 2. Modify, 3. Cancel, 4. Exit
    """
    def __init__(self, broker=None, is_dry_run=False, redis_client=None, activity_logs=None):
        self.broker = broker
        self.is_dry_run = is_dry_run
        self.r = redis_client
        self.activity_logs = activity_logs
        self.use_redis = False
        self.memory_store = {}
        
        # Risk Defaults
        self.configs = {
            "DEFAULT": {"target": 55, "sl": 20, "trailing": 20, "slippage_buffer": 1.0}
        }

        if self.r:
            try:
                self.r.ping()
                logger.info("✅ SuperOrderEngine: Using shared Redis connection")
                self.use_redis = True
            except Exception as e:
                logger.warning(f"SuperOrderEngine: Redis failed ({e}). Using memory.")
        else:
            logger.warning("SuperOrderEngine: No Redis client. Using memory.")

    # --- State Management ---
    def _get_state(self, underlying):
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
        self._set_state(underlying, {'side': 'NONE', 'last_signal': 'NONE'})
        logger.info(f"State cleared for {underlying}")

    def _add_activity_log(self, msg, prefix=""):
        from datetime import datetime
        timestamp = datetime.now().strftime('%H:%M:%S')
        full_msg = f"[{timestamp}] {prefix}{msg}"
        if self.activity_logs is not None:
            self.activity_logs.appendleft(full_msg)
        if self.r:
            try:
                pipe = self.r.pipeline()
                pipe.lpush("activity_logs", full_msg)
                pipe.ltrim("activity_logs", 0, 49)
                pipe.execute()
            except Exception as e:
                logger.error(f"Redis log failed: {e}")

    # --- 1. Place Native Super Order ---
    def place_super_order(self, underlying, side, quantity, itm, target_price, stop_loss_price, trailing_jump=1.0, entry_price=0, mode='MARKET'):
        """
        Calculates levels and places a Native Super Order using the provided instrument (itm).
        Expects actual absolute prices for target_price, stop_loss_price, and entry_price.
        """
        symbol = itm['symbol']
        sec_id = itm['security_id']
        
        # Final Payload update
        leg_data = {
            'transaction_type': 'BUY',
            'security_id': sec_id,
            'quantity': quantity,
            'order_type': mode,
            'price': float(entry_price) if mode == 'LIMIT' else 0.0,
            'target_price': float(target_price),
            'stop_loss_price': float(stop_loss_price),
            'trailing_jump': float(trailing_jump)
        }
        
        resp = self.broker.place_super_order(symbol, leg_data)
        if resp.get('success'):
            order_id = resp.get('order_id')
            state = {
                'side': side,
                'entry_id': order_id,
                'symbol': symbol,
                'security_id': sec_id,
                'sl_id': "NATIVE_BO",
                'tgt_id': "NATIVE_BO",
                'sl_price': stop_loss_price,
                'tgt_price': target_price,
                'quantity': quantity
            }
            self._set_state(underlying, state)
            msg = f"Native Super Order: {symbol} at ~{entry_price}. SL: {stop_loss_price}, TGT: {target_price}"
            self._add_activity_log(msg, "🚀 ")
            return {"success": True, "order_id": order_id, "state": state}
        
        return resp

    # --- 2. Modify Native Super Order ---
    def modify_super_order(self, underlying, stop_loss_price=None, target_price=None, trailing_jump=None, quantity=None, entry_price=None):
        """Updates legs of the active super order."""
        state = self._get_state(underlying)
        order_id = state.get('entry_id')
        if not order_id:
            return {"success": False, "error": "No active order found to modify"}
            
        results = []
        if stop_loss_price or trailing_jump:
            res = self.broker.modify_super_sl_leg(order_id, stop_loss_price or state.get('sl_price'), trailing_jump or 1.0)
            results.append(res)
            
        if target_price:
            res = self.broker.modify_super_target_leg(order_id, target_price)
            results.append(res)
            
        if entry_price or quantity:
            res = self.broker.modify_super_entry_leg(order_id, entry_price or 0, quantity)
            results.append(res)
            
        return {"success": True, "details": results}

    # --- 3. Cancel Super Order ---
    def cancel_super_order(self, underlying):
        """Cancels a pending native super order."""
        state = self._get_state(underlying)
        order_id = state.get('entry_id')
        if not order_id:
            return {"success": False, "error": "No active order to cancel"}
            
        resp = self.broker.cancel_super_order(order_id, 'ENTRY_LEG')
        if resp.get('success'):
            self._clear_state(underlying)
            self._add_activity_log(f"Bracket Cancelled: {state.get('symbol')}", "🚫 ")
        return resp

    # --- 4. Exit Super Order ---
    def exit_super_order(self, underlying):
        """Exits the position and cancels the bracket."""
        state = self._get_state(underlying)
        order_id = state.get('entry_id')
        if not order_id:
            return {"success": False, "error": "No active position to exit"}
            
        symbol = state.get('symbol')
        sec_id = state.get('security_id')
        qty = state.get('quantity', 1)
        
        # 1. Place Opposite Market Order to flat position
        exit_payload = {
            'transaction_type': 'SELL',
            'order_type': 'MARKET',
            'quantity': qty,
            'security_id': sec_id,
            'product_type': 'INTRADAY' # Bracket orders are always intraday
        }
        
        logger.info(f"Exiting Super Order: Placing Market Sell for {symbol}")
        exit_resp = self.broker.place_order(symbol, exit_payload)
        
        # 2. Cancel all bracket legs
        self.broker.cancel_super_order(order_id, 'ENTRY_LEG') # This kills everything if pending
        self.broker.cancel_super_order(order_id, 'TARGET_LEG')
        self.broker.cancel_super_order(order_id, 'STOP_LOSS_LEG')
        
        self._clear_state(underlying)
        self._add_activity_log(f"Position Exited: {symbol}", "🏁 ")
        
        return {"success": True, "exit": exit_resp}

    # --- Signal Router ---
    def process_signal(self, underlying, itm, signal_type, mode='MARKET', leg_data=None):
        """
        Main entry point for signals.
        itm: pre-resolved ITM contract dict from server (skips internal resolution).
        """
        state = self._get_state(underlying)
        current_side = state.get('side', 'NONE')
        leg_data = leg_data or {}

        # 1. Handle Exits (Opposite Signal)
        if (signal_type == 'S' and current_side == 'CALL') or (signal_type == 'B' and current_side == 'PUT'):
            logger.info(f"Signal: OPPOSITE for {underlying}. Exiting existing state.")
            return self.exit_super_order(underlying)

        # 2. Handle Entries
        if signal_type in ['B', 'S'] and current_side == 'NONE':
            side = 'CALL' if signal_type == 'B' else 'PUT'

            if not itm:
                return {"success": False, "error": "ITM contract not provided"}

            # Fetch LTP for the pre-resolved ITM contract
            ltp = self.broker.get_ltp(itm['security_id'])
            if not ltp:
                return {"success": False, "error": "Could not fetch LTP for ITM contract"}

            target_val = leg_data.get('target') or self.configs["DEFAULT"]["target"]
            sl_val = leg_data.get('sl') or self.configs["DEFAULT"]["sl"]
            trailing_val = leg_data.get('trailing') or self.configs["DEFAULT"]["trailing"]

            def calc_abs(val, ref_price, is_sl=False):
                if val < 100:
                    return round(ref_price * (1 - val / 100), 1) if is_sl else round(ref_price * (1 + val / 100), 1)
                return val

            tgt_price = calc_abs(target_val, ltp, is_sl=False)
            sl_price = calc_abs(sl_val, ltp, is_sl=True)
            trailing_jump = round(ltp * (trailing_val / 100), 1) if trailing_val < 50 else trailing_val
            entry_price = leg_data.get('entry_price', 0)

            return self.place_super_order(
                underlying, side, leg_data.get('quantity', 1), itm,
                target_price=tgt_price, stop_loss_price=sl_price,
                trailing_jump=trailing_jump, entry_price=entry_price, mode=mode
            )

        return {"action": "NONE", "reason": "Already in position or no action needed"}

    def find_underlying_by_order_id(self, order_id):
        """Returns the underlying name whose state has the given entry_id, or None."""
        if self.use_redis:
            keys = self.r.keys("state:*")
        else:
            keys = [k for k in self.memory_store.keys() if k.startswith("state:")]
        for k in keys:
            u = k.split(":", 1)[1] if ":" in k else k
            s = self._get_state(u)
            if s.get('entry_id') == order_id:
                return u
        return None

    def update_entry_price(self, underlying, price):
        """Stores the fill price into state (called by dhan-webhook on TRADED)."""
        state = self._get_state(underlying)
        state['entry_price'] = price
        self._set_state(underlying, state)
