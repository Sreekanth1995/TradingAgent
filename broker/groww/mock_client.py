"""MockGrowwClient for offline testing without live network calls."""

import uuid
from typing import Optional, Dict, Any, List


class MockGrowwClient:
    def __init__(self, redis_client=None, dry_run: bool = True):
        self.redis_client = redis_client
        self.dry_run = dry_run
        self.broker_name = "groww"
        self.orders: Dict[str, Dict[str, Any]] = {}
        self.positions: List[Dict[str, Any]] = []
        self.access_token = "mock_groww_token_12345"
        self.ucc = "GROWW_MOCK_USER"
        self.available_margin = 500000.0

    def generate_access_token(self) -> Dict[str, Any]:
        self.access_token = f"mock_groww_token_{uuid.uuid4().hex[:8]}"
        return {"status": "success", "access_token": self.access_token}

    def renew_token(self) -> Dict[str, Any]:
        return self.generate_access_token()

    def get_auth_status(self) -> Dict[str, Any]:
        return {
            "broker": "groww",
            "is_active": True,
            "ucc": self.ucc,
            "has_api_key": True,
            "has_totp": True,
            "masked_token": "mock...2345",
            "dry_run": self.dry_run,
        }

    def get_itm_contract(self, underlying: str, side: str, spot_price: float, expiry: Optional[str] = None) -> Optional[Dict[str, Any]]:
        strike = round(spot_price / 50) * 50 + (-50 if side.upper() in ('CE', 'CALL') else 50)
        opt_type = 'CE' if side.upper() in ('CE', 'CALL') else 'PE'
        symbol = f"{underlying.upper()}24DEC{int(strike)}{opt_type}"
        return {
            "broker": "groww",
            "underlying": underlying,
            "strike": strike,
            "option_type": opt_type,
            "trading_symbol": symbol,
            "security_id": symbol,
            "exchange": "NSE",
            "segment": "FNO",
        }

    def place_order(self, symbol: str, leg_data: Dict[str, Any]) -> Dict[str, Any]:
        oid = f"GRW_{uuid.uuid4().hex[:8].upper()}"
        record = {
            "order_id": oid,
            "groww_order_id": oid,
            "symbol": symbol,
            "status": "success",
            "order_status": "FILLED",
            "leg_data": leg_data,
        }
        self.orders[oid] = record
        qty = int(leg_data.get("quantity", 1))
        tx = leg_data.get("transactionType", "BUY").upper()
        signed_qty = qty if tx in ("BUY", "B", "LONG") else -qty
        self.positions.append({
            "broker": "groww",
            "tradingSymbol": symbol,
            "netQty": signed_qty,
            "costPrice": float(leg_data.get("price", 100.0)),
            "realizedProfit": 0.0,
            "unrealizedProfit": 0.0,
            "product": "MIS",
        })
        return record

    def place_super_order(self, symbol: str, leg_data: Dict[str, Any]) -> Dict[str, Any]:
        entry = self.place_order(symbol, leg_data)
        oco_id = f"GRW_OCO_{uuid.uuid4().hex[:8].upper()}"
        entry["oco_order_id"] = oco_id
        return entry

    def modify_order(self, order_id: str, order_type: str, leg_data: Dict[str, Any]) -> Dict[str, Any]:
        if order_id in self.orders:
            self.orders[order_id]["leg_data"].update(leg_data)
            return {"status": "success", "order_id": order_id}
        return {"status": "success", "order_id": order_id}

    def cancel_order(self, order_id: str) -> Dict[str, Any]:
        if order_id in self.orders:
            self.orders[order_id]["order_status"] = "CANCELLED"
        return {"status": "success", "order_id": order_id}

    def get_positions(self) -> List[Dict[str, Any]]:
        return list(self.positions)

    def get_limits(self) -> Dict[str, Any]:
        return {
            "broker": "groww",
            "available_margin": self.available_margin,
            "used_margin": 15000.0,
        }

    def get_fund_limits(self) -> Dict[str, Any]:
        return self.get_limits()

    def kill_switch(self) -> Dict[str, Any]:
        self.positions.clear()
        return {"status": "success", "broker": "groww", "flattened": []}
