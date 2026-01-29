import os
import unittest
from unittest.mock import MagicMock, patch
import logging
import json
from ranking_engine import RankingEngine
from broker_dhan import DhanClient

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

class TestDeploymentReset(unittest.TestCase):
    
    @patch('redis.Redis')
    @patch('broker_dhan.DhanClient')
    def test_deployment_reset_logic(self, MockDhanClient, MockRedis):
        print("\n--- STARTING DEPLOYMENT RESET TEST (MOCKED) ---")
        
        # 1. Setup Mock Redis
        mock_r = MagicMock()
        MockRedis.return_value = mock_r
        
        # Simulate some existing data in Redis
        # We need to mock keys() and delete()
        mock_r.keys.side_effect = lambda pattern: {
            "rank:*": ["rank:NIFTY"],
            "last_signal:*": ["last_signal:NIFTY:1"],
            "active_contract:*": ["active_contract:NIFTY"]
        }.get(pattern, [])
        
        # 2. Test Reset = False (Default)
        os.environ["RESET_REDIS_ON_START"] = "false"
        broker = MockDhanClient()
        engine = RankingEngine(broker)
        
        print("[Step 1] Initialized RankingEngine with RESET_REDIS_ON_START=false")
        # Should NOT call delete or flush logic
        mock_r.delete.assert_not_called()
        print("✅ No deletions occurred when reset=false.")
        
        # Reset mock for next step
        mock_r.delete.reset_mock()
        
        # 3. Test Reset = True
        print("\n[Step 2] Initializing RankingEngine with RESET_REDIS_ON_START=true")
        os.environ["RESET_REDIS_ON_START"] = "true"
        engine_reset = RankingEngine(broker)
        
        # Should call keys() several times and delete() with the keys found
        # In _flush_redis_state:
        # 1. last_signal:* -> delete(*keys)
        # 2. rank:* -> delete(*keys)
        # 3. active_contract:* -> delete(*keys)
        # 4. trading_side -> delete("trading_side")
        # 5. last_reset_date -> delete("last_reset_date")
        
        print(f"Delete calls: {mock_r.delete.call_args_list}")
        
        # Verify specific delete calls
        mock_r.delete.assert_any_call("last_signal:NIFTY:1")
        mock_r.delete.assert_any_call("rank:NIFTY")
        mock_r.delete.assert_any_call("active_contract:NIFTY")
        mock_r.delete.assert_any_call("trading_side")
        mock_r.delete.assert_any_call("last_reset_date")
        
        print("✅ Redis delete called for all expected keys.")
        print("\n✅ DEPLOYMENT RESET TEST PASSED (MOCKED)")

    def test_memory_fallback_reset(self):
        print("\n--- STARTING MEMORY FALLBACK RESET TEST ---")
        # Force REDIS_AVAILABLE to False for this test or just don't have it running
        # Actually RankingEngine handles it if connection fails.
        # But we can just use the memory store logic directly.
        
        os.environ["RESET_REDIS_ON_START"] = "true"
        with patch('ranking_engine.REDIS_AVAILABLE', False):
            broker = MagicMock()
            engine = RankingEngine(broker)
            # Inject some data into memory store
            engine.memory_store["rank:NIFTY"] = 5
            engine.last_signals["NIFTY:1"] = "B"
            
            # Manually call flush to see if it clears
            engine._flush_redis_state()
            
            self.assertEqual(engine.memory_store, {})
            self.assertEqual(engine.last_signals, {})
            print("✅ Memory state flushed correctly.")

if __name__ == "__main__":
    unittest.main()
