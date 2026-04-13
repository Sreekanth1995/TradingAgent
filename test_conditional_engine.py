import pytest
from unittest.mock import Mock, patch
from conditional_order_engine import ConditionalOrderEngine

class TestConditionalOrderEngine:
    def setup_method(self):
        self.mock_broker = Mock()
        self.mock_broker.get_itm_contract.return_value = {
            'symbol': 'NIFTY 25 MAY 22000 CE',
            'security_id': '12345',
            'opt_type': 'CE'
        }
        self.mock_broker.get_index_id.return_value = '13'
        self.mock_broker.get_ltp.return_value = 22050.0
        self.mock_broker.lot_map = {'12345': 25}
        
        self.engine = ConditionalOrderEngine(broker=self.mock_broker)
        # Clear storage
        self.engine.memory_store = {}
        
    def test_handle_buy_signal(self):
        # 1. Simulate BUY signal (e.g. from /ui-signal)
        leg_data = {
            'underlying': 'NIFTY',
            'quantity': 1,
            'current_price': 22050.0
        }
        
        # Mock successful market order placement
        self.mock_broker.place_buy_order.return_value = {'success': True, 'order_id': 'mock_entry_999'}
        
        res = self.engine.handle_signal('B', leg_data)
        
        # Verify
        assert res['status'] == 'success'
        assert res['action'] == 'OPENED_CONDITIONAL'
        
        # Broker should be called for an execution order
        self.mock_broker.place_buy_order.assert_called_once()
        args, kwargs = self.mock_broker.place_buy_order.call_args
        assert args[0] == 'NIFTY 25 MAY 22000 CE'
        assert args[1]['order_type'] == 'MARKET'
        assert args[1]['quantity'] == 1
        
        # State should be updated accurately
        state = self.engine._get_state('NIFTY')
        assert state['side'] == 'CALL'
        assert state['entry_id'] == 'mock_entry_999'

    def test_handle_exit_signal(self):
        # Set up active CE position state
        initial_state = {
            'side': 'CALL',
            'symbol': 'NIFTY 25 MAY 22000 CE',
            'security_id': '12345',
            'quantity': 1,
            'entry_id': 'mock_entry_999',
            'conditional_target_alert_id': 'alert_target',
            'idx_sl_alert_id': 'alert_sl'
        }
        self.engine._set_state('NIFTY', initial_state)
        
        res = self.engine.handle_signal('LONG_EXIT', {'underlying': 'NIFTY'})
        
        assert res['status'] == 'success'
        assert res['action'] == 'CLOSED_CONDITIONAL_CALL'
        
        # Check active conditional limits were cancelled
        self.mock_broker.cancel_conditional_order.assert_any_call('alert_target')
        self.mock_broker.cancel_conditional_order.assert_any_call('alert_sl')
        
        # Check square off market order was submitted
        self.mock_broker.place_order.assert_called_once()
        args, kwargs = self.mock_broker.place_order.call_args
        assert args[0] == 'NIFTY 25 MAY 22000 CE'
        assert args[1]['transaction_type'] == 'SELL'
        
        # State should be cleared safely
        state = self.engine._get_state('NIFTY')
        assert state['side'] == 'NONE'

    def test_set_index_boundaries(self):
        # Position must be active to set bound
        self.engine._set_state('NIFTY', {
            'side': 'CALL',
            'security_id': '12345',
            'quantity': 1
        })
        
        # Mock broker responses
        self.mock_broker.place_conditional_order.side_effect = [
            {'success': True, 'alert_id': 'SL_ALERT_1'},
            {'success': True, 'alert_id': 'TGT_ALERT_2'}
        ]
        
        res = self.engine.set_index_boundaries('NIFTY', target_level=22100.0, sl_level=22000.0)
        
        assert res['status'] == 'success'
        assert res['sl_id'] == 'SL_ALERT_1'
        assert res['target_id'] == 'TGT_ALERT_2'
        
        state = self.engine._get_state('NIFTY')
        assert state['idx_sl_alert_id'] == 'SL_ALERT_1'
        assert state['idx_target_alert_id'] == 'TGT_ALERT_2'
