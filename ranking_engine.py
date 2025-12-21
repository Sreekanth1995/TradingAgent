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

    def _get_active_instruments(self, underlying, side):
        """Returns a set of active instrument keys for a given underlying and side."""
        if self.use_redis:
            val = self.r.smembers(f"active_instruments:{underlying}:{side}")
            return set(val) if val else set()
        else:
            return self.memory_store.get(f"active_instruments:{underlying}:{side}", set())

    def _add_active_instrument(self, underlying, side, instrument_key):
        """Adds an instrument to the active set for a given side."""
        if self.use_redis:
            self.r.sadd(f"active_instruments:{underlying}:{side}", instrument_key)
        else:
            if f"active_instruments:{underlying}:{side}" not in self.memory_store:
                self.memory_store[f"active_instruments:{underlying}:{side}"] = set()
            self.memory_store[f"active_instruments:{underlying}:{side}"].add(instrument_key)

    def _remove_active_instrument(self, underlying, side, instrument_key):
        """Removes an instrument from the active set for a given side."""
        if self.use_redis:
            self.r.srem(f"active_instruments:{underlying}:{side}", instrument_key)
        else:
            active_set = self.memory_store.get(f"active_instruments:{underlying}:{side}", set())
            if instrument_key in active_set:
                active_set.remove(instrument_key)

    def process_signal(self, instrument_key, transaction_type, timeframe, leg_data):
        """
        Main logic for Multi-Timeframe Ranking.
        Buy (+1) | Sell (-Timeframe)
        Includes Mutual Exclusion: Cannot open a side if the opposite side is active.
        """
        current_rank = self._get_rank(instrument_key)
        new_rank = current_rank
        action_taken = "NONE"

        # 1. Identify Side and Underlying for Mutual Exclusion
        option_type = leg_data.get('option_type') # 'CE' or 'PE'
        underlying = leg_data.get('symbol')      # 'NIFTY', etc.
        
        # Determine counterpart
        counterpart_side = None
        if option_type == 'CE':
            counterpart_side = 'PE'
        elif option_type == 'PE':
            counterpart_side = 'CE'

        # Apply Logic
        if transaction_type == "B":
            # Mutual Exclusion Check: Only for NEW entries
            if current_rank <= 0 and counterpart_side and underlying:
                active_counterparts = self._get_active_instruments(underlying, counterpart_side)
                if active_counterparts:
                    logger.warning(f"MUTUAL EXCLUSION: Blocking {option_type} entry for {underlying} because {counterpart_side} is active: {active_counterparts}")
                    return {
                        "symbol": instrument_key,
                        "old_rank": current_rank,
                        "new_rank": current_rank,
                        "action": "BLOCKED_BY_MUTUAL_EXCLUSION"
                    }

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
                    if option_type and underlying:
                        self._add_active_instrument(underlying, option_type, instrument_key)
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
                     if option_type and underlying:
                         self._remove_active_instrument(underlying, option_type, instrument_key)
                else:
                    logger.critical(f"SELL FAILED: {resp['error']}. Keeping Rank at {current_rank} (STUCK POSITION).")
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
        if action_taken not in ["FAILED_ENTRY", "FAILED_EXIT", "BLOCKED_BY_MUTUAL_EXCLUSION"]:
            self._set_rank(instrument_key, new_rank)
        else:
             logger.info(f"Skipping State Update due to Failure/Block. Rank remains {self._get_rank(instrument_key)}")
        
        return {
            "symbol": instrument_key,
            "old_rank": current_rank,
            "new_rank": new_rank,
            "action": action_taken
        }
