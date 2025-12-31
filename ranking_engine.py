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

    def process_signal(self, underlying, transaction_type, timeframe, leg_data, now_override=None):
        """
        Refactored Index-Based Sequential Trading with Intelligent Side Inference.
        transaction_type: 'B' (Bullish/Long Bias), 'S' (Bearish/Short Bias)
        """
        # 0. Market Hours Filter: Ignore signals before 09:30 IST
        now_ist = now_override if now_override else datetime.now(IST)
        
        if now_ist.tzinfo is None:
             now_ist = IST.localize(now_ist)
             
        if now_ist.hour < 9 or (now_ist.hour == 9 and now_ist.minute < 30):
            logger.info(f"MARKET HOUR FILTER: Ignoring signal for {underlying} at {now_ist.strftime('%H:%M:%S')} IST (Pre-09:30)")
            return {
                "underlying": underlying,
                "action": "SKIPPED_MARKET_HOURS",
                "time": now_ist.strftime('%H:%M:%S'),
                "new_rank": self._get_rank(underlying),
                "side": self._get_global_side()
            }

        # Get weight for the signal's timeframe
        weight = self.timeframe_weights.get(timeframe, 1)
        current_side = self._get_global_side()
        current_rank = self._get_rank(underlying)
        new_rank = current_rank
        action_taken = "NONE"

        # 1. State: IDLE (NONE)
        if current_side == 'NONE':
            if transaction_type == "B":
                # Start CALL Trend
                new_rank = weight
                side_to_set = 'CALL'
                option_type = 'CE'
                logger.info(f"START CALL: Bullish signal ({timeframe}m) detected. Rank 0 -> {new_rank}")
            elif transaction_type == "S":
                # Start PUT Trend
                new_rank = weight
                side_to_set = 'PUT'
                option_type = 'PE'
                logger.info(f"START PUT: Bearish signal ({timeframe}m) detected. Rank 0 -> {new_rank}")
            else:
                return {"underlying": underlying, "action": "INVALID_TX"}

            # Execute Entry
            self._set_global_side(side_to_set)
            spot = leg_data.get('current_price', 0)
            itm = self.broker.get_itm_contract(underlying, option_type, spot)
            
            if itm:
                logger.info(f"OPENING {side_to_set} ({option_type}) position: {itm['symbol']} (1 Lot)")
                resp = self.broker.place_buy_order(itm['symbol'], itm)
                if resp['success']:
                    action_taken = f"OPEN_{side_to_set}"
                    # Store both symbol and security_id
                    self._set_active_contract(underlying, {
                        "symbol": itm['symbol'],
                        "security_id": itm['security_id']
                    })
                else:
                    logger.error(f"ENTRY FAILED: {resp['error']}")
                    self._set_global_side('NONE')
                    new_rank = 0
                    action_taken = "FAILED_ENTRY"
            else:
                logger.error("Failed to resolve ITM contract.")
                self._set_global_side('NONE')
                new_rank = 0
                action_taken = "FAILED_ITM"

        # 2. State: ACTIVE CALL
        elif current_side == 'CALL':
            if transaction_type == "B":
                # Pyramiding (Bullish signal in Bullish trend)
                new_rank += 1
                logger.info(f"UPHOLD CALL: Signal ({timeframe}m). Rank {current_rank} -> {new_rank}")
                action_taken = "HOLD_STRONG"
            elif transaction_type == "S":
                # Hard Exit or Decay
                if timeframe == 0:
                    new_rank = 0
                    logger.warning("HARD EXIT: Closing CALL trend immediately.")
                else:
                    new_rank -= weight
                    logger.info(f"DECAY CALL: Bearish signal ({timeframe}m). Rank {current_rank} -> {new_rank}")
                
                if new_rank <= 0 and current_rank > 0:
                    self._close_active_trend(underlying, leg_data)
                    action_taken = "CLOSE_TREND"
                    new_rank = 0
                else:
                    action_taken = "WEAKEN_HOLD"

        # 3. State: ACTIVE PUT
        elif current_side == 'PUT':
            if transaction_type == "S":
                # Pyramiding (Bearish signal in Bearish trend)
                new_rank += 1
                logger.info(f"UPHOLD PUT: Signal ({timeframe}m). Rank {current_rank} -> {new_rank}")
                action_taken = "HOLD_STRONG"
            elif transaction_type == "B":
                # Hard Exit or Decay
                if timeframe == 0:
                    new_rank = 0
                    logger.warning("HARD EXIT: Closing PUT trend immediately.")
                else:
                    new_rank -= weight
                    logger.info(f"DECAY PUT: Bullish signal ({timeframe}m). Rank {current_rank} -> {new_rank}")
                
                if new_rank <= 0 and current_rank > 0:
                    self._close_active_trend(underlying, leg_data)
                    action_taken = "CLOSE_TREND"
                    new_rank = 0
                else:
                    action_taken = "WEAKEN_HOLD"

        self._set_rank(underlying, new_rank)
        return {
            "underlying": underlying,
            "old_rank": current_rank,
            "new_rank": new_rank,
            "action": action_taken,
            "side": self._get_global_side()
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

    def _close_active_trend(self, underlying, leg_data):
        """Helper to close the active contract and reset state."""
        contract_data = self._get_active_contract(underlying)
        if contract_data:
            symbol = contract_data.get('symbol')
            # Pass the contract data (including security_id) to the broker
            logger.info(f"Exhausting trend. Closing {symbol}")
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
