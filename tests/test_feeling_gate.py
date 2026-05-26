"""
Tests for the per-underlying market-feeling trade gate.

Test groups (see eng-review test plan):
  TestDecision         (7) — 8-case truth table + invalid side raises
  TestPersistence      (5) — missing/corrupt/denied sentinels + atomic write
  TestRoutes           (6) — PUT/GET /set-feeling, /get-feeling, validation, auth
  TestRouteGate        (5) — /super-order + /conditional-order + /webhook enforcement
  TestEngineGuard      (3) — direct engine call bypassing route still blocked
  TestLifecycle        (2) — restart-survives, per-underlying isolation
  TestContraPending    (1) — feeling flip warns about contra PENDING, no auto-cancel
"""
import json
import os
import threading
from unittest.mock import MagicMock

import pytest

from feeling_gate import (
    FeelingState, feeling_gate, normalize_feeling, derive_side,
    VALID_FEELINGS,
)
from atomic_json import write_json
from super_order_engine import SuperOrderEngine
from conditional_order_engine import ConditionalOrderEngine
from broker_mock import MockDhanClient


# ───────────────────────── TestDecision: 8-case truth table ─────────────────────────
class TestDecision:
    def test_bullish_allows_call(self):
        allow, reason = feeling_gate('CALL', 'Bullish')
        assert allow is True
        assert 'Bullish' in reason

    def test_bullish_blocks_put(self):
        allow, reason = feeling_gate('PUT', 'Bullish')
        assert allow is False
        assert 'Bullish' in reason and 'PUT' in reason

    def test_bearish_blocks_call(self):
        allow, reason = feeling_gate('CALL', 'Bearish')
        assert allow is False

    def test_bearish_allows_put(self):
        allow, reason = feeling_gate('PUT', 'Bearish')
        assert allow is True

    def test_inside_blocks_both(self):
        a_call, _ = feeling_gate('CALL', 'Inside')
        a_put, _ = feeling_gate('PUT', 'Inside')
        assert a_call is False and a_put is False

    def test_none_allows_both(self):
        # The fresh-install / "no opinion" default. Critical for first boot.
        a_call, _ = feeling_gate('CALL', None)
        a_put, _ = feeling_gate('PUT', None)
        assert a_call is True and a_put is True

    def test_invalid_side_raises(self):
        with pytest.raises(ValueError):
            feeling_gate('FLAT', 'Bullish')


# ───────────────────────── TestPersistence ─────────────────────────
class TestPersistence:
    def test_missing_file_returns_allow_all(self, tmp_path):
        """Premise 9 + plan-eng-review Issue 1: missing file is fresh-install,
        not corrupt. Gate must allow."""
        p = str(tmp_path / "feelings.json")
        fs = FeelingState(path=p)
        assert fs.get('NIFTY') is None
        assert fs.is_unreadable is False
        assert fs.store_status == 'ok'
        allow, _ = feeling_gate('CALL', fs.get('NIFTY'))
        assert allow is True

    def test_corrupt_file_marks_store_unreadable(self, tmp_path):
        p = str(tmp_path / "feelings.json")
        # Simulate a torn write (mid-dump crash).
        with open(p, 'w') as f:
            f.write('{"NIFTY": "Bull')
        fs = FeelingState(path=p)
        assert fs.is_unreadable is True
        assert fs.store_status == 'unreadable'
        # get() returns None so the route's is_unreadable check is what blocks
        # (we don't trust the partial parse).
        assert fs.get('NIFTY') is None

    def test_permission_denied_marks_store_unreadable(self, tmp_path):
        p = str(tmp_path / "feelings.json")
        with open(p, 'w') as f:
            f.write('{"NIFTY": "Bullish"}')
        os.chmod(p, 0)
        try:
            if os.geteuid() == 0:
                pytest.skip("running as root; cannot test PermissionError")
            fs = FeelingState(path=p)
            assert fs.is_unreadable is True
            assert fs.store_status == 'unreadable'
        finally:
            os.chmod(p, 0o600)

    def test_atomic_write_survives_partial_simulation(self, tmp_path):
        """If write_json raises mid-call (simulated), the prior value is intact."""
        p = str(tmp_path / "feelings.json")
        fs = FeelingState(path=p)
        fs.set('NIFTY', 'Bullish')
        # Snapshot the on-disk file before the failure.
        before = open(p).read()

        # Force write_json to fail by patching the underlying os.replace.
        from unittest.mock import patch
        with patch('atomic_json.os.replace', side_effect=OSError('simulated')):
            with pytest.raises(OSError):
                fs.set('NIFTY', 'Bearish')

        # The file must still be the prior version, NOT torn or empty.
        after = open(p).read()
        assert after == before
        assert fs.get('NIFTY') == 'Bullish'
        assert not os.path.exists(p + '.tmp')

    def test_concurrent_writes_do_not_tear(self, tmp_path):
        p = str(tmp_path / "feelings.json")
        fs = FeelingState(path=p)
        errs = []
        feelings_cycle = ['Bullish', 'Bearish', 'Inside']

        def writer(i):
            try:
                fs.set('NIFTY', feelings_cycle[i % 3])
            except Exception as e:
                errs.append(e)

        threads = [threading.Thread(target=writer, args=(i,)) for i in range(60)]
        for t in threads: t.start()
        for t in threads: t.join()

        assert errs == []
        # File is valid JSON and final value is one of the three we wrote.
        final = fs.get('NIFTY')
        assert final in feelings_cycle


