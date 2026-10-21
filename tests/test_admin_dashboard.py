"""Tests for Multi-Broker Admin Dashboard and API endpoints."""

import pytest
import os
import json

# Ensure test mode
os.environ["USE_MOCK_API"] = "true"
os.environ["SECRET"] = "test_secret"

from server import app, multi_broker_manager


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def test_admin_dashboard_render(client):
    res = client.get("/admin")
    assert res.status_code == 200
    assert b"Broker Gateway & Auth Hub" in res.data
    assert b"Dhan" in res.data
    assert b"Groww" in res.data
    assert b"FlatTrade" in res.data


def test_api_accounts_get(client):
    res = client.get("/api/accounts")
    assert res.status_code == 200
    data = json.loads(res.data)
    assert data["status"] == "success"
    assert "accounts" in data
    assert len(data["accounts"]) >= 3
    brokers = [a["broker"] for a in data["accounts"]]
    assert "dhan" in brokers
    assert "groww" in brokers
    assert "flattrade" in brokers
    assert "margins" in data
    assert "positions" in data


def test_api_accounts_toggle(client):
    # Disable groww
    res = client.post("/api/accounts/toggle", json={"broker": "groww", "enabled": False})
    assert res.status_code == 200
    data = json.loads(res.data)
    assert data["status"] == "success"
    assert data["enabled"] is False

    # Check status reflects disabled
    status_res = client.get("/api/accounts")
    accounts = json.loads(status_res.data)["accounts"]
    groww_acc = next(a for a in accounts if a["broker"] == "groww")
    assert groww_acc["enabled"] is False

    # Re-enable groww
    res = client.post("/api/accounts/toggle", json={"broker": "groww", "enabled": True})
    assert res.status_code == 200


def test_api_accounts_lot_multiplier(client):
    res = client.post("/api/accounts/lot-multiplier", json={"broker": "groww", "multiplier": 4})
    assert res.status_code == 200
    data = json.loads(res.data)
    assert data["status"] == "success"
    assert data["multiplier"] == 4

    status_res = client.get("/api/accounts")
    accounts = json.loads(status_res.data)["accounts"]
    groww_acc = next(a for a in accounts if a["broker"] == "groww")
    assert groww_acc["lot_multiplier"] == 4

    # Reset back to 1
    client.post("/api/accounts/lot-multiplier", json={"broker": "groww", "multiplier": 1})


def test_api_accounts_login(client):
    res = client.post("/api/accounts/login/groww")
    assert res.status_code == 200
    data = json.loads(res.data)
    assert data["status"] == "success"

    res_flat = client.post("/api/accounts/login/flattrade")
    assert res_flat.status_code == 200
    data_flat = json.loads(res_flat.data)
    assert data_flat["status"] == "success"


def test_api_accounts_kill(client):
    res = client.post("/api/accounts/kill/all")
    assert res.status_code == 200
    data = json.loads(res.data)
    assert data["status"] == "success"


def test_api_accounts_ping(client):
    res = client.get("/api/accounts/ping")
    assert res.status_code == 200
    data = json.loads(res.data)
    assert data["status"] == "success"
    assert "dhan" in data["latencies"]
    assert "groww" in data["latencies"]
    assert "flattrade" in data["latencies"]
