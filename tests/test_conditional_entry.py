"""
Tests for the conditional index-touch entry feature (Approach A).

Coverage:
  - derive_entry_trigger / validate_sl_target / round_to_tick  (pure helpers, T4)
  - arm_conditional_entry: PENDING state, lot-size, lot_map-miss reject (T3)
  - handle_postback ENTRY: linkage, partial fills, idempotency, dup (T2/T10)
  - cancel_pending_entry + exit-while-pending + fill-vs-cancel race (T5)
  - flush_pending_entries (T7)
  - regressions: market entry + orderId-keyed market fill still work (T12/R1/R2)
"""
import pytest

from conditional_order_engine import ConditionalOrderEngine
from broker_mock import MockDhanClient
from instrument_resolver import derive_entry_trigger, validate_sl_target, round_to_tick


# ───────────────────────── T4: pure helpers ─────────────────────────
class TestDeriveEntryTrigger:
    def test_above_when_entry_over_spot(self):
        ok, r = derive_entry_trigger(24600, 24550)
        assert ok and r['operator'] == 'ABOVE' and r['comparing_value'] == 24600.0

    def test_below_when_entry_under_spot(self):
        ok, r = derive_entry_trigger(24500, 24550)
        assert ok and r['operator'] == 'BELOW' and r['comparing_value'] == 24500.0

    def test_tie_is_rejected_as_already_crossed(self):
        ok, r = derive_entry_trigger(24550, 24550)
        assert not ok and 'crossed' in r['reason'].lower()

    def test_near_tie_within_one_tick_rejected(self):
        ok, r = derive_entry_trigger(24550.02, 24550.0)  # < 0.05 gap
        assert not ok

    def test_nonpositive_entry_rejected(self):
        ok, r = derive_entry_trigger(0, 24550)
        assert not ok

    def test_fat_finger_rejected(self):
        ok, r = derive_entry_trigger(40000, 24550)  # >25% from spot
        assert not ok and 'implausible' in r['reason'].lower()

    def test_nonnumeric_rejected(self):
        ok, r = derive_entry_trigger("abc", 24550)
        assert not ok

    def test_comparing_value_is_tick_rounded(self):
        ok, r = derive_entry_trigger(24600.03, 24550)
        assert ok and r['comparing_value'] == 24600.05


class TestRoundToTick:
    def test_round(self):
        assert round_to_tick(24600.03) == 24600.05
        assert round_to_tick(24600.01) == 24600.0


class TestValidateSLTarget:
    def test_call_valid(self):
        ok, _ = validate_sl_target('CALL', 24600, sl_index=24550, target_index=24700)
        assert ok

    def test_call_sl_not_below_rejected(self):
        ok, reason = validate_sl_target('CALL', 24600, 24650, 24700)
        assert not ok and 'SL' in reason

    def test_call_target_not_above_rejected(self):
        ok, _ = validate_sl_target('CALL', 24600, 24550, 24590)
        assert not ok

    def test_put_valid(self):
        ok, _ = validate_sl_target('PUT', 24500, sl_index=24550, target_index=24400)
        assert ok

    def test_put_sl_not_above_rejected(self):
        ok, _ = validate_sl_target('PUT', 24500, 24450, 24400)
        assert not ok


# ───────────────────────── engine fixtures ─────────────────────────
CE_SID = 'SID_NIFTY_24550_CE'


def make_engine():
    broker = MockDhanClient()
    broker.lot_map = {CE_SID: 75}
    eng = ConditionalOrderEngine(broker=broker)
    eng.memory_store = {}
    return eng, broker


def arm_call(eng, correlation='ENTRY:NIFTY:abc', qty=1):
    return eng.arm_conditional_entry({
        'underlying': 'NIFTY', 'side': 'CALL',
        'itm': {'symbol': 'NIFTY_MOCK_24550_CE', 'security_id': CE_SID},
        'idx_sec_id': '13', 'quantity': qty,
        'operator': 'ABOVE', 'comparing_value': 24600.0,
        'sl_index': 24550, 'target_index': 24700,
        'correlation_id': correlation,
    })