# ───────────────────────── TestRoutes (HTTP /set-feeling, /get-feeling) ─────────────────────────
@pytest.fixture
def server_app(tmp_path, monkeypatch):
    """Use the live server module but swap in a tmpdir-isolated FeelingState
    and a test SECRET. Does NOT reload the module — that polluted other
    tests' module-level imports.

    Restores the prior feeling_state + SECRET at fixture teardown via monkeypatch.
    """
    # Avoid the import-time scrip-master download by forcing mock mode if not
    # already set. Safe to set even when server is already imported.
    monkeypatch.setenv('USE_MOCK_API', 'true')

    import server
    # Swap in a tmpdir-isolated FeelingState so tests don't see each other's writes
    # and don't pollute a real feelings.json.
    test_fs = FeelingState(path=str(tmp_path / 'feelings.json'))
    monkeypatch.setattr(server, 'feeling_state', test_fs)
    # Engines hold a reference to feeling_state from constructor — patch those too.
    if server.super_order_engine is not None:
        monkeypatch.setattr(server.super_order_engine, 'feeling_state', test_fs)
    if server.conditional_engine is not None:
        monkeypatch.setattr(server.conditional_engine, 'feeling_state', test_fs)
    # Test SECRET so payload `secret='testsecret'` authenticates.
    monkeypatch.setattr(server, 'SECRET', 'testsecret')
    yield server


class TestRoutes:
    def test_set_then_get_round_trip(self, server_app):
        client = server_app.app.test_client()
        r = client.post('/set-feeling', json={'secret': 'testsecret', 'underlying': 'NIFTY', 'value': 'Bullish'})
        assert r.status_code == 200
        assert r.get_json()['feeling'] == 'Bullish'

        r2 = client.post('/get-feeling', json={'secret': 'testsecret', 'underlying': 'NIFTY'})
        assert r2.status_code == 200
        assert r2.get_json()['feeling'] == 'Bullish'

    def test_get_all_returns_full_map(self, server_app):
        client = server_app.app.test_client()
        client.post('/set-feeling', json={'secret': 'testsecret', 'underlying': 'NIFTY', 'value': 'Bullish'})
        client.post('/set-feeling', json={'secret': 'testsecret', 'underlying': 'BANKNIFTY', 'value': 'Bearish'})

        r = client.post('/get-feeling', json={'secret': 'testsecret'})
        body = r.get_json()
        assert r.status_code == 200
        assert body['feelings'] == {'NIFTY': 'Bullish', 'BANKNIFTY': 'Bearish', 'FINNIFTY': None}

    def test_null_value_clears(self, server_app):
        client = server_app.app.test_client()
        client.post('/set-feeling', json={'secret': 'testsecret', 'underlying': 'NIFTY', 'value': 'Bullish'})
        r = client.post('/set-feeling', json={'secret': 'testsecret', 'underlying': 'NIFTY', 'value': None})
        assert r.status_code == 200
        assert r.get_json()['feeling'] is None

    def test_invalid_value_rejected_400(self, server_app):
        client = server_app.app.test_client()
        r = client.post('/set-feeling', json={'secret': 'testsecret', 'underlying': 'NIFTY', 'value': 'Neutral'})
        assert r.status_code == 400
        assert 'one of' in r.get_json()['message']

    def test_invalid_underlying_rejected_400(self, server_app):
        client = server_app.app.test_client()
        r = client.post('/set-feeling', json={'secret': 'testsecret', 'underlying': 'BTC', 'value': 'Bullish'})
        assert r.status_code == 400

    def test_unauthorized_without_secret(self, server_app):
        client = server_app.app.test_client()
        r = client.post('/set-feeling', json={'underlying': 'NIFTY', 'value': 'Bullish'})
        assert r.status_code == 401
        r2 = client.post('/get-feeling', json={'underlying': 'NIFTY'})
        assert r2.status_code == 401


