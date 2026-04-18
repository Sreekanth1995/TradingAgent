import pytest
import json
from unittest.mock import MagicMock, patch
from server import app, _get_active_positions

@pytest.fixture
def client():
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client

def test_get_active_positions_empty():
    """Verify that no positions are returned when engine state is NONE."""
    with patch('server.super_order_engine') as mock_engine:
        mock_engine._get_state.return_value = {'side': 'NONE'}
        positions = _get_active_positions()
        assert positions == []

def test_get_active_positions_with_data():
    """Verify that active positions are correctly aggregated and PnL is calculated."""
    with patch('server.super_order_engine') as mock_engine, \
         patch('server.broker') as mock_broker:
        
        # Mock engine state for NIFTY
        mock_engine._get_state.side_effect = lambda u: {
            'side': 'CALL',
            'symbol': 'NIFTY_MOCK_24500_CE',
            'security_id': '13',
            'entry_price': 100.0,
            'quantity': 50,
            'range_position': 'INSIDE'
        } if u == "NIFTY" else {'side': 'NONE'}
        
        # Mock broker LTP
        mock_broker.get_ltp.return_value = 110.0
        
        positions = _get_active_positions()
        
        assert len(positions) == 1
        pos = positions[0]
        assert pos['underlying'] == 'NIFTY'
        assert pos['pnl_abs'] == 500.0 # (110 - 100) * 50
        assert pos['pnl_pct'] == 10.0
        assert pos['ltp'] == 110.0

def test_get_active_positions_missing_ltp():
    """Verify that '---' is returned when LTP is missing."""
    with patch('server.super_order_engine') as mock_engine, \
         patch('server.broker') as mock_broker:
        
        # Only NIFTY has a position
        mock_engine._get_state.side_effect = lambda u: {
            'side': 'PUT',
            'symbol': 'NIFTY_MOCK_24500_PE',
            'security_id': '13',
            'entry_price': 100.0,
            'quantity': 50
        } if u == 'NIFTY' else {'side': 'NONE'}
        
        # LTP is None (API Failure)
        mock_broker.get_ltp.return_value = None
        
        positions = _get_active_positions()
        
        assert len(positions) == 1
        pos = positions[0]
        assert pos['ltp'] == '---'
        assert pos['pnl_abs'] == '---'

def test_get_state_endpoint_mock(client):
    """Verify that /get-state returns active_positions array."""
    with patch('server.SECRET', 'test_secret'), \
         patch('server._get_active_positions') as mock_agg:
        
        mock_agg.return_value = [{"symbol": "MOCK_POS", "pnl_abs": 10.0}]
        
        resp = client.post('/get-state', json={
            'secret': 'test_secret',
            'underlying': 'NIFTY'
        })
        
        assert resp.status_code == 200
        data = resp.get_json()
        assert 'active_positions' in data
        assert len(data['active_positions']) == 1
        assert data['active_positions'][0]['symbol'] == "MOCK_POS"
