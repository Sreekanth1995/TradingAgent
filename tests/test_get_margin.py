import pytest
from unittest.mock import patch, MagicMock
from server import app, SECRET

@pytest.fixture
def client():
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client

def test_get_margin_unauthorized(client):
    """Rejects unauthorized requests without valid secret."""
    resp = client.post('/get-margin', json={"secret": "wrong"})
    assert resp.status_code == 401
    assert resp.get_json()['status'] == 'error'

def test_get_margin_normal_flow(client):
    """When broker provides live LTP and margin_calculator succeeds, sizes lots dynamically."""
    with patch('server.broker') as mock_broker:
        mock_broker.get_fund_limits.return_value = {
            "status": "success",
            "data": {"availabelBalance": 100000.0}
        }
        mock_broker.lot_map = {"45678": 65}
        mock_broker.get_itm_contract.return_value = {
            "symbol": "NIFTY-Oct2026-22800-CE",
            "security_id": "45678",
            "strike": 22800.0
        }
        mock_broker.get_ltp.return_value = 150.0
        mock_broker.margin_calculator.return_value = {
            "status": "success",
            "data": {"totalMargin": 9750.0}  # 150 * 65
        }

        resp = client.post('/get-margin', json={
            "secret": SECRET,
            "underlying": "NIFTY",
            "side": "CALL",
            "spot_index": 22850.0
        })

        assert resp.status_code == 200
        data = resp.get_json()
        assert data['status'] == 'success'
        assert data['suggested_lots'] == 8  # floor(100000 * 0.8 / 9750) = 8
        assert data['ltp'] == 150.0
        assert data['margin_per_lot'] == 9750.0
        assert data['estimated_pricing'] is False

def test_get_margin_missing_ltp_and_margin_calculator_failure(client):
    """
    CRITICAL: Validates the scenario from 2026-10-19 where Dhan option LTP is unavailable (0/None).
    Must not fail with HTTP 400! Must compute conservative estimated premium and size lots dynamically.
    """
    with patch('server.broker') as mock_broker:
        mock_broker.get_fund_limits.return_value = {
            "status": "success",
            "data": {"availabelBalance": 97817.07}
        }
        mock_broker.lot_map = {}  # missing from lot_map -> falls back to default 65
        mock_broker.get_itm_contract.return_value = {
            "symbol": "NIFTY-Oct2026-22800-CE",
            "security_id": "45678",
            "strike": 22800.0
        }
        # Broker returns None for LTP (untraded contract or off-hours)
        mock_broker.get_ltp.return_value = None
        # Margin calculator returns failure
        mock_broker.margin_calculator.return_value = {"status": "failure", "remarks": "LTP is 0"}

        resp = client.post('/get-margin', json={
            "secret": SECRET,
            "underlying": "NIFTY",
            "side": "CALL",
            "spot_index": 22850.0
        })

        assert resp.status_code == 200
        data = resp.get_json()
        assert data['status'] == 'success'
        assert data['estimated_pricing'] is True
        # spot=22850, strike=22800 -> intrinsic=50. ltp = max(120, 50 + 70) = 120.0
        assert data['ltp'] == 120.0
        assert data['lot_size'] == 65
        # margin_per_lot = 120 * 65 = 7800.0
        assert data['margin_per_lot'] == 7800.0
        # suggested_lots = floor(97817.07 * 0.8 / 7800.0) = floor(78253.65 / 7800) = 10 lots!
        assert data['suggested_lots'] == 10
        assert data['available_balance'] == 97817.07

def test_get_margin_put_side_missing_ltp(client):
    """Validates PUT side intrinsic fallback when LTP is absent."""
    with patch('server.broker') as mock_broker:
        mock_broker.get_fund_limits.return_value = {
            "status": "success",
            "data": {"availabelBalance": 50000.0}
        }
        mock_broker.lot_map = {"56789": 65}
        mock_broker.get_itm_contract.return_value = {
            "symbol": "NIFTY-Oct2026-23000-PE",
            "security_id": "56789",
            "strike": 23000.0
        }
        mock_broker.get_ltp.return_value = 0.0
        mock_broker.margin_calculator.side_effect = Exception("Dhan API Timeout")

        resp = client.post('/get-margin', json={
            "secret": SECRET,
            "underlying": "NIFTY",
            "side": "PUT",
            "spot_index": 22850.0
        })

        assert resp.status_code == 200
        data = resp.get_json()
        assert data['status'] == 'success'
        assert data['estimated_pricing'] is True
        # spot=22850, strike=23000 -> intrinsic=150. ltp = max(120, 150 + 70) = 220.0
        assert data['ltp'] == 220.0
        assert data['margin_per_lot'] == 220.0 * 65  # 14300.0
        assert data['suggested_lots'] == 2  # floor(50000 * 0.8 / 14300) = 2

def test_get_margin_fund_limits_failure_graceful_recovery(client):
    """When Dhan fund limits API errors, endpoint gracefully recovers with suggested_lots >= 1."""
    with patch('server.broker') as mock_broker:
        mock_broker.get_fund_limits.side_effect = Exception("Connection Reset")
        mock_broker.lot_map = {"45678": 65}
        mock_broker.get_itm_contract.return_value = {
            "symbol": "NIFTY-Oct2026-22800-CE",
            "security_id": "45678",
            "strike": 22800.0
        }
        mock_broker.get_ltp.return_value = 100.0
        mock_broker.margin_calculator.return_value = {
            "status": "success",
            "data": {"totalMargin": 6500.0}
        }

        resp = client.post('/get-margin', json={
            "secret": SECRET,
            "underlying": "NIFTY",
            "side": "CALL",
            "spot_index": 22850.0
        })

        assert resp.status_code == 200
        data = resp.get_json()
        assert data['status'] == 'success'
        assert data['available_balance'] == 0.0
        assert data['suggested_lots'] == 1  # Safe minimum fallback
