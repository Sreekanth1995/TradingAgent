import os
import logging
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
    def __init__(self, broker):
        self.broker = broker
        # Initialize Redis
        self.use_redis = False
        self.memory_store = {}
        self.last_signals = {}  # Store last signal per underlying
        
        # User Defined Timeframe Weights
        self.timeframe_weights = {
            1: 1,
            2: 1,
            3: 2,
            5: 3
        }

        if REDIS_AVAILABLE:
            redis_host = os.getenv("REDIS_HOST", "localhost")
            redis_port = int(os.getenv("REDIS_PORT", 6379))
            try:
                self.r = redis.Redis(host=redis_host, port=redis_port, decode_responses=True)
                self.r.ping()
                logger.info(f"Connected to Redis at {redis_host}:{redis_port}")
                self.use_redis = True
            except (redis.ConnectionError, NameError):
                logger.warning("Redis connection failed. Using in-memory storage (NOT PERSISTENT).")
        else:
            logger.warning("Redis library not installed. Using in-memory storage (NOT PERSISTENT).")

    def _get_rank(self, key):
        if self.use_redis:
            val = self.r.get(f"rank:{key}")
            return int(val) if val else 0
        else:
            return self.memory_store.get(key, 0)

    def _set_rank(self, key, value):
        logger.info(f"Setting Rank for {key} to {value}")
        if self.use_redis:
            self.r.set(f"rank:{key}", value)
        else:
            self.memory_store[key] = value

    def _open_new_trend(self, underlying, side, rank, leg_data, flip=False):
        """Helper to resolve ITM and place buy order."""
        option_type = 'CE' if side == 'CALL' else 'PE'
        self._set_global_side(side)
        self._set_rank(underlying, rank)
        
        spot = leg_data.get('current_price', 0)
        itm = self.broker.get_itm_contract(underlying, option_type, spot)
        
        prefix = "FLIP OPEN" if flip else "START"
        if itm:
            itm['current_price'] = spot
            logger.info(f"{prefix} {side}: {itm['symbol']} at {spot}")
            resp = self.broker.place_buy_order(itm['symbol'], itm)
            if resp['success']:
                self._set_active_contract(underlying, {
                    "symbol": itm['symbol'],
                    "security_id": itm['security_id']
                })
                return f"OPEN_{side}"
            else:
                logger.error(f"ENTRY FAILED: {resp['error']}")
                self._set_global_side('NONE')
                self._set_rank(underlying, 0)
                return "FAILED_ENTRY"
        else:
            logger.error("Failed to resolve ITM contract.")
            self._set_global_side('NONE')
            self._set_rank(underlying, 0)
            return "FAILED_ITM"

    def process_signal(self, underlying, transaction_type, timeframe, leg_data, now_override=None):
        """
        Refactored Index-Based Sequential Trading with Intelligent Side Inference.
        transaction_type: 'B' (Bullish/Long Bias), 'S' (Bearish/Short Bias)
        """
        # 0. Market Hours and Daily Square-off
        now_ist = now_override if now_override else datetime.now(IST)
        if now_ist.tzinfo is None:
             now_ist = IST.localize(now_ist)

        # 0.0 Daily Signal Reset (Ensures toggle logic starts fresh every morning)
        self._check_daily_reset(now_ist)

        is_market_open = (now_ist.hour > 9 or (now_ist.hour == 9 and now_ist.minute >= 30))
        is_market_closing = (now_ist.hour > 15 or (now_ist.hour == 15 and now_ist.minute >= 25))
             
        # Daily Square-off After 15:25 IST
        if is_market_closing:
            current_side = self._get_global_side()
            if current_side != 'NONE':
                logger.info(f"DAILY SQUARE-OFF: Time {now_ist.strftime('%H:%M:%S')} IST is past 15:25. Closing position.")
                self._close_active_trend(underlying, leg_data, now_ist)
                return {
                    "underlying": underlying,
                    "action": "DAILY_SQUARE_OFF",
                    "time": now_ist.strftime('%H:%M:%S'),
                    "new_rank": 0,
                    "side": "NONE"
                }
            return {
                "underlying": underlying,
                "action": "MARKET_CLOSED",
                "time": now_ist.strftime('%H:%M:%S'),
                "new_rank": 0,
                "side": "NONE"
            }

        # 0.2 Signal De-duplication (Toggle Logic)
        if transaction_type == "ZONE":
            last_zone = self._get_last_signal(underlying, "ZONE_STATE")
            if last_zone == timeframe:
                logger.info(f"ZONE TOGGLE: Ignoring repeat touch of {timeframe} for {underlying}")
                return {
                    "underlying": underlying,
                    "action": "SKIPPED_ZONE_TOGGLE",
                    "time": now_ist.strftime('%H:%M:%S'),
                    "new_rank": self._get_rank(underlying),
                    "side": self._get_global_side()
                }
            # Update last zone hit
            self._set_last_signal(underlying, "ZONE_STATE", timeframe)
        else:
            last_type = self._get_last_signal(underlying, timeframe)
            if last_type == transaction_type:
                logger.info(f"TOGGLE FILTER: Ignoring {transaction_type} for {underlying} on {timeframe}m (Same as last state)")
                return {
                    "underlying": underlying,
                    "action": "SKIPPED_TOGGLE",
                    "time": now_ist.strftime('%H:%M:%S'),
                    "new_rank": self._get_rank(underlying),
                    "side": self._get_global_side()
                }
            # Update last signal (toggle state) for this timeframe
            self._set_last_signal(underlying, timeframe, transaction_type)

        current_rank = self._get_rank(underlying)
        new_rank = current_rank
        action_taken = "NONE"

        # 0.3 Calculate New Rank
        weight = self.timeframe_weights.get(timeframe, 1)
        if transaction_type == "B":
            new_rank += weight
            logger.info(f"BULLISH SIGNAL ({timeframe}m): Weight {weight}. Rank {current_rank} -> {new_rank}")
        elif transaction_type == "S":
            new_rank -= weight
            logger.info(f"BEARISH SIGNAL ({timeframe}m): Weight {weight}. Rank {current_rank} -> {new_rank}")
        elif transaction_type == "ZONE":
            level = timeframe # We use timeframe field to pass the level name
            logger.info(f"ZONE LEVEL ALERT: {underlying} touched {level}")
            # Zone Decay Logic: Reduce rank magnitude by 1
            if current_rank > 0:
                new_rank -= 1
                logger.info(f"ZONE DECAY (CALL): Rank {current_rank} -> {new_rank}")
            elif current_rank < 0:
                new_rank += 1
                logger.info(f"ZONE DECAY (PUT): Rank {current_rank} -> {new_rank}")
            action_taken = "ZONE_DECAY"

        # 1. Execution Window and Order Placement
        # We only place orders AFTER 09:30 AM IST.
        if is_market_open:
            current_side = self._get_global_side()
            
            # Determine target side from signed rank
            if new_rank > 0:
                target_side = 'CALL'
            elif new_rank < 0:
                target_side = 'PUT'
            else:
                target_side = 'NONE'

            # A. If side changes (Flip or Exit)
            if target_side != current_side:
                # Close existing if any
                if current_side != 'NONE':
                    logger.info(f"TREND CHANGE: Closing {current_side} position.")
                    self._close_active_trend(underlying, leg_data, now_ist)
                
                # Open new if needed
                if target_side != 'NONE':
                    logger.info(f"TREND START: Opening {target_side} position with rank {new_rank}")
                    action_taken = self._open_new_trend(underlying, target_side, new_rank, leg_data, flip=(current_side != 'NONE'))
                else:
                    action_taken = "CLOSE_TREND"
            
            # B. If side is same but rank changed (Pyramiding/Decay)
            else:
                if target_side == 'CALL':
                    action_taken = "UPHOLD_CALL" if new_rank > current_rank else "DECAY_CALL"
                elif target_side == 'PUT':
                    action_taken = "UPHOLD_PUT" if new_rank < current_rank else "DECAY_PUT"
                
                # Catch-up logic: if market is open and it's our first signal of the day
                active_contract = self._get_active_contract(underlying)
                if not active_contract and target_side != 'NONE':
                    logger.info(f"MARKET OPEN CATCH-UP: Realizing pre-market trend {target_side} with Rank {new_rank}")
                    action_taken = self._open_new_trend(underlying, target_side, new_rank, leg_data)

        # Update persistent state
        self._set_rank(underlying, new_rank)
        # Note: _open_new_trend and _close_active_trend already handle _set_global_side('NONE') etc.
        # But for pre-market (is_market_open=False), we still need to track the intended side.
        if not is_market_open:
            if new_rank > 0:
                self._set_global_side('CALL')
                action_taken = "PREMARKET_RANK_CALL"
            elif new_rank < 0:
                self._set_global_side('PUT')
                action_taken = "PREMARKET_RANK_PUT"
            else:
                self._set_global_side('NONE')
                action_taken = "PREMARKET_NEUTRAL"

        return {
            "underlying": underlying,
            "old_rank": current_rank,
            "new_rank": new_rank,
            "action": action_taken,
            "side": self._get_global_side(),
            "time": now_ist.strftime('%H:%M:%S')
        }

    def _get_global_side(self):
        if self.use_redis:
            val = self.r.get("trading_side")
            return val if val else 'NONE'
        else:
            return self.memory_store.get("trading_side", 'NONE')

    def _set_global_side(self, side):
        logger.info(f"Global Trading Side set to: {side}")
        if self.use_redis:
            self.r.set("trading_side", side)
        else:
            self.memory_store["trading_side"] = side

    def _close_active_trend(self, underlying, leg_data, exit_time=None):
        """Helper to close the active contract and reset state."""
        contract_data = self._get_active_contract(underlying)
        if contract_data:
            symbol = contract_data.get('symbol')
            # Pass the contract data (including security_id) to the broker
            logger.info(f"Exhausting trend. Closing {symbol}")
            
            # Inject current price for PnL
            current_price = leg_data.get('current_price', 0)
            contract_data['current_price'] = current_price
            
            self.broker.place_sell_order(symbol, contract_data)
        
        self._set_global_side('NONE')
        self._set_active_contract(underlying, None)

    def _check_daily_reset(self, now_ist):
        """Checks if a new day has started and clears timeframe toggles if so."""
        current_date = now_ist.date().isoformat()
        last_reset = self._get_last_reset_date()
        
        if last_reset != current_date:
            logger.info(f"NEW DAY DETECTED ({current_date}). Clearing signal history/toggles.")
            
            # Clear all timeframe toggles
            if self.use_redis:
                keys = self.r.keys("last_signal:*")
                if keys:
                    self.r.delete(*keys)
            else:
                self.last_signals = {}
                
            # Clear zone state specifically
            if self.use_redis:
                self.r.delete("last_signal:ZONE_STATE")
            
            self._set_last_reset_date(current_date)

    def _get_last_reset_date(self):
        if self.use_redis:
            return self.r.get("last_reset_date")
        else:
            return self.memory_store.get("last_reset_date")

    def _set_last_reset_date(self, date_str):
        if self.use_redis:
            self.r.set("last_reset_date", date_str)
        else:
            self.memory_store["last_reset_date"] = date_str

    def _get_active_contract(self, underlying):
        import json
        if self.use_redis:
            val = self.r.get(f"active_contract:{underlying}")
            return json.loads(val) if val else None
        else:
            val = self.memory_store.get(f"active_contract:{underlying}")
            return json.loads(val) if val else None

    def _set_active_contract(self, underlying, contract_dict):
        import json
        if self.use_redis:
            if contract_dict: 
                self.r.set(f"active_contract:{underlying}", json.dumps(contract_dict))
            else: 
                self.r.delete(f"active_contract:{underlying}")
        else:
            if contract_dict: 
                self.memory_store[f"active_contract:{underlying}"] = json.dumps(contract_dict)
            else: 
                self.memory_store.pop(f"active_contract:{underlying}", None)

    def _get_last_signal(self, underlying, timeframe):
        key = f"{underlying}:{timeframe}"
        if self.use_redis:
            return self.r.get(f"last_signal:{key}")
        else:
            return self.last_signals.get(key)

    def _set_last_signal(self, underlying, timeframe, signal_type):
        key = f"{underlying}:{timeframe}"
        if self.use_redis:
            if signal_type:
                self.r.set(f"last_signal:{key}", signal_type)
            else:
                self.r.delete(f"last_signal:{key}")
        else:
            if signal_type:
                self.last_signals[key] = signal_type
            else:
                self.last_signals.pop(key, None)