# ───────────────────────── T3: arm ─────────────────────────
class TestArmConditionalEntry:
    def test_arm_sets_pending_and_places_conditional_buy(self):
        eng, broker = make_engine()
        res = arm_call(eng)
        assert res['status'] == 'success' and res['action'] == 'ARMED_CONDITIONAL_ENTRY'

        st = eng._get_state('NIFTY')
        assert st['side'] == 'PENDING_CALL'
        assert st['correlation_id'] == 'ENTRY:NIFTY:abc'
        assert st['entry_alert_id']

        gtts = list(broker.mock_gtts.values())
        assert len(gtts) == 1
        g = gtts[0]
        assert g['transaction_type'] == 'BUY'
        assert g['product_type'] == 'INTRADAY'      # T1: pinned
        assert g['user_note'] == 'ENTRY:NIFTY:abc'  # T2: correlation linkage
        assert g['trigger_sec_id'] == '13'          # index trigger
        assert g['quantity'] == 75                  # T9: 1 lot * lot_size 75

        assert eng.get_pending_protection('ENTRY:NIFTY:abc', consume=False) is not None

    def test_lot_map_miss_rejects_without_placing(self):
        eng, broker = make_engine()
        broker.lot_map = {}  # miss
        res = arm_call(eng)
        assert res['status'] == 'error' and 'lot_map miss' in res['message']
        assert broker.mock_gtts == {}                     # never placed an order
        assert eng._get_state('NIFTY')['side'] == 'NONE'  # no PENDING state left


# ───────────────────────── T10/T2: fill → bracket ─────────────────────────
class TestConditionalFill:
    def test_fill_arms_bracket_via_usernote(self):
        eng, broker = make_engine()
        arm_call(eng, correlation='ENTRY:NIFTY:xyz')
        res = eng.handle_postback({
            'orderStatus': 'TRADED', 'orderId': 'NEWORD_999',
            'userNote': 'ENTRY:NIFTY:xyz', 'tradedPrice': 105.0, 'filledQty': 75,
        })
        assert res['source'] == 'conditional_fill' and res['final'] is True

        st = eng._get_state('NIFTY')
        assert st['side'] == 'CALL'
        assert st['entry_price'] == 105.0
        assert st['entry_id'] == 'NEWORD_999'
        assert st.get('idx_sl_alert_id') and st.get('idx_target_alert_id')

        sells = [g for g in broker.mock_gtts.values() if g['transaction_type'] == 'SELL']
        assert len(sells) == 2
        assert all(g['product_type'] == 'INTRADAY' for g in sells)  # exit nets the long

        assert eng.get_pending_protection('ENTRY:NIFTY:xyz', consume=False) is None  # consumed

    def test_partial_then_final_is_idempotent_to_cumulative_qty(self):
        eng, broker = make_engine()
        arm_call(eng, correlation='ENTRY:NIFTY:pp', qty=2)

        eng.handle_postback({'orderStatus': 'PART_TRADED', 'orderId': 'O1',
                             'userNote': 'ENTRY:NIFTY:pp', 'filledQty': 75})  # 1 lot
        st = eng._get_state('NIFTY')
        assert st['side'] == 'CALL' and st['quantity'] == 1
        assert eng.get_pending_protection('ENTRY:NIFTY:pp', consume=False) is not None  # not consumed

        eng.handle_postback({'orderStatus': 'TRADED', 'orderId': 'O1',
                             'userNote': 'ENTRY:NIFTY:pp', 'filledQty': 150})  # 2 lots
        st = eng._get_state('NIFTY')
        assert st['quantity'] == 2
        assert eng.get_pending_protection('ENTRY:NIFTY:pp', consume=False) is None  # consumed on final

    def test_duplicate_final_postback_is_noop(self):
        eng, broker = make_engine()
        arm_call(eng, correlation='ENTRY:NIFTY:dup')
        eng.handle_postback({'orderStatus': 'TRADED', 'orderId': 'O',
                             'userNote': 'ENTRY:NIFTY:dup', 'filledQty': 75})
        res = eng.handle_postback({'orderStatus': 'TRADED', 'orderId': 'O',
                                   'userNote': 'ENTRY:NIFTY:dup', 'filledQty': 75})
        assert res['source'] == 'conditional_fill_dup'


