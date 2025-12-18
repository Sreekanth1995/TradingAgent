import os
import logging

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

    def process_signal(self, instrument_key, transaction_type, timeframe, leg_data):
        """
        Main logic for Multi-Timeframe Ranking.
        Buy (+1) | Sell (-Timeframe)
        """
        current_rank = self._get_rank(instrument_key)
        new_rank = current_rank
        action_taken = "NONE"

        # Apply Logic
        if transaction_type == "B":
            # Buy Logic: Hybrid (Jump Start, Slow Build)
            if current_rank <= 0:
                # First Entry: Set Rank to Timeframe (e.g. 2m -> Rank 2)
                new_rank = timeframe
                logger.info(f"Buy Signal ({timeframe}m - INITIAL). Rank {current_rank} -> {new_rank}")
            else:
                # Subsequent Entry: Add +1 only
                new_rank += 1
                logger.info(f"Buy Signal ({timeframe}m - ADD). Rank {current_rank} -> {new_rank}")
            
            # Execution Logic
            if current_rank <= 0 and new_rank > 0:
                # First Entry (crossed 0 threshold)
                logger.info(f"OPENING LONG Position for {instrument_key}")
                resp = self.broker.place_buy_order(instrument_key, leg_data)
                
                if resp['success']:
                    action_taken = "OPEN_LONG"
                else:
                    logger.error(f"BUY FAILED: {resp['error']}. Reverting Rank to {current_rank}.")
                    new_rank = current_rank # ROLLBACK: Pretend signal never happened
                    action_taken = "FAILED_ENTRY"
                    
            elif current_rank > 0:
                # Already open, maybe pyramid?
                logger.info(f"Rank increased {current_rank} -> {new_rank}. Holding/Pyramiding.")
                action_taken = "HOLD_STRONG"

        elif transaction_type == "S":
            # Sell Logic: -Timeframe
            decrement = timeframe
            new_rank -= decrement
            logger.info(f"Sell Signal ({timeframe}m). Rank {current_rank} -> {new_rank}")
            
            # Trigger Logic
            if new_rank <= 0 and current_rank > 0:
                # Close Condition met
                logger.info(f"Rank dropped to {new_rank} <= 0. CLOSING Position for {instrument_key}")
                resp = self.broker.place_sell_order(instrument_key, leg_data)
                
                if resp['success']:
                     new_rank = 0 # Clamp to 0
                     action_taken = "CLOSE_LONG"
                else:
                    logger.critical(f"SELL FAILED: {resp['error']}. Keeping Rank at {current_rank} (STUCK POSITION).")
                    # If sell fails, we are technically still holding the position.
                    # We should probably NOT decrement the rank so the system knows we are still exposed.
                    # Or we should keep the rank low but flag an error?
                    # Safer to Revert Rank so the next sell signal tries again.
                    new_rank = current_rank # ROLLBACK
                    action_taken = "FAILED_EXIT"

            elif new_rank <= 0 and current_rank <= 0:
                 # Already flat
                 new_rank = 0
                 action_taken = "FLAT"
            else:
                # Still positive (e.g., 4 -> 3)
                logger.info(f"Rank dropped but still > 0. Holding.")
                action_taken = "WEAKEN_HOLD"

        # Save State (Only if order succeeded or no trade was required)
        if action_taken not in ["FAILED_ENTRY", "FAILED_EXIT"]:
            self._set_rank(instrument_key, new_rank)
        else:
             logger.info(f"Skipping State Update due to Failure. Rank remains {self._get_rank(instrument_key)}")
        
        return {
            "symbol": instrument_key,
            "old_rank": current_rank,
            "new_rank": new_rank,
            "action": action_taken
        }