# ───────────────────────── TestRouteGate ─────────────────────────
class TestRouteGate:
    def test_super_order_put_blocked_under_bullish(self, server_app):
        client = server_app.app.test_client()
        client.post('/set-feeling', json={'secret': 'testsecret', 'underlying': 'NIFTY', 'value': 'Bullish'})

        r = client.post('/super-order', json={
            'secret': 'testsecret', 'underlying': 'NIFTY', 'side': 'PUT',
            'target_price': 100, 'sl_price': 50,
            'option': 'NIFTY24NOV24500PE', 'security_id': '12345',
        })
        assert r.status_code == 200
        body = r.get_json()
        assert body['status'] == 'skipped_by_feeling'
        assert body['feeling'] == 'Bullish'
        assert body['side'] == 'PUT'

    def test_super_order_call_allowed_under_bullish(self, server_app):
        """Allowed entry should NOT short-circuit at the gate; it proceeds to
        the broker (which may fail in MOCK mode for unrelated reasons —
        we only assert the response is NOT skipped_by_feeling)."""
        client = server_app.app.test_client()
        client.post('/set-feeling', json={'secret': 'testsecret', 'underlying': 'NIFTY', 'value': 'Bullish'})

        r = client.post('/super-order', json={
            'secret': 'testsecret', 'underlying': 'NIFTY', 'side': 'CALL',
            'target_price': 100, 'sl_price': 50,
            'option': 'NIFTY24NOV24500CE', 'security_id': '54321',
        })
        body = r.get_json() or {}
        assert body.get('status') != 'skipped_by_feeling'

    def test_super_order_unset_feeling_passes_through(self, server_app):
        client = server_app.app.test_client()
        # No feeling set — gate must be transparent.
        r = client.post('/super-order', json={
            'secret': 'testsecret', 'underlying': 'NIFTY', 'side': 'PUT',
            'target_price': 100, 'sl_price': 50,
            'option': 'NIFTY24NOV24500PE', 'security_id': '12345',
        })
        body = r.get_json() or {}
        assert body.get('status') != 'skipped_by_feeling'

    def test_inside_blocks_both_sides(self, server_app):
        client = server_app.app.test_client()
        client.post('/set-feeling', json={'secret': 'testsecret', 'underlying': 'NIFTY', 'value': 'Inside'})

        for side, opt, secid in (('CALL', 'NIFTY24NOV24500CE', '1'),
                                  ('PUT',  'NIFTY24NOV24500PE', '2')):
            r = client.post('/super-order', json={
                'secret': 'testsecret', 'underlying': 'NIFTY', 'side': side,
                'target_price': 100, 'sl_price': 50,
                'option': opt, 'security_id': secid,
            })
            assert r.get_json()['status'] == 'skipped_by_feeling', f"side={side} not blocked"

    def test_skipped_row_written_to_trade_feed(self, server_app, monkeypatch):
        """When the gate blocks, a SKIPPED row is inserted into trade_feed
        so the operator has a paper trail."""
        client = server_app.app.test_client()
        client.post('/set-feeling', json={'secret': 'testsecret', 'underlying': 'NIFTY', 'value': 'Bullish'})

        inserts = []
        import trade_feed
        real_insert = trade_feed.insert_trade

        def spy_insert(**kwargs):
            inserts.append(kwargs)
            return real_insert(**kwargs)

        monkeypatch.setattr(trade_feed, 'insert_trade', spy_insert)
        # Also patch the alias in server (server.py imports trade_feed as a module — patching the module's attr works because the route looks up trade_feed.insert_trade at call time)

        client.post('/super-order', json={
            'secret': 'testsecret', 'underlying': 'NIFTY', 'side': 'PUT',
            'target_price': 100, 'sl_price': 50,
            'option': 'NIFTY24NOV24500PE', 'security_id': '12345',
        })
        skipped = [i for i in inserts if i.get('status') == 'SKIPPED']
        assert len(skipped) == 1, f"expected 1 SKIPPED row, got {inserts}"
        assert skipped[0]['underlying'] == 'NIFTY'
        assert 'Bullish' in skipped[0].get('comment', '')


