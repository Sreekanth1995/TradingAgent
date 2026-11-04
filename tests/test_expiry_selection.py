import pytest
from datetime import datetime, timedelta
import pytz
from broker_dhan import DhanClient
from broker_mock import MockDhanClient

def test_expiry_selection_dhan_client(monkeypatch):
    # Mock _load_scrip_master so it doesn't read the file or download anything.
    monkeypatch.setattr(DhanClient, "_load_scrip_master", lambda self: None)
    
    client = DhanClient()
    # Ensure it's marked as loaded
    client.scrip_loaded = True
    client._scrip_ready.set()
    
    IST = pytz.timezone('Asia/Kolkata')
    today_str = datetime.now(IST).strftime('%Y-%m-%d')
    future_str = (datetime.now(IST) + timedelta(days=7)).strftime('%Y-%m-%d')
    far_future_str = (datetime.now(IST) + timedelta(days=14)).strftime('%Y-%m-%d')
    
    # 1. Test case: Nearest expiry is today, next week is in the future.
    # It should pick the next week expiry.
    client.scrip_map = {
        ("NIFTY", 24500.0, "CE", today_str): "11101",
        ("NIFTY", 24500.0, "CE", future_str): "11102",
        ("NIFTY", 24500.0, "CE", far_future_str): "11103",
    }
    
    # Verify is_expiry_day
    assert client.is_expiry_day("NIFTY") is True
    
    # Verify get_itm_contract picks next week
    contract = client.get_itm_contract("NIFTY", "CE", 24550.0)
    assert contract is not None
    assert contract["expiry"] == future_str
    assert contract["security_id"] == "11102"
    
    # 2. Test case: Nearest expiry is in the future.
    # It should pick the nearest expiry.
    client.scrip_map = {
        ("NIFTY", 24500.0, "CE", future_str): "11102",
        ("NIFTY", 24500.0, "CE", far_future_str): "11103",
    }
    
    # Verify is_expiry_day
    assert client.is_expiry_day("NIFTY") is False
    
    # Verify get_itm_contract picks nearest
    contract = client.get_itm_contract("NIFTY", "CE", 24550.0)
    assert contract is not None
    assert contract["expiry"] == future_str
    assert contract["security_id"] == "11102"

def test_expiry_selection_mock_client():
    client = MockDhanClient()
    
    IST = pytz.timezone('Asia/Kolkata')
    today_str = datetime.now(IST).strftime('%Y-%m-%d')
    future_str = (datetime.now(IST) + timedelta(days=7)).strftime('%Y-%m-%d')
    
    # Mock client nearest is today, so it should pick next week (today + 7 days)
    assert client.is_expiry_day("NIFTY") is True
    
    contract = client.get_itm_contract("NIFTY", "CE", 24550.0)
    assert contract is not None
    assert contract["expiry"] == future_str

def test_expiry_selection_only_today_available(monkeypatch):
    monkeypatch.setattr(DhanClient, "_load_scrip_master", lambda self: None)
    
    alarms = []
    def mock_alarm(msg, prefix="🚨 "):
        alarms.append((prefix, msg))
        
    client = DhanClient(activity_log_fn=mock_alarm)
    client.scrip_loaded = True
    client._scrip_ready.set()
    
    IST = pytz.timezone('Asia/Kolkata')
    today_str = datetime.now(IST).strftime('%Y-%m-%d')
    
    # Only today's expiry exists in scrip map
    client.scrip_map = {
        ("NIFTY", 24500.0, "CE", today_str): "11101",
    }
    
    # nearest expiry is today -> is_expiry_day is True
    assert client.is_expiry_day("NIFTY") is True
    
    # Resolving ITM contract should fail-closed and return None
    contract = client.get_itm_contract("NIFTY", "CE", 24550.0)
    assert contract is None
    
    # An alarm should have been fired
    assert len(alarms) == 1
    assert "fallback rejected" in alarms[0][1]
    assert "🚨" in alarms[0][0]


def test_banknifty_strike_step_and_itm_selection(monkeypatch):
    from constants import strike_step_for
    assert strike_step_for("NIFTY") == 50
    assert strike_step_for("FINNIFTY") == 50
    assert strike_step_for("BANKNIFTY") == 100

    monkeypatch.setattr(DhanClient, "_load_scrip_master", lambda self: None)
    client = DhanClient()
    client.scrip_loaded = True
    client._scrip_ready.set()

    future_exp = "2026-11-23"
    client.scrip_map = {
        ("BANKNIFTY", 55700.0, "CE", future_exp): "62174",
        ("BANKNIFTY", 55900.0, "PE", future_exp): "62182",
    }

    # At spot 55800:
    # ATM = round(55800 / 100) * 100 = 55800
    # ITM CE = 55800 - 100 = 55700
    # ITM PE = 55800 + 100 = 55900
    ce_contract = client.get_itm_contract("BANKNIFTY", "CE", 55800.0)
    assert ce_contract is not None
    assert ce_contract["strike"] == 55700.0
    assert ce_contract["security_id"] == "62174"

    pe_contract = client.get_itm_contract("BANKNIFTY", "PE", 55800.0)
    assert pe_contract is not None
    assert pe_contract["strike"] == 55900.0
    assert pe_contract["security_id"] == "62182"

