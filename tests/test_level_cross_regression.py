"""
Regression: LEVEL_CROSS must never open a new position when current_side='NONE'.

Today this is incidental safety — `process_signal` only handles 'B'/'S' for new
entries and 'S'/'B' opposite-of-position for exits. LEVEL_CROSS falls out of
both branches when current_side is NONE, returning the "no action" sentinel.

The feeling-gate /plan-eng-review (premise 8) called this out: a future refactor
that adds a LEVEL_CROSS entry path would silently bypass the gate. This test
pins the current behavior so any such refactor is loud (this test breaks).
"""
import pytest
from unittest.mock import MagicMock

from super_order_engine import SuperOrderEngine
from broker_mock import MockDhanClient


def test_level_cross_does_not_open_position_when_current_side_none():
    broker = MockDhanClient()
    engine = SuperOrderEngine(broker, redis_client=None, activity_logs=None)

    # No prior state for the underlying.
    state = engine._get_state('NIFTY')
    assert state['side'] == 'NONE'

    # A LEVEL_CROSS signal should fall out of the entry/exit branches and
    # return a "no action" sentinel — never call place_super_order.
    broker.place_super_order = MagicMock(name='place_super_order')

    itm = {'symbol': 'NIFTY24NOV24500CE', 'security_id': '12345'}
    result = engine.process_signal('NIFTY', itm, 'LEVEL_CROSS')

    # Must NOT place an order.
    broker.place_super_order.assert_not_called()

    # State unchanged.
    assert engine._get_state('NIFTY')['side'] == 'NONE'

    # Returned the no-action sentinel.
    assert result.get('action') == 'NONE'
