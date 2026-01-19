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
            5: 2,
            8: 3
        }

        if REDIS_AVAILABLE:
            redis_url = os.getenv("REDIS_URL")
            try:
                if redis_url:
                    self.r = redis.from_url(redis_url, decode_responses=True)
                    logger.info("RankingEngine: Connecting to Redis using REDIS_URL")
                else:
                    redis_host = os.getenv("REDIS_HOST", "localhost")
                    redis_port = int(os.getenv("REDIS_PORT", 6379))
                    self.r = redis.Redis(host=redis_host, port=redis_port, decode_responses=True)
                    logger.info(f"RankingEngine: Connecting to Redis at {redis_host}:{redis_port}")
                
                self.r.ping()
                logger.info("✅ RankingEngine: Connected to Redis successfully")
                self.use_redis = True
            except Exception as e:
                logger.warning(f"RankingEngine: Redis connection failed ({e}). Using in-memory storage (NOT PERSISTENT).")
        else:
            logger.warning("RankingEngine: Redis library not installed. Using in-memory storage (NOT PERSISTENT).")

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

        # 0.2 Signal De-duplication Filter (Per-Timeframe)
        last_type = self._get_last_signal(underlying, timeframe)
        if last_type == transaction_type:
            logger.info(f"DUPLICATE SIGNAL: Ignoring {transaction_type} for {underlying} on {timeframe}m (Same as last {timeframe}m signal)")
            return {
                "underlying": underlying,
                "action": "SKIPPED_DUPLICATE",
                "time": now_ist.strftime('%H:%M:%S'),
                "new_rank": self._get_rank(underlying),
                "side": self._get_global_side()
            }
        
        # Update last signal for THIS timeframe before processing
        self._set_last_signal(underlying, timeframe, transaction_type)

        # Get weight for the signal's timeframe
        weight = self.timeframe_weights.get(timeframe, 1)
        current_side = self._get_global_side()
        current_rank = self._get_rank(underlying)
        new_rank = current_rank
        action_taken = "NONE"

        # 1. State: IDLE (NONE)
        if current_side == 'NONE':
            if transaction_type == "B":
                new_rank = weight
                current_side = 'CALL'
                if is_market_open:
                    action_taken = self._open_new_trend(underlying, 'CALL', weight, leg_data)
                else:
                    self._set_global_side('CALL')
                    action_taken = "PREMARKET_RANK_CALL"
            elif transaction_type == "S":
                new_rank = weight
                current_side = 'PUT'
                if is_market_open:
                    action_taken = self._open_new_trend(underlying, 'PUT', weight, leg_data)
                else:
                    self._set_global_side('PUT')
                    action_taken = "PREMARKET_RANK_PUT"
            else:
                return {"underlying": underlying, "action": "INVALID_TX"}

        # 2. State: ACTIVE CALL
        elif current_side == 'CALL':
            if transaction_type == "B":
                new_rank += 1
                logger.info(f"UPHOLD CALL: Signal ({timeframe}m). Rank {current_rank} -> {new_rank}")
                action_taken = "HOLD_STRONG"
            elif transaction_type == "S":
                if timeframe == 0:
                    new_rank = 0
                    logger.warning("HARD EXIT: Closing CALL trend immediately.")
                else:
                    new_rank -= weight
                    logger.info(f"DECAY CALL: Bearish signal ({timeframe}m). Rank {current_rank} -> {new_rank}")
                
                if new_rank < 0:
                    flip_rank = abs(new_rank)
                    logger.info(f"FLIP CALL -> PUT: Rank {new_rank} detected. Reversing position.")
                    if is_market_open:
                        self._close_active_trend(underlying, leg_data, now_ist)
                        action_taken = self._open_new_trend(underlying, 'PUT', flip_rank, leg_data, flip=True)
                    else:
                        self._set_global_side('PUT')
                        action_taken = "PREMARKET_FLIP_PUT"
                    new_rank = flip_rank
                elif new_rank == 0:
                    if is_market_open:
                        self._close_active_trend(underlying, leg_data, now_ist)
                    else:
                        self._set_global_side('NONE')
                    action_taken = "CLOSE_TREND"
                else:
                    action_taken = "WEAKEN_HOLD"

        # 3. State: ACTIVE PUT
        elif current_side == 'PUT':
            if transaction_type == "S":
                new_rank += 1
                logger.info(f"UPHOLD PUT: Signal ({timeframe}m). Rank {current_rank} -> {new_rank}")
                action_taken = "HOLD_STRONG"
            elif transaction_type == "B":
                if timeframe == 0:
                    new_rank = 0
                    logger.warning("HARD EXIT: Closing PUT trend immediately.")
                else:
                    new_rank -= weight
                    logger.info(f"DECAY PUT: Bullish signal ({timeframe}m). Rank {current_rank} -> {new_rank}")
                
                if new_rank < 0:
                    flip_rank = abs(new_rank)
                    logger.info(f"FLIP PUT -> CALL: Rank {new_rank} detected. Reversing position.")
                    if is_market_open:
                        self._close_active_trend(underlying, leg_data, now_ist)
                        action_taken = self._open_new_trend(underlying, 'CALL', flip_rank, leg_data, flip=True)
                    else:
                        self._set_global_side('CALL')
                        action_taken = "PREMARKET_FLIP_CALL"
                    new_rank = flip_rank
                elif new_rank == 0:
                    if is_market_open:
                        self._close_active_trend(underlying, leg_data, now_ist)
                    else:
                        self._set_global_side('NONE')
                    action_taken = "CLOSE_TREND"
                else:
                    action_taken = "WEAKEN_HOLD"

        # 4. Catch-up Logic: If market is open but we have no active contract for the current trend
        self._set_rank(underlying, new_rank)
        
        if is_market_open and action_taken in ["HOLD_STRONG", "WEAKEN_HOLD", "NONE"]:
            active_contract = self._get_active_contract(underlying)
            current_side = self._get_global_side()
            if not active_contract and current_side != 'NONE':
                logger.info(f"MARKET OPEN CATCH-UP: Realizing pre-market trend {current_side} with Rank {new_rank}")
                action_taken = self._open_new_trend(underlying, current_side, new_rank, leg_data)

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
