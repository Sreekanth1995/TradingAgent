"""Unit tests for modular broker domain services and DhanClient facade.

Verifies:
1. Each domain service satisfies its Protocol interface via isinstance check.
2. DhanClient correctly routes calls to each dedicated service.
3. Offline test capability with load_scrip=False.
4. All requests.* calls in broker/ specify timeouts.
"""

import re
import pytest
from pathlib import Path
from unittest.mock import MagicMock

from broker.interfaces import (
    AuthServiceInterface,
    InstrumentServiceInterface,
    MarketDataServiceInterface,
    OrderServiceInterface,
    ConditionalOrderServiceInterface,
    SafetyServiceInterface,
    SocketServiceInterface,
)
from broker.auth_service import DhanAuthService
from broker.instrument_service import DhanInstrumentService
from broker.market_data_service import DhanMarketDataService
from broker.order_service import DhanOrderService
from broker.conditional_order_service import DhanConditionalOrderService
from broker.safety_service import DhanSafetyService
from broker.socket_service import DhanSocketService
from broker.client import DhanClient


def test_interfaces_implemented_by_services():
    """Verify each service class satisfies its runtime-checkable protocol."""
    auth = DhanAuthService(dry_run=True)
    inst = DhanInstrumentService(load_scrip=False)
    mdata = DhanMarketDataService(auth_service=auth, instrument_service=inst)
    order = DhanOrderService(auth_service=auth, instrument_service=inst, market_data_service=mdata)
    cond = DhanConditionalOrderService(auth_service=auth, market_data_service=mdata)
    safety = DhanSafetyService(order_service=order, auth_service=auth)
    sock = DhanSocketService(auth_service=auth)

    assert isinstance(auth, AuthServiceInterface)
    assert isinstance(inst, InstrumentServiceInterface)
    assert isinstance(mdata, MarketDataServiceInterface)
    assert isinstance(order, OrderServiceInterface)
    assert isinstance(cond, ConditionalOrderServiceInterface)
    assert isinstance(safety, SafetyServiceInterface)
    assert isinstance(sock, SocketServiceInterface)


def test_dhan_client_offline_initialization():
    """Verify DhanClient can be initialized completely offline without background threads."""
    client = DhanClient(load_scrip=False)
    assert client.instrument_service.scrip_loaded is False
    assert client.instrument_service._scrip_ready.is_set()


def test_dhan_client_facade_delegation():
    """Verify DhanClient properly delegates to its underlying domain services."""
    mock_auth = MagicMock(spec=DhanAuthService)
    mock_inst = MagicMock(spec=DhanInstrumentService)
    mock_mdata = MagicMock(spec=DhanMarketDataService)
    mock_order = MagicMock(spec=DhanOrderService)
    mock_cond = MagicMock(spec=DhanConditionalOrderService)
    mock_safety = MagicMock(spec=DhanSafetyService)
    mock_sock = MagicMock(spec=DhanSocketService)

    client = DhanClient(
        load_scrip=False,
        auth_service=mock_auth,
        instrument_service=mock_inst,
        market_data_service=mock_mdata,
        order_service=mock_order,
        conditional_order_service=mock_cond,
        safety_service=mock_safety,
        socket_service=mock_sock,
    )

    # Test Auth delegation
    client.save_access_token("token_123")
    mock_auth.save_access_token.assert_called_once_with("token_123")

    # Test MarketData delegation
    mock_mdata.round_to_tick.return_value = 100.05
    assert client._round_to_tick(100.04) == 100.05
    mock_mdata.round_to_tick.assert_called_once_with(100.04, 0.05)

    # Test Instrument delegation
    mock_inst.get_index_id.return_value = "13"
    assert client.get_index_id("NIFTY") == "13"
    mock_inst.get_index_id.assert_called_once_with("NIFTY")

    # Test Order delegation
    client.cancel_order("ord_456")
    mock_order.cancel_order.assert_called_once_with("ord_456")

    # Test Conditional Order delegation
    client.cancel_conditional_order("alert_789")
    mock_cond.cancel_conditional_order.assert_called_once_with("alert_789")

    # Test Safety delegation
    client.kill_switch()
    mock_safety.kill_switch.assert_called_once()

    # Test Alarm delegation
    client._alarm("test alarm")
    mock_safety.alarm.assert_called_once_with("test alarm", "🚨 ")


