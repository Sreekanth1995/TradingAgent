"""MockFlatTradeClient for offline testing without live network calls."""

import uuid
from typing import Optional, Dict, Any, List


class MockFlatTradeClient:
    def __init__(self, redis_client=None, dry_run: bool = True):
        self.redis_client = redis_client
        self.dry_run = dry_run
        self.broker_name = "flattrade"
        self.orders: Dict[str, Dict[str, Any]] = {}
        self.positions: List[Dict[str, Any]] = []
        self.token = "mock_flattrade_token_12345"
        self.ucc = "FT_MOCK_USER"
        self.available_margin = 750000.0

    def generate_token(self, request_code: Optional[str] = None) -> Dict[str, Any]:
        self.token = f"mock_ft_token_{uuid.uuid4().hex[:8]}"
        return {"status": "success", "token": self.token}

    def renew_token(self) -> Dict[str, Any]:
        return self.generate_token()

    def get_auth_status(self) -> Dict[str, Any]:
        return {
            "broker": "flattrade",
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
            "broker": "flattrade",
            "underlying": underlying,
            "strike": strike,
            "option_type": opt_type,
            "trading_symbol": symbol,
            "security_id": symbol,
            "exchange": "NFO",
            "product_type": "I",
        }

    def place_order(self, symbol: str, leg_data: Dict[str, Any]) -> Dict[str, Any]:
        oid = f"FT_{uuid.uuid4().hex[:8].upper()}"
        record = {
            "order_id": oid,
            "noren_order_id": oid,
            "symbol": symbol,
            "status": "success",
            "order_status": "COMPLETE",
            "leg_data": leg_data,
        }
        self.orders[oid] = record
        qty = int(leg_data.get("quantity", 1))
        tx = leg_data.get("transactionType", "BUY").upper()
        signed_qty = qty if tx in ("BUY", "B", "LONG") else -qty
        self.positions.append({
            "broker": "flattrade",
            "tradingSymbol": symbol,
            "netQty": signed_qty,
            "costPrice": float(leg_data.get("price", 100.0)),
            "realizedProfit": 0.0,
            "unrealizedProfit": 0.0,
            "product": "I",
        })
        return record

    def place_super_order(self, symbol: str, leg_data: Dict[str, Any]) -> Dict[str, Any]:
        entry = self.place_order(symbol, leg_data)
        sl_id = f"FT_SL_{uuid.uuid4().hex[:8].upper()}"
        entry["sl_order_id"] = sl_id
        return entry

    def modify_order(self, order_id: str, order_type: str, leg_data: Dict[str, Any]) -> Dict[str, Any]:
        if order_id in self.orders:
            self.orders[order_id]["leg_data"].update(leg_data)
        return {"status": "success", "order_id": order_id}

    def cancel_order(self, order_id: str) -> Dict[str, Any]:
        if order_id in self.orders:
            self.orders[order_id]["order_status"] = "CANCELLED"
        return {"status": "success", "order_id": order_id}

    def get_positions(self) -> List[Dict[str, Any]]:
        return list(self.positions)

    def get_limits(self) -> Dict[str, Any]:
        return {
            "broker": "flattrade",
            "available_margin": self.available_margin,
            "used_margin": 10000.0,
        }

    def get_fund_limits(self) -> Dict[str, Any]:
        return self.get_limits()

    def kill_switch(self) -> Dict[str, Any]:
        self.positions.clear()
        return {"status": "success", "broker": "flattrade", "flattened": []}
