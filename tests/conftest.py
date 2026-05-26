import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# server.py fail-closes if WEBHOOK_SECRET is missing (PR #9a T7a — mirrors the
# d2f0adb mcp_server fix). Tests that do top-level `from server import ...` would
# explode at collection time without a default. Set a placeholder; individual
# tests still monkeypatch over this with their own SECRET.
os.environ.setdefault("WEBHOOK_SECRET", "test_secret")
# USE_MOCK_API defaults to true in tests so DhanClient never spawns its scrip
# downloader (the no-network DhanClient TODO is still open; this is the safe path).
os.environ.setdefault("USE_MOCK_API", "true")
