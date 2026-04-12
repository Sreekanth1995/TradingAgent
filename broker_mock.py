import logging
import random
import time
from datetime import datetime

logger = logging.getLogger(__name__)

class MockDhanClient:
    """
    Simulates the Dhan Broker interface for local development and testing.
    Provides jittery price movements and managed mock positions.
    """
    def __init__(self):
        logger.info("🛠️ initializing Mock Dhan Client...")
        self.mock_positions = []
        # Base prices for indices
        self.prices = {
            "13": 24500.0, # NIFTY
            "25": 52300.0, # BANKNIFTY
            "27": 22400.0  # FINNIFTY
        }
        # Prices for specific options (sid -> price)
        self.option_prices = {}
        # Active exits: sid -> {target, sl, symbol, side}
        self.active_exits = {}
        # Completed trades ready for persistence
        self.completed_trades = []
        
        self.scrip_loaded = True
        self.dry_run = False # Irrelevant in mock mode but kept for compatibility

    def get_ltp(self, security_id, exchange_segment=None):
        """Returns a jittery price for any security ID and checks for SL/Target hits."""
        sid = str(security_id)
        
        # Determine base price
        if sid in self.prices:
             base = self.prices[sid]
        elif sid in self.option_prices:
             base = self.option_prices[sid]
        else:
             # Default for unknown options
             base = 100.0
             self.option_prices[sid] = base
        
        # Apply Jitter (+/- 0.05% to 0.4% - higher jitter for testing)
        jitter_pct = random.uniform(-0.004, 0.004)
        price = base * (1 + jitter_pct)
        price = round(price, 2)
        
        # Update stored price
        if sid in self.prices:
            self.prices[sid] = price
        else:
            self.option_prices[sid] = price
            
        # --- Check for SL/Target Hits ---
        if sid in self.active_exits:
            exit_data = self.active_exits[sid]
            target = exit_data.get('target')
            sl = exit_data.get('sl')
            side = exit_data.get('side', 'CALL')
            symbol = exit_data.get('symbol', sid)
            
            triggered = False
            reason = ""
            
            if side == 'CALL':
                if price >= target:
                    triggered, reason = True, "TARGET_HIT"
                elif price <= sl:
                    triggered, reason = True, "SL_HIT"
            else: # PUT
                if price <= target:
                    triggered, reason = True, "TARGET_HIT"
                elif price >= sl:
                    triggered, reason = True, "SL_HIT"
            
            if triggered:
                logger.info(f"🚨 [MOCK EXIT] {reason} for {symbol} | Price={price} (Tgt={target}, SL={sl})")
                self._trigger_mock_exit(sid, price, reason)
                
        return price

    def _trigger_mock_exit(self, security_id, exit_price, reason):
        """Removes a position, its exits, and archives the trade info."""
        sid = str(security_id)
        
        # 1. Capture final performance
        pos_info = next((p for p in self.mock_positions if str(p.get('securityId')) == sid), None)
        if pos_info:
            entry_price = float(pos_info.get('averagePrice', 0))
            qty = int(pos_info.get('netQty', 0))
            
            pnl_abs = (exit_price - entry_price) * qty
            pnl_pct = ((exit_price / entry_price) - 1) * 100 if entry_price > 0 else 0.0
            
            self.completed_trades.append({
                "underlying": sid.split('_')[1] if 'SID' in sid else "NIFTY", # Fallback logic
                "symbol": pos_info.get('tradingSymbol'),
                "side": "CALL" if "CE" in pos_info.get('tradingSymbol', '') else "PUT",
                "qty": qty,
                "entry_price": round(entry_price, 2),
                "exit_price": round(exit_price, 2),
                "pnl_abs": round(pnl_abs, 2),
                "pnl_pct": round(pnl_pct, 2),
                "reason": reason,
                "exit_time": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            })

        # 2. Cleanup
        self.mock_positions = [p for p in self.mock_positions if str(p.get('securityId')) != sid]
        if sid in self.active_exits:
            del self.active_exits[sid]
        logger.info(f"✅ [MOCK EXIT] Cleaned up and archived position {sid}")

    def get_completed_trades(self):
        """Returns and clears the recently completed trades."""
        trades = self.completed_trades[:]
        self.completed_trades = []
        return trades

    def place_super_order(self, symbol, leg_data):
        """
        Simulates a Dhan Super Order (Bracket Order).
        Captures target and SL prices for simulation.
        """
        sec_id = leg_data.get('security_id')
        if not sec_id:
             sec_id = "MOCK_SO_" + str(random.randint(1000, 9999))
             
        target_price = leg_data.get('target_price')
        sl_price = leg_data.get('stop_loss_price')
        qty = int(leg_data.get('quantity', 1))
        
        # Determine side from symbol
        side = 'CALL' if 'CE' in symbol.upper() else 'PUT'
        
        logger.info(f"🚀 [MOCK BROKER] Super Order for {symbol} | Qty={qty}, SL={sl_price}, Tgt={target_price}")
        
        # Store exit state
        self.active_exits[str(sec_id)] = {
            'target': target_price,
            'sl': sl_price,
            'symbol': symbol,
            'side': side
        }
        
        # Add to positions
        entry_price = self.get_ltp(sec_id)
        self.mock_positions.append({
            "tradingSymbol": symbol,
            "securityId": sec_id,
            "averagePrice": entry_price,
            "netQty": qty * 50,
            "positionType": "LONG",
            "realizedProfit": 0.0,
            "unrealizedProfit": 0.0
        })
        
        return {"success": True, "order_id": "MOCK_SO_123"}

    def get_positions(self):
        """Returns the current list of mock positions."""
        return self.mock_positions

    def place_order(self, symbol, leg_data):
        """Simulates placing an order by updating mock_positions."""
        transaction_type = leg_data.get('transaction_type', 'BUY')
        qty = int(leg_data.get('quantity', 1))
        sec_id = leg_data.get('security_id', "MOCK_" + str(random.randint(1000, 9999)))
        
        logger.info(f"[MOCK BROKER] Placed {transaction_type} order for {symbol} (Qty: {qty})")
        
        if transaction_type == "BUY":
            # Add new position
            entry_price = self.get_ltp(sec_id)
            self.mock_positions.append({
                "tradingSymbol": symbol,
                "securityId": sec_id,
                "averagePrice": entry_price,
                "netQty": qty * 50, # Assume standard lot size
                "positionType": "LONG",
                "realizedProfit": 0.0,
                "unrealizedProfit": 0.0
            })
        elif transaction_type == "SELL":
            # Remove positions matching symbol
            self.mock_positions = [p for p in self.mock_positions if p['tradingSymbol'] != symbol]
            
        return {"status": "success", "data": {"orderId": f"MOCK_{random.randint(100000, 999999)}"}}

    def place_buy_order(self, symbol, leg_data):
        leg_data['transaction_type'] = 'BUY'
        return self.place_order(symbol, leg_data)

    def place_sell_order(self, symbol, leg_data):
        leg_data['transaction_type'] = 'SELL'
        return self.place_order(symbol, leg_data)

    def get_itm_contract(self, underlying, side, spot_price):
        """Returns dummy ITM contract data."""
        atm = round(spot_price / 50) * 50
        strike = atm - 50 if side == 'CE' else atm + 50
        sec_id = f"SID_{underlying}_{int(strike)}_{side}"
        
        return {
            "security_id": sec_id,
            "strike": strike,
            "expiry": datetime.now().strftime('%Y-%m-%d'),
            "symbol": f"{underlying}_MOCK_{int(strike)}_{side}"
        }

    def cancel_order(self, order_id):
        return {"success": True}

    def get_order_status(self, order_id):
        return {"orderStatus": "TRADED", "averagePrice": 100.0}

    def get_pending_orders(self, security_id=None):
        return []

    def get_super_orders(self, security_id=None):
        return []

    def place_conditional_order(self, sec_id, exchange_seg, quantity, operator, comparing_value, **kwargs):
        logger.info(f"[MOCK BROKER] GTT Created: {operator} @ {comparing_value}")
        return {"success": True, "alert_id": f"GTT_{random.randint(1000, 9999)}", "error": None}

    def kill_all_gtt(self, sec_id):
        return {"success": True}

    def is_expiry_day(self, underlying):
        return False