# ───────────────────────── TestEngineGuard ─────────────────────────
class TestEngineGuard:
    """Verify Approach C: when a caller bypasses the route, the engine still blocks."""

    def test_super_engine_blocks_direct_call_under_contra_feeling(self, tmp_path):
        fs = FeelingState(path=str(tmp_path / 'feelings.json'))
        fs.set('NIFTY', 'Bullish')
        engine = SuperOrderEngine(MockDhanClient(), feeling_state=fs)

        itm = {'symbol': 'NIFTY24NOV24500PE', 'security_id': '12345'}
        result = engine.place_super_order(
            underlying='NIFTY', side='PUT', quantity=1, itm=itm,
            target_price=100, stop_loss_price=50,
        )
        assert result.get('success') is False
        assert result.get('status') == 'skipped_by_feeling'
        assert result.get('feeling') == 'Bullish'

    def test_conditional_engine_blocks_handle_signal_bypass(self, tmp_path):
        fs = FeelingState(path=str(tmp_path / 'feelings.json'))
        fs.set('NIFTY', 'Bullish')
        engine = ConditionalOrderEngine(MockDhanClient(), feeling_state=fs)

        # signal_type='S' = SHORT entry (PUT). Under Bullish, must block.
        itm = {'symbol': 'NIFTY24NOV24500PE', 'security_id': '12345',
               'tradingSymbol': 'NIFTY24NOV24500PE'}
        result = engine.handle_signal('S', {
            'underlying': 'NIFTY', 'itm': itm, 'idx_sec_id': '13',
            'spot_index': 24500, 'quantity': 1,
        })
        assert result.get('status') == 'skipped_by_feeling'
        assert result.get('side') == 'PUT'

    def test_engine_skipped_entirely_when_feeling_state_is_none(self, tmp_path):
        """Older tests construct engines without feeling_state. The gate must
        be a no-op in that case so we don't break the existing suite."""
        engine = SuperOrderEngine(MockDhanClient(), feeling_state=None)
        engine.broker.place_super_order = MagicMock(return_value={'success': True, 'order_id': 'X'})
        itm = {'symbol': 'NIFTY24NOV24500CE', 'security_id': '12345'}
        result = engine.place_super_order(
            underlying='NIFTY', side='CALL', quantity=1, itm=itm,
            target_price=100, stop_loss_price=50,
        )
        # The broker call should have been reached.
        engine.broker.place_super_order.assert_called_once()

    def test_super_engine_fails_closed_on_invalid_side(self, tmp_path):
        """/ship adversarial review CRITICAL #2: a programming-error caller
        with side='Call' (lowercase) or any other invalid string must NOT
        silently bypass the gate. The Approach-C safety net disappears if
        the engine guard is permissive on garbage input.
        """
        fs = FeelingState(path=str(tmp_path / 'feelings.json'))
        fs.set('NIFTY', 'Bullish')
        engine = SuperOrderEngine(MockDhanClient(), feeling_state=fs)
        # Spy the broker call so we can prove it was never invoked.
        engine.broker.place_super_order = MagicMock()

        itm = {'symbol': 'NIFTY24NOV24500CE', 'security_id': '12345'}
        result = engine.place_super_order(
            underlying='NIFTY', side='Call',  # wrong case — invalid
            quantity=1, itm=itm,
            target_price=100, stop_loss_price=50,
        )
        assert result.get('success') is False, "invalid side must NOT proceed to broker"
        assert result.get('status') == 'skipped_by_feeling'
        engine.broker.place_super_order.assert_not_called()

    def test_conditional_arm_entry_engine_guard_blocks(self, tmp_path):
        """/ship adversarial review test gap: arm_conditional_entry has the
        engine guard but no test exercised it directly. This test calls the
        method (bypassing the /conditional-order route) and asserts the
        block kicks in before any broker call."""
        fs = FeelingState(path=str(tmp_path / 'feelings.json'))
        fs.set('NIFTY', 'Bearish')  # blocks CALL
        engine = ConditionalOrderEngine(MockDhanClient(), feeling_state=fs)
        # Inject lot_size so the gate is the only thing in front of broker placement.
        engine.broker.lot_map['12345'] = 75
        engine.broker.place_conditional_order = MagicMock()

        result = engine.arm_conditional_entry({
            'underlying': 'NIFTY', 'side': 'CALL',
            'itm': {'symbol': 'NIFTY24NOV24500CE', 'security_id': '12345',
                    'tradingSymbol': 'NIFTY24NOV24500CE'},
            'idx_sec_id': '13', 'operator': 'ABOVE', 'comparing_value': 24500.0,
            'sl_index': 24400.0, 'target_index': 24700.0,
            'correlation_id': 'ENTRY:NIFTY:abc', 'quantity': 1,
        })
        assert result.get('status') == 'skipped_by_feeling'
        assert result.get('feeling') == 'Bearish'
        engine.broker.place_conditional_order.assert_not_called()


