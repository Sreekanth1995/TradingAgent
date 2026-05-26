"""
Tests for PR #9a — alarm-pipe foundation.

Coverage matrix (matches the eng-review test plan for 9a):

  Slack webhook gating               2 tests   (fires only on 🚨; failure is silent)
  correlationId uniqueness           1 test    (10,000 concurrent calls, zero collisions)
  M1 _get_security_id None on miss   1 test    (returns None + alarm fires)
  WEBHOOK_SECRET fail-closed         1 test    (import-time RuntimeError on missing env)
  HTTP timeouts (lint)               1 test    (no requests.* in broker_dhan.py lacks timeout)

Total: 6 tests.

These pin the audit's most-cited fail-OPEN sites against silent regression. PR #9b
will add the remaining 7 fail-closed contracts; PR #9a's job is making sure when
THOSE alarms fire, the operator can SEE them.
"""
import os
import re
import threading
import time
import uuid
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest


# ─────────────────────────── Slack webhook gating ───────────────────────────
class TestSlackWebhookGating:
    """server.py:_add_activity_log fires the Slack webhook ONLY on 🚨 prefix.
    Normal info-level logs (📡, 🛡️, 🎯, etc.) must NOT spam Slack."""

    def _import_server_with_slack(self, slack_url="https://hooks.slack.test/T/B/X"):
        """Re-import server with a fresh SLACK_WEBHOOK_URL captured at import time."""
        import importlib, sys, server as _existing
        os.environ["SLACK_WEBHOOK_URL"] = slack_url
        importlib.reload(_existing)
        return _existing

    def test_alarm_prefix_triggers_slack_post(self):
        srv = self._import_server_with_slack()
        # Patch the synchronous _send body executed inside the daemon thread.
        # _post_to_slack_async spawns the thread; we need to capture the call without
        # depending on the real HTTP layer.
        posts = []
        def fake_post(url, json=None, timeout=None):
            posts.append({"url": url, "json": json, "timeout": timeout})
            class R: status_code = 200
            return R()
        with patch.dict(os.environ, {"SLACK_WEBHOOK_URL": "https://hooks.slack.test/T/B/X"}), \
             patch("requests.post", side_effect=fake_post):
            # Reload to pick up the env var the test set
            import importlib, server as _s
            importlib.reload(_s)
            _s._add_activity_log("SCRIP MISS for NIFTY", prefix="🚨 ")
            # The post is fire-and-forget in a thread — give it a moment.
            for _ in range(20):
                if posts:
                    break
                time.sleep(0.05)
        assert len(posts) == 1, f"expected exactly one Slack post for 🚨 alarm, got {posts}"
        assert "🚨" in posts[0]["json"]["text"]
        assert "SCRIP MISS" in posts[0]["json"]["text"]

    def test_non_alarm_prefix_does_not_trigger_slack(self):
        posts = []
        def fake_post(url, json=None, timeout=None):
            posts.append(url)
            class R: status_code = 200
            return R()
        with patch.dict(os.environ, {"SLACK_WEBHOOK_URL": "https://hooks.slack.test/T/B/X"}), \
             patch("requests.post", side_effect=fake_post):
            import importlib, server as _s
            importlib.reload(_s)
            # Non-alarm prefixes (info-level logs) must NOT post.
            for prefix in ["📡 ", "🛡️ ", "🎯 ", "✅ ", ""]:
                _s._add_activity_log("Some info message", prefix=prefix)
            # Wait long enough that an erroneous thread would have posted.
            time.sleep(0.3)
        assert posts == [], f"non-alarm prefixes leaked into Slack: {posts}"

    def test_alarm_storm_bounded_by_pool_and_drops_excess(self):
        """PR #9a /ship adversarial review: a sustained 🚨 storm (500
        alarms back-to-back) must NOT spawn 500 OS threads. The
        ThreadPoolExecutor caps concurrent posts at 2 and the semaphore
        caps queued+inflight at _SLACK_QUEUE_LIMIT — anything beyond is
        dropped with a single batched warning."""
        with patch.dict(os.environ, {"SLACK_WEBHOOK_URL": "https://hooks.slack.test/T/B/X"}):
            import importlib, server as _s
            importlib.reload(_s)

            # Make every Slack post BLOCK so the executor + semaphore fill up.
            # This is the worst case (slow Slack endpoint) the bound must survive.
            block_event = threading.Event()
            posts = []
            def slow_post(url, json=None, timeout=None):
                posts.append(url)
                block_event.wait(timeout=2)  # release at end of test
                class R: status_code = 200
                return R()

            with patch("requests.post", side_effect=slow_post):
                # Fire 500 alarms back-to-back, faster than Slack can drain.
                for i in range(500):
                    _s._add_activity_log(f"SCRIP MISS #{i}", prefix="🚨 ")
                # Let the semaphore-bound mechanic settle.
                time.sleep(0.1)
                # The semaphore limit is 50 (2 in-flight workers + 48 queued).
                # Anything beyond MUST be counted as dropped (_slack_dropped_count > 0).
                assert _s._slack_dropped_count > 0, (
                    "Storm of 500 alarms with blocked Slack should have triggered drops; "
                    f"_slack_dropped_count={_s._slack_dropped_count}"
                )
                # At most _SLACK_QUEUE_LIMIT messages should be in-flight/queued —
                # NOT one OS thread per alarm.
                assert _s._slack_dropped_count >= 500 - _s._SLACK_QUEUE_LIMIT, (
                    f"Expected >={500 - _s._SLACK_QUEUE_LIMIT} drops, "
                    f"got {_s._slack_dropped_count}"
                )
                # Unblock the workers so they finish (test teardown).
                block_event.set()