def test_no_untimed_requests_in_broker_package():
    """Verify every requests call in broker/ passes a timeout parameter."""
    broker_dir = Path(__file__).resolve().parent.parent / "broker"
    pattern = re.compile(r"requests\.(get|post|put|delete|patch)\(")
    offenders = []

    for py_file in broker_dir.glob("*.py"):
        src = py_file.read_text()
        for m in pattern.finditer(src):
            start = m.end() - 1
            depth = 0
            i = start
            while i < len(src):
                ch = src[i]
                if ch == "(":
                    depth += 1
                elif ch == ")":
                    depth -= 1
                    if depth == 0:
                        end = i
                        break
                i += 1
            else:
                offenders.append((py_file.name, m.start(), "unbalanced parens"))
                continue

            block = src[start:end + 1]
            if "timeout=" not in block:
                line_no = src.count("\n", 0, m.start()) + 1
                offenders.append((py_file.name, line_no, block.replace("\n", "\\n")[:100]))

    assert offenders == [], f"Found untimed requests calls in broker/: {offenders}"


def test_zero_downtime_scrip_reload_preserves_maps():
    """Verify reload_scrip_master preserves existing maps if new source fails or is invalid."""
    inst = DhanInstrumentService(load_scrip=False)
    inst.scrip_map = {("NIFTY", 22000.0, "CE", "2026-10-15"): "12345"}
    inst.lot_map = {"12345": 50}
    inst.scrip_loaded = True

    # Point to nonexistent path
    inst._csv_path = "/nonexistent/test_scrip.csv"

    # Attempt reload with force_download=False so it tries local nonexistent file
    count = inst.reload_scrip_master(force_download=False)
    assert count == 1
    # Existing maps remain 100% intact
    assert inst.scrip_map[("NIFTY", 22000.0, "CE", "2026-10-15")] == "12345"
    assert inst.lot_map["12345"] == 50


def test_fail_closed_lot_guard_when_scrip_loaded():
    """Verify place_order and place_super_order fail-closed if security_id is missing from lot_map."""
    auth = DhanAuthService(dry_run=True)
    inst = DhanInstrumentService(load_scrip=False)
    inst.lot_map = {"12345": 25}
    inst.scrip_loaded = True  # Marks that scrip is loaded

    mdata = DhanMarketDataService(auth_service=auth, instrument_service=inst)
    order = DhanOrderService(auth_service=auth, instrument_service=inst, market_data_service=mdata)

    # Placing an order with unknown sec_id "99999" must fail-closed
    res = order.place_order(
        symbol="NIFTY-UNKNOWN",
        leg_data={"security_id": "99999", "quantity": 1, "transaction_type": "BUY"}
    )
    assert res.get("success") is False
    assert "lot_map miss" in res.get("error", "")

    # Super order with unknown sec_id "99999" must also fail-closed
    super_res = order.place_super_order(
        symbol="NIFTY-UNKNOWN",
        leg_data={
            "security_id": "99999",
            "quantity": 1,
            "target_price": 100.0,
            "stop_loss_price": 50.0,
        }
    )
    assert super_res.get("success") is False
    assert "lot_map miss" in super_res.get("error", "")


def test_kill_switch_cancels_super_order_legs_before_squareoff():
    """Verify kill_switch cancels super order legs and pending orders before squaring off positions."""
    mock_order = MagicMock()
    mock_auth = MagicMock()
    mock_auth.dry_run = True

    # Setup mock super order legs
    mock_order.get_super_orders.return_value = [
        {"orderId": "BO_101", "legName": "TARGET_LEG", "tradingSymbol": "NIFTY-22000-CE"},
        {"orderId": "BO_101", "legName": "STOP_LOSS_LEG", "tradingSymbol": "NIFTY-22000-CE"}
    ]
    mock_order.cancel_super_order.return_value = {"success": True}

    # Setup mock pending general orders
    mock_order.get_all_orders.return_value = [
        {"orderId": "ORD_201", "orderStatus": "PENDING", "tradingSymbol": "NIFTY-22100-PE"}
    ]
    mock_order.cancel_order.return_value = {"success": True}

    # Setup mock open positions
    mock_order.get_positions.return_value = [
        {"securityId": "12345", "netQty": 50, "tradingSymbol": "NIFTY-22000-CE"}
    ]

    safety = DhanSafetyService(order_service=mock_order, auth_service=mock_auth)
    result = safety.kill_switch()

    # Verify Super Order legs were cancelled via cancel_super_order
    assert len(result["cancelled_super_legs"]) == 2
    assert mock_order.cancel_super_order.call_count == 2
    mock_order.cancel_super_order.assert_any_call("BO_101", "TARGET_LEG")
    mock_order.cancel_super_order.assert_any_call("BO_101", "STOP_LOSS_LEG")

    # Verify standard order cancelled via cancel_order
    assert len(result["cancelled"]) == 1
    mock_order.cancel_order.assert_called_once_with("ORD_201")

    # Verify positions were squared off
    assert len(result["squaredoff"]) == 1
    assert result["squaredoff"][0]["symbol"] == "NIFTY-22000-CE"