# ───────────────────────── TestUnreadableRoutes ─────────────────────────
class TestUnreadableRoutes:
    """/ship adversarial review test gap: no route-level test for the
    unreadable-store branch. Highest-stakes fail-closed path (entries blocked)
    that previously had no integration coverage."""

    def test_super_order_blocked_when_store_unreadable(self, server_app, tmp_path):
        # Corrupt the test feelings.json after fixture has wired feeling_state.
        with open(server_app.feeling_state.path, 'w') as f:
            f.write('{"NIFTY": "Bull')  # torn write

        client = server_app.app.test_client()
        r = client.post('/super-order', json={
            'secret': 'testsecret', 'underlying': 'NIFTY', 'side': 'CALL',
            'target_price': 100, 'sl_price': 50,
            'option': 'NIFTY24NOV24500CE', 'security_id': '12345',
        })
        assert r.status_code == 200
        body = r.get_json()
        assert body['status'] == 'skipped_by_feeling_unreadable'
        assert 'recovery' in body
        # The hint must NOT direct the user to restart the server. Earlier
        # versions said "delete feelings.json then restart" — restart isn't
        # required because FeelingState reads disk fresh on every call.
        assert 'no restart needed' in body['recovery'], \
            f"recovery hint should clarify restart is unnecessary, got {body['recovery']!r}"

    def test_set_feeling_returns_503_when_store_unreadable(self, server_app):
        with open(server_app.feeling_state.path, 'w') as f:
            f.write('{"NIFTY": "Bull')

        client = server_app.app.test_client()
        r = client.post('/set-feeling', json={'secret': 'testsecret', 'underlying': 'NIFTY', 'value': 'Bullish'})
        assert r.status_code == 503
        assert r.get_json()['feelings_store'] == 'unreadable'

    def test_health_surfaces_unreadable(self, server_app):
        with open(server_app.feeling_state.path, 'w') as f:
            f.write('{"NIFTY": "Bull')

        client = server_app.app.test_client()
        r = client.get('/health')
        assert r.status_code == 200
        assert r.get_json()['feelings_store'] == 'unreadable'


