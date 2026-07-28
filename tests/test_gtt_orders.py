import pytest
from unittest.mock import patch, MagicMock
from server import app

@pytest.fixture
def client():
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client

def test_gtt_orders_unauthorized(client):
    """Verify endpoint rejects requests with invalid secret."""
    resp = client.post('/gtt-orders', json={"secret": "wrong_secret"})
    assert resp.status_code == 401
    assert resp.get_json()['status'] == 'error'

def test_gtt_orders_success(client):
    """Verify GTT orders are retrieved and correctly divided into filled and notfilled."""
    mock_all_gtts = [
        # active/notfilled
        {
            "alertId": "GTT_ACTIVE_1",
            "alertStatus": "ACTIVE",
            "condition": {"comparingValue": 23900},
            "orders": [{"quantity": 100}]
        },
        {
            "alertId": "GTT_PENDING_1",
            "alertStatus": "PENDING",
            "condition": {"comparingValue": 24000},
            "orders": [{"quantity": 50}]
        },
        # filled
        {
            "alertId": "GTT_FILLED_1",
            "alertStatus": "TRIGGERED",
            "condition": {"comparingValue": 23800},
            "orders": [{"quantity": 75}]
        },
        {
            "alertId": "GTT_FILLED_2",
            "alertStatus": "FILLED",
            "condition": {"comparingValue": 23850},
            "orders": [{"quantity": 150}]
        },
        # other
        {
            "alertId": "GTT_CANCELLED_1",
            "alertStatus": "CANCELLED",
            "condition": {"comparingValue": 23700},
            "orders": [{"quantity": 250}]
        }
    ]

    with patch('server.broker') as mock_broker, \
         patch('server.SECRET', 'test_secret'):
        mock_broker.get_all_gtt_orders.return_value = mock_all_gtts

        resp = client.post('/gtt-orders', json={"secret": "test_secret"})
        assert resp.status_code == 200
        
        data = resp.get_json()
        assert data['status'] == 'success'
        
        # Check notfilled division
        notfilled_ids = [g['alertId'] for g in data['notfilled']]
        assert "GTT_ACTIVE_1" in notfilled_ids
        assert "GTT_PENDING_1" in notfilled_ids
        assert len(data['notfilled']) == 2
        
        # Check filled division
        filled_ids = [g['alertId'] for g in data['filled']]
        assert "GTT_FILLED_1" in filled_ids
        assert "GTT_FILLED_2" in filled_ids
        assert len(data['filled']) == 2
        
        # Check other division
        other_ids = [g['alertId'] for g in data['other']]
        assert "GTT_CANCELLED_1" in other_ids
        assert len(data['other']) == 1