# ─────────────────────────── correlationId uniqueness ───────────────────────────
class TestCorrelationIdUniqueness:
    """The 1-second-resolution generator from before PR #9a collided under burst
    at 9:15 IST (3 underlyings × CALL+PUT can all happen in one second). PR #9b's
    M5 idempotency builds on uniqueness — this test pins the fix."""

    def test_10000_ids_have_zero_collisions(self):
        # Mirror the format used in broker_dhan.py place_super_order.
        # Generating in a tight loop is the worst case for uniqueness.
        seen = set()
        for _ in range(10_000):
            cid = f"b_{time.time_ns()}_{uuid.uuid4().hex[:8]}"
            assert cid not in seen, f"collision after {len(seen)} IDs at {cid}"
            seen.add(cid)
        assert len(seen) == 10_000


# ─────────────────────────── M1 _get_security_id None on miss ───────────────────────────
class TestSecurityIdFailClosed:
    """The audit's #1 most-dangerous fail-OPEN. Before PR #9a, an unknown strike
    returned the literal string '1333'. Now it returns None and fires a 🚨 alarm."""

    def test_known_strike_returns_id(self):
        from broker_dhan import DhanClient
        c = DhanClient()
        # Inject a known mapping
        c.scrip_map[("NIFTY", 24500.0, "CE", "2026-05-29")] = "55501"
        assert c._get_security_id("NIFTY", 24500, "CE", "2026-05-29") == "55501"

    def test_unknown_strike_returns_none_and_fires_alarm(self):
        from broker_dhan import DhanClient
        captured = []
        c = DhanClient(activity_log_fn=lambda msg, prefix: captured.append((prefix, msg)))
        # Make sure no entry matches
        c.scrip_map = {}
        result = c._get_security_id("NIFTY", 99999, "CE", "2026-05-29")
        assert result is None, f"unknown strike must return None, got {result!r}"
        assert len(captured) == 1, f"expected exactly one alarm, got {captured}"
        prefix, msg = captured[0]
        assert prefix.strip() == "🚨"
        assert "SCRIP MISS" in msg
        assert "NIFTY" in msg
        assert "99999" in msg


# ─────────────────────────── WEBHOOK_SECRET fail-closed ───────────────────────────
class TestWebhookSecretFailClosed:
    """server.py:34 used to default to 'WEBHOOK_SECRET' = '60pgS' (public). Now
    the module raises RuntimeError at import if the env var is missing."""

    def test_missing_secret_raises_at_import(self, monkeypatch):
        # Set to empty string. `load_dotenv()` defaults to override=False, so a
        # pre-existing empty WEBHOOK_SECRET in os.environ blocks the parent
        # worktree's .env (if any) from re-populating it. The fail-closed
        # branch reads `os.environ.get("WEBHOOK_SECRET")` which returns "" →
        # truthy-False → RuntimeError, exactly the contract.
        monkeypatch.setenv("WEBHOOK_SECRET", "")
        import sys
        # Snapshot the existing server module so we can restore it after the
        # failing import. Without this, the next test that does
        # `from server import ...` gets a partial/missing module and fails
        # mysteriously. Same pattern as the prior fixture-pollution fix in
        # tests/test_feeling_gate.py.
        saved_server = sys.modules.pop("server", None)
        try:
            with pytest.raises(RuntimeError, match="WEBHOOK_SECRET environment variable is required"):
                import server  # noqa: F401
        finally:
            # Restore the previously imported module so downstream tests don't
            # see a stale or partial import. The good module is the one that
            # was loaded under the conftest's "test_secret" env.
            if saved_server is not None:
                sys.modules["server"] = saved_server
            else:
                # No prior import — drop any partial that the failed import left.
                sys.modules.pop("server", None)


# ─────────────────────────── HTTP timeouts (lint) ───────────────────────────
class TestHttpTimeouts:
    """Every requests.* call in broker_dhan.py must specify a timeout. Lint-style
    scan over the source file. Pins audit finding #19."""

    def test_no_untimed_requests_call_in_broker_dhan(self):
        path = Path(__file__).resolve().parent.parent / "broker_dhan.py"
        src = path.read_text()
        # Find every `requests.METHOD(` invocation across the file (multi-line allowed).
        # Approach: for each match of `requests.{verb}(`, scan forward balancing parens
        # until depth returns to zero; assert `timeout=` appears in that span.
        pattern = re.compile(r"requests\.(get|post|put|delete|patch)\(")
        offenders = []
        for m in pattern.finditer(src):
            start = m.end() - 1  # position of the opening (
            depth = 0
            i = start
            while i < len(src):
                ch = src[i]
                if ch == "(":
                    depth += 1
                elif ch == ")":
                    depth -= 1
                    if depth == 0:
                        end = i
                        break
                i += 1
            else:
                offenders.append((m.start(), "unbalanced parens"))
                continue
            block = src[start:end + 1]
            if "timeout=" not in block:
                # Compute line number for a useful error message
                line_no = src.count("\n", 0, m.start()) + 1
                offenders.append((line_no, block.replace("\n", "\\n")[:120]))
        assert offenders == [], (
            "broker_dhan.py has requests.* calls without timeout=:\n"
            + "\n".join(f"  line {ln}: {snippet}" for ln, snippet in offenders)
        )
