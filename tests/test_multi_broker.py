"""Unit tests for MultiBrokerManager."""

import pytest
from broker.manager import MultiBrokerManager
from broker.groww.mock_client import MockGrowwClient
from broker.flattrade.mock_client import MockFlatTradeClient
from broker_mock import MockDhanClient


class DummyRedis:
    def __init__(self):
        self.store = {}

    def get(self, key):
        return self.store.get(key)

    def set(self, key, val, ex=None):
        self.store[key] = val
        return True


def test_multi_broker_parallel_dispatch():
    r = DummyRedis()
    dhan = MockDhanClient(redis_client=r)
    groww = MockGrowwClient(redis_client=r)
    flat = MockFlatTradeClient(redis_client=r)

    mgr = MultiBrokerManager(
        redis_client=r,
        brokers={"dhan": dhan, "groww": groww, "flattrade": flat},
        default_broker="dhan",
    )

    # Place order across all 3 brokers
    res = mgr.place_super_order("NIFTY24DEC24000CE", {
        "quantity": 50,
        "transactionType": "BUY",
        "target_price": 120.0,
        "stop_loss_price": 90.0,
    })

    assert res["status"] == "success"
    assert "dhan" in res["results"]
    assert "groww" in res["results"]
    assert "flattrade" in res["results"]
    assert res["results"]["dhan"].get("order_id") or res["results"]["dhan"].get("success")
    assert res["results"]["groww"]["status"] == "success"
    assert res["results"]["flattrade"]["status"] == "success"

    # Verify positions exist across accounts
    positions = mgr.get_positions()
    brokers_with_pos = {p["broker"] for p in positions}
    assert "dhan" in brokers_with_pos or len(positions) >= 2


def test_multi_broker_account_tag_override():
    r = DummyRedis()
    dhan = MockDhanClient(redis_client=r)
    groww = MockGrowwClient(redis_client=r)
    flat = MockFlatTradeClient(redis_client=r)

    mgr = MultiBrokerManager(
        redis_client=r,
        brokers={"dhan": dhan, "groww": groww, "flattrade": flat},
    )

    # Target groww only
    res = mgr.place_super_order("NIFTY24DEC24000CE", {
        "quantity": 50,
        "transactionType": "BUY",
    }, accounts=["groww"])

    assert res["status"] == "success"
    assert "groww" in res["results"]
    assert "dhan" not in res["results"]
    assert "flattrade" not in res["results"]


def test_multi_broker_lot_multipliers():
    r = DummyRedis()
    dhan = MockDhanClient(redis_client=r)
    groww = MockGrowwClient(redis_client=r)

    mgr = MultiBrokerManager(
        redis_client=r,
        brokers={"dhan": dhan, "groww": groww},
    )

    mgr.set_lot_multiplier("dhan", 2)
    mgr.set_lot_multiplier("groww", 3)

    res = mgr.place_order("NIFTY24DEC24000CE", {"quantity": 1, "transactionType": "BUY"})
    assert res["status"] == "success"

    # Check that positions reflect the scaled lot quantities
    dhan_pos = [p for p in dhan.get_positions() if p["tradingSymbol"] == "NIFTY24DEC24000CE"]
    groww_pos = [p for p in groww.get_positions() if p["tradingSymbol"] == "NIFTY24DEC24000CE"]

    assert len(dhan_pos) > 0
    # MockDhanClient multiplies by 50 lot units: 1 * 2 * 50 = 100
    assert dhan_pos[0]["netQty"] == 100
    assert len(groww_pos) > 0
    # MockGrowwClient records raw quantity: 1 * 3 = 3
    assert groww_pos[0]["netQty"] == 3


def test_multi_broker_fail_safe_isolation():
    r = DummyRedis()
    dhan = MockDhanClient(redis_client=r)

    class FailingBroker:
        def place_super_order(self, symbol, leg):
            raise RuntimeError("API Outage on FailingBroker")

    failing = FailingBroker()
    mgr = MultiBrokerManager(
        redis_client=r,
        brokers={"dhan": dhan, "failing": failing},
    )

    res = mgr.place_super_order("NIFTY24DEC24000CE", {"quantity": 50, "transactionType": "BUY"})

    # Dhan still succeeds!
    assert res["status"] == "success"
    assert res["results"]["dhan"].get("order_id") or res["results"]["dhan"].get("success")
    assert res["results"]["failing"]["status"] == "error"
    assert "API Outage" in res["results"]["failing"]["message"]


def test_multi_broker_toggle_and_statuses():
    r = DummyRedis()
    dhan = MockDhanClient(redis_client=r)
    groww = MockGrowwClient(redis_client=r)

    mgr = MultiBrokerManager(
        redis_client=r,
        brokers={"dhan": dhan, "groww": groww},
    )

    statuses = mgr.get_account_statuses()
    assert len(statuses) == 2

    # Disable groww
    mgr.toggle_broker("groww", False)
    assert "groww" not in mgr.enabled_brokers

    # Place order should only go to dhan
    res = mgr.place_order("NIFTY24DEC24000CE", {"quantity": 50})
    assert "dhan" in res["results"]
    assert "groww" not in res["results"]

    # Re-enable groww
    mgr.toggle_broker("groww", True)
    assert "groww" in mgr.enabled_brokers
