import os
import json
import logging
from dotenv import load_dotenv

# Setup Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

def seed_mock_data():
    """
    Seeds local Redis or memory store with sample data for mock mode.
    """
    redis_host = os.getenv("REDIS_HOST", "localhost")
    redis_port = int(os.getenv("REDIS_PORT", 6379))
    
    # 1. Define Default Levels
    nifty_levels = {
        "TP0": {"low": 24450, "high": 24550},
        "UTP1": {"low": 24600, "high": 24650},
        "LTP1": {"low": 24350, "high": 24400}
    }
    
    try:
        # 1. Try Redis Seeding
        try:
            import redis
            r = redis.Redis(host=redis_host, port=redis_port, decode_responses=True)
            r.ping()
            logger.info(f"Connected to Redis at {redis_host}:{redis_port}")
            
            r.set("state:NIFTY_levels", json.dumps(nifty_levels))
            logger.info("✅ Seeded NIFTY Levels in Redis")
            
            # 2. Seed an initial NIFTY Position
            nifty_state = {
                "side": "CALL",
                "symbol": "NIFTY_MOCK_24500_CE",
                "security_id": "13", 
                "entry_price": 125.50,
                "quantity": 50,
                "last_signal": "BUY",
                "range_position": "ABOVE"
            }
            r.set("state:NIFTY", json.dumps(nifty_state))
            logger.info("✅ Seeded NIFTY Active Position State in Redis")
        except (ImportError, Exception) as e:
            logger.warning(f"Redis skip/fail: {e}. Moving to file-only seeding...")
            
        # 2. Save to levels.json for server persistence (ALWAYS do this for mock mode)
        with open("levels.json", "w") as f:
            json.dump({"NIFTY": nifty_levels}, f)
        logger.info("✅ Seeded levels.json")

    except Exception as e:
        logger.error(f"Critical failure seeding mock data: {e}")

if __name__ == "__main__":
    seed_mock_data()
