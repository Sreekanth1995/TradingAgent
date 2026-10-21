"""Unit tests for Groww broker integration."""

import pytest
from broker.groww.auth_service import GrowwAuthService
from broker.groww.instrument_service import GrowwInstrumentService
from broker.groww.order_service import GrowwOrderService
from broker.groww.client import GrowwClient
from broker.groww.mock_client import MockGrowwClient


class DummyRedis:
    def __init__(self):
        self.store = {}

    def get(self, key):
        return self.store.get(key)

    def set(self, key, val, ex=None):
        self.store[key] = val
        return True


def test_groww_auth_service_dry_run():
    r = DummyRedis()
    auth = GrowwAuthService(api_key="test_key", totp_secret="JBSWY3DPEHPK3PXP", redis_client=r, dry_run=True)
    res = auth.generate_access_token()
    assert res["status"] == "success"
    assert auth.access_token is not None
    assert r.get("tokens:groww:access_token") is not None

    status = auth.get_auth_status()
    assert status["broker"] == "groww"
    assert status["is_active"] is True
    assert status["has_api_key"] is True


def test_groww_instrument_service_symbol_formatting():
    inst = GrowwInstrumentService()
    sym = inst.format_trading_symbol("NIFTY", 24000, "CE", "2024-12-26")
    assert sym == "NIFTY24DEC24000CE"

    sym_pe = inst.format_trading_symbol("BANKNIFTY", 51500, "PE", "2024-12-26")
    assert sym_pe == "BANKNIFTY24DEC51500PE"

    itm = inst.get_itm_contract("NIFTY", "CALL", 24020, "2024-12-26")
    assert itm is not None
    assert itm["strike"] == 23950
    assert itm["option_type"] == "CE"
    assert itm["trading_symbol"] == "NIFTY24DEC23950CE"


def test_groww_order_service_dry_run():
    r = DummyRedis()
    auth = GrowwAuthService(redis_client=r, dry_run=True)
    auth.save_access_token("test_token")
    inst = GrowwInstrumentService(auth_service=auth)
    order_srv = GrowwOrderService(auth_service=auth, instrument_service=inst, dry_run=True)

    # Place regular order
    res = order_srv.place_order("NIFTY24DEC24000CE", {"quantity": 50, "transactionType": "BUY"})
    assert res["status"] == "success"
    assert "order_id" in res

    # Place super order (Market entry + OCO bracket)
    super_res = order_srv.place_super_order("NIFTY24DEC24000CE", {
        "quantity": 50,
        "transactionType": "BUY",
        "target_price": 120.0,
        "stop_loss_price": 90.0,
    })
    assert super_res["status"] == "success"
    assert "oco_order_id" in super_res

    # Positions and limits
    limits = order_srv.get_limits()
    assert limits["broker"] == "groww"
    assert limits["available_margin"] > 0


def test_groww_client_facade():
    r = DummyRedis()
    client = GrowwClient(redis_client=r, dry_run=True)
    auth_res = client.generate_access_token()
    assert auth_res["status"] == "success"

    order = client.place_buy_order("NIFTY24DEC24000CE", {"quantity": 50})
    assert order["status"] == "success"

    super_order = client.place_super_order("NIFTY24DEC24000CE", {
        "quantity": 50,
        "target_price": 110.0,
        "stop_loss_price": 85.0
    })
    assert super_order["status"] == "success"

    limits = client.get_fund_limits()
    assert limits["available_margin"] > 0


def test_mock_groww_client():
    mock = MockGrowwClient()
    mock.generate_access_token()
    assert mock.access_token is not None

    itm = mock.get_itm_contract("NIFTY", "CALL", 24020)
    assert itm is not None
    assert "NIFTY24DEC" in itm["trading_symbol"]

    res = mock.place_super_order(itm["trading_symbol"], {"quantity": 50, "transactionType": "BUY"})
    assert res["status"] == "success"
    assert len(mock.get_positions()) == 1

    mock.kill_switch()
    assert len(mock.get_positions()) == 0