# ───────────────────────── T5: cancel / race ─────────────────────────
class TestPendingCancel:
    def test_exit_signal_while_pending_cancels_entry(self):
        eng, broker = make_engine()
        arm_call(eng, correlation='ENTRY:NIFTY:c1')
        res = eng.handle_signal('LONG_EXIT', {'underlying': 'NIFTY'})
        assert res['action'] == 'CANCELLED_PENDING_ENTRY'
        assert eng._get_state('NIFTY')['side'] == 'NONE'
        assert eng.get_pending_protection('ENTRY:NIFTY:c1', consume=False) is None

    def test_cancel_with_no_pending_errors(self):
        eng, _ = make_engine()
        res = eng.cancel_pending_entry('NIFTY')
        assert res['status'] == 'error'

    def test_fill_during_cancel_does_not_wipe_live_position(self):
        eng, broker = make_engine()
        arm_call(eng, correlation='ENTRY:NIFTY:race')

        # The fill lands DURING the broker cancel call → flips PENDING_CALL -> CALL.
        def flip_during_cancel(alert_id):
            s = eng._get_state('NIFTY')
            s['side'] = 'CALL'
            eng._set_state('NIFTY', s)
            return {"success": True}
        broker.cancel_conditional_order = flip_during_cancel

        res = eng.cancel_pending_entry('NIFTY')
        assert res['action'] == 'ENTRY_ALREADY_FILLED'
        assert eng._get_state('NIFTY')['side'] == 'CALL'  # not wiped


# ───────────────────────── T7: EOD flush ─────────────────────────
class TestFlush:
    def test_flush_cancels_pending(self):
        eng, broker = make_engine()
        arm_call(eng, correlation='ENTRY:NIFTY:f')
        res = eng.flush_pending_entries()
        assert 'NIFTY' in res['flushed']
        assert eng._get_state('NIFTY')['side'] == 'NONE'

    def test_flush_ignores_live_positions(self):
        eng, _ = make_engine()
        eng._set_state('NIFTY', {'side': 'CALL', 'security_id': 'x', 'quantity': 1})
        res = eng.flush_pending_entries()
        assert res['flushed'] == []
        assert eng._get_state('NIFTY')['side'] == 'CALL'


# ───────────────────────── T12: regressions ─────────────────────────
class TestRegressions:
    def test_R1_market_entry_path_unchanged(self):
        eng, broker = make_engine()
        broker.lot_map = {'SID_X': 75}
        res = eng.handle_signal('B', {
            'underlying': 'NIFTY',
            'itm': {'symbol': 'SYM', 'security_id': 'SID_X'},
            'idx_sec_id': '13', 'quantity': 1,
        })
        assert res['status'] == 'success' and res['action'] == 'OPENED_CONDITIONAL'
        assert eng._get_state('NIFTY')['side'] == 'CALL'

    def test_R2_market_fill_orderid_keyed_still_arms_bracket(self):
        eng, broker = make_engine()
        broker.lot_map = {'SID_X': 75}
        eng._set_state('NIFTY', {'side': 'CALL', 'symbol': 'SYM', 'security_id': 'SID_X',
                                 'idx_sec_id': '13', 'quantity': 1})
        eng.store_pending_protection('ORD_MKT', {
            'underlying': 'NIFTY', 'target_level': 24700, 'sl_level': 24550, 'quantity': 1})
        res = eng.handle_postback({'orderStatus': 'TRADED', 'orderId': 'ORD_MKT', 'tradedPrice': 100.0})
        assert res['source'] == 'order_fill'
        st = eng._get_state('NIFTY')
        assert st.get('idx_sl_alert_id') and st.get('idx_target_alert_id')
        assert st['entry_price'] == 100.0
