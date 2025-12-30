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

    def process_signal(self, underlying, transaction_type, timeframe, leg_data, now_override=None):
        """
        Refactored Index-Based Sequential Trading with Custom Weightage.
        underlying: 'NIFTY'
        """
        # 0. Market Hours Filter: Ignore signals before 09:30 IST
        now_ist = now_override if now_override else datetime.now(IST)
        
        # If now_ist is naive, assume it's already in IST or local (not ideal, but common in sim)
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

        # 1. Manage Global Side Lock
        current_side = self._get_global_side()
        signal_side = leg_data.get('option_type') # 'CE' or 'PE'
        
        if current_side != 'NONE':
            intended_side = 'CALL' if signal_side == 'CE' else 'PUT'
            if current_side != intended_side:
                logger.info(f"FLIP-FLOP LOCK: Ignoring {signal_side} signal because we are in {current_side} mode.")
                return {"symbol": underlying, "action": f"BLOCKED_BY_{current_side}_STATE", "side": current_side}

        # 2. Handle Underlying Rank
        current_rank = self._get_rank(underlying)
        new_rank = current_rank
        action_taken = "NONE"

        if transaction_type == "B":
            if current_rank <= 0:
                new_rank = weight
                logger.info(f"Buy Signal ({timeframe}m - INITIAL, Weight:{weight}). Index {underlying} Rank {current_rank} -> {new_rank}")
            else:
                new_rank += 1
                logger.info(f"Buy Signal ({timeframe}m - ADD, Weight:{weight}). Index {underlying} Rank {current_rank} -> {new_rank}")
            
            # Entry/Modify Execution
            if current_rank <= 0 and new_rank > 0:
                side = 'CE' if signal_side == 'CE' else 'PE'
                self._set_global_side('CALL' if side == 'CE' else 'PUT')
                
                spot = leg_data.get('current_price', 0)
                itm = self.broker.get_itm_contract(underlying, side, spot)
                
                if itm:
                    # ALWAYS 1 LOT AS REQUESTED
                    logger.info(f"OPENING {side} position via ITM selection: {itm['symbol']} (1 Lot)")
                    resp = self.broker.place_buy_order(itm['symbol'], itm)
                    if resp['success']:
                        action_taken = f"OPEN_{side}"
                        self._set_active_contract(underlying, itm['symbol'])
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
                    
            elif current_rank > 0:
                action_taken = "HOLD_STRONG"

        elif transaction_type == "S":
            new_rank -= weight
            logger.info(f"Sell Signal ({timeframe}m, Weight:{weight}). Index {underlying} Rank {current_rank} -> {new_rank}")
            
            if new_rank <= 0 and current_rank > 0:
                active_contract = self._get_active_contract(underlying)
                logger.info(f"Rank for {underlying} exhausted. CLOSING {active_contract} for current trend.")
                
                if active_contract:
                    # Trigger real sell for the contract we actually bought
                    self.broker.place_sell_order(active_contract, leg_data)
                
                action_taken = "CLOSE_TREND"
                self._set_global_side('NONE')
                self._set_active_contract(underlying, None)
                new_rank = 0
            elif new_rank <= 0:
                new_rank = 0
                action_taken = "FLAT"
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

    def _get_active_contract(self, underlying):
        if self.use_redis:
            return self.r.get(f"active_contract:{underlying}")
        else:
            return self.memory_store.get(f"active_contract:{underlying}")

    def _set_active_contract(self, underlying, contract):
        if self.use_redis:
            if contract: self.r.set(f"active_contract:{underlying}", contract)
            else: self.r.delete(f"active_contract:{underlying}")
        else:
            if contract: self.memory_store[f"active_contract:{underlying}"] = contract
            else: self.memory_store.pop(f"active_contract:{underlying}", None)
