"""Unit tests for FlatTrade broker integration."""

import pytest
from broker.flattrade.auth_service import FlatTradeAuthService
from broker.flattrade.instrument_service import FlatTradeInstrumentService
from broker.flattrade.order_service import FlatTradeOrderService
from broker.flattrade.client import FlatTradeClient
from broker.flattrade.mock_client import MockFlatTradeClient


class DummyRedis:
    def __init__(self):
        self.store = {}

    def get(self, key):
        return self.store.get(key)

    def set(self, key, val, ex=None):
        self.store[key] = val
        return True


def test_flattrade_auth_service_dry_run():
    r = DummyRedis()
    auth = FlatTradeAuthService(
        user_id="FT0123",
        api_key="ft_api_key",
        api_secret="ft_api_secret",
        totp_key="JBSWY3DPEHPK3PXP",
        redis_client=r,
        dry_run=True,
    )
    res = auth.generate_token()
    assert res["status"] == "success"
    assert auth.token is not None
    assert r.get("tokens:flattrade:token") is not None

    status = auth.get_auth_status()
    assert status["broker"] == "flattrade"
    assert status["is_active"] is True
    assert status["ucc"] == "FT0123"


def test_flattrade_instrument_service():
    inst = FlatTradeInstrumentService()
    sym = inst.format_trading_symbol("NIFTY", 24000, "CE", "2024-12-26")
    assert sym == "NIFTY24DEC24000CE"

    itm = inst.get_itm_contract("NIFTY", "PUT", 24020, "2024-12-26")
    assert itm is not None
    assert itm["strike"] == 24050
    assert itm["option_type"] == "PE"
    assert itm["exchange"] == "NFO"


def test_flattrade_order_service_dry_run():
    r = DummyRedis()
    auth = FlatTradeAuthService(redis_client=r, dry_run=True)
    auth.save_token("test_token")
    inst = FlatTradeInstrumentService(auth_service=auth)
    order_srv = FlatTradeOrderService(auth_service=auth, instrument_service=inst, dry_run=True)

    # Place order
    res = order_srv.place_order("NIFTY24DEC24000CE", {"quantity": 50, "transactionType": "BUY"})
    assert res["status"] == "success"
    assert "order_id" in res

    # Place super order (Market entry + SL arming)
    super_res = order_srv.place_super_order("NIFTY24DEC24000CE", {
        "quantity": 50,
        "transactionType": "BUY",
        "stop_loss_price": 95.0,
    })
    assert super_res["status"] == "success"
    assert "sl_order_id" in super_res

    # Limits
    limits = order_srv.get_limits()
    assert limits["broker"] == "flattrade"
    assert limits["available_margin"] > 0


def test_flattrade_client_facade():
    r = DummyRedis()
    client = FlatTradeClient(redis_client=r, dry_run=True)
    res = client.generate_token()
    assert res["status"] == "success"

    order = client.place_buy_order("NIFTY24DEC24000CE", {"quantity": 50})
    assert order["status"] == "success"

    super_order = client.place_super_order("NIFTY24DEC24000CE", {
        "quantity": 50,
        "stop_loss_price": 85.0
    })
    assert super_order["status"] == "success"


def test_mock_flattrade_client():
    mock = MockFlatTradeClient()
    mock.generate_token()
    assert mock.token is not None

    itm = mock.get_itm_contract("NIFTY", "CALL", 24020)
    assert itm is not None

    res = mock.place_super_order(itm["trading_symbol"], {"quantity": 50, "transactionType": "BUY"})
    assert res["status"] == "success"
    assert len(mock.get_positions()) == 1

    mock.kill_switch()
    assert len(mock.get_positions()) == 0