# ───────────────────────── TestSSEInvisibility ─────────────────────────
class TestSSEInvisibility:
    """/ship adversarial review test gap: the design promise that vetoed
    /webhook signals stay invisible to Claude (no last_signal_storage update,
    no SSE emit) was enforced only by code structure. Pin it with a test
    so a future refactor can't silently break the invisibility contract."""

    def test_blocked_webhook_does_not_update_last_signal_storage(self, server_app):
        client = server_app.app.test_client()
        client.post('/set-feeling', json={'secret': 'testsecret', 'underlying': 'NIFTY', 'value': 'Bullish'})

        # Reset last_signal_storage to a known state before the call.
        server_app.last_signal_storage['data'] = None

        r = client.post('/webhook', json={
            'secret': 'testsecret', 'timeframe': 5,
            'order_legs': [{'underlying': 'NIFTY', 'transactionType': 'SELL', 'price': 24500}],
        })
        assert r.status_code == 200
        # The blocked signal should NOT have updated last_signal_storage.
        assert server_app.last_signal_storage['data'] is None, \
            "vetoed signal leaked into last_signal_storage — AI mode would see it"


# ───────────────────────── TestLifecycle ─────────────────────────
class TestLifecycle:
    def test_state_survives_restart(self, tmp_path):
        """Second FeelingState pointing at the same file reads the first one's writes."""
        p = str(tmp_path / 'feelings.json')
        fs1 = FeelingState(path=p)
        fs1.set('NIFTY', 'Bullish')
        # Simulate restart: brand-new instance, same path.
        fs2 = FeelingState(path=p)
        assert fs2.get('NIFTY') == 'Bullish'

    def test_per_underlying_isolation(self, tmp_path):
        p = str(tmp_path / 'feelings.json')
        fs = FeelingState(path=p)
        fs.set('NIFTY', 'Bullish')
        fs.set('BANKNIFTY', 'Bearish')

        # Each underlying maps to its own feeling; flipping one doesn't change others.
        assert fs.get('NIFTY') == 'Bullish'
        assert fs.get('BANKNIFTY') == 'Bearish'
        assert fs.get('FINNIFTY') is None

        # NIFTY × CALL under Bullish allows; BANKNIFTY × CALL under Bearish blocks.
        a_call_nifty, _ = feeling_gate('CALL', fs.get('NIFTY'))
        a_call_bn, _ = feeling_gate('CALL', fs.get('BANKNIFTY'))
        assert a_call_nifty is True
        assert a_call_bn is False


# ───────────────────────── TestContraPending ─────────────────────────
class TestContraPending:
    def test_set_feeling_warns_about_contra_pending_no_autocancel(self, server_app, monkeypatch):
        """Flip feeling while a PENDING_PUT is armed under Bullish — the new
        Bearish set should report a contra warning but the PENDING must
        remain armed (no auto-cancel; operator decides)."""
        client = server_app.app.test_client()
        # Arrange: feeling=Bearish, then arm a PENDING_PUT by mutating engine state
        # directly (we're testing the warning logic, not the arming flow itself).
        client.post('/set-feeling', json={'secret': 'testsecret', 'underlying': 'NIFTY', 'value': 'Bearish'})
        server_app.conditional_engine._set_state('NIFTY', {
            'side': 'PENDING_PUT', 'entry_trigger': 24500.0,
            'entry_alert_id': 'ALERT-1', 'correlation_id': 'ENTRY:NIFTY:xxx',
        })

        # Act: flip to Bullish — contradicts the armed PUT.
        r = client.post('/set-feeling', json={'secret': 'testsecret', 'underlying': 'NIFTY', 'value': 'Bullish'})
        body = r.get_json()
        assert r.status_code == 200
        assert body['feeling'] == 'Bullish'

        # The warning must surface.
        warnings = body.get('warnings', [])
        assert any(w['kind'] == 'contra_pending_entry' and w['side'] == 'PUT'
                   for w in warnings), f"expected contra warning, got {warnings}"

        # CRITICAL: PENDING must remain armed (no auto-cancel).
        state = server_app.conditional_engine._get_state('NIFTY')
        assert state['side'] == 'PENDING_PUT'
        assert state['entry_alert_id'] == 'ALERT-1'
