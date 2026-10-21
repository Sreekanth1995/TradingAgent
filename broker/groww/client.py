"""GrowwClient Facade.

Provides a unified broker client facade implementing the standard broker protocols,
delegating to dedicated Groww domain services while maintaining identical caller interfaces.
"""

import os
import logging
from typing import Optional, Dict, Any, List

from broker.groww.auth_service import GrowwAuthService
from broker.groww.instrument_service import GrowwInstrumentService
from broker.groww.order_service import GrowwOrderService

logger = logging.getLogger("broker.groww.client")


class GrowwClient:
    def __init__(
        self,
        redis_client=None,
        api_key: Optional[str] = None,
        totp_secret: Optional[str] = None,
        dry_run: Optional[bool] = None,
        auth_service: Optional[GrowwAuthService] = None,
        instrument_service: Optional[GrowwInstrumentService] = None,
        order_service: Optional[GrowwOrderService] = None,
    ):
        if dry_run is None:
            dry_run = os.getenv("DRY_RUN", "false").lower() == "true"
        self.dry_run = dry_run
        self.broker_name = "groww"

        # 1. Auth Service
        self.auth_service = auth_service or GrowwAuthService(
            api_key=api_key,
            totp_secret=totp_secret,
            redis_client=redis_client,
            dry_run=dry_run,
        )

        # 2. Instrument Service
        self.instrument_service = instrument_service or GrowwInstrumentService(
            auth_service=self.auth_service,
        )

        # 3. Order Service
        self.order_service = order_service or GrowwOrderService(
            auth_service=self.auth_service,
            instrument_service=self.instrument_service,
            dry_run=dry_run,
        )

    # --- Auth Delegations ---
    def save_access_token(self, token: str) -> None:
        self.auth_service.save_access_token(token)

    def generate_access_token(self) -> Dict[str, Any]:
        return self.auth_service.generate_access_token()

    def renew_token(self) -> Dict[str, Any]:
        return self.auth_service.renew_token()

    def get_auth_status(self) -> Dict[str, Any]:
        return self.auth_service.get_auth_status()

    # --- Instrument Delegations ---
    def get_itm_contract(self, underlying: str, side: str, spot_price: float, expiry: Optional[str] = None) -> Optional[Dict[str, Any]]:
        return self.instrument_service.get_itm_contract(underlying, side, spot_price, expiry)

    # --- Order Delegations ---
    def place_buy_order(self, symbol: str, leg_data: Dict[str, Any]) -> Dict[str, Any]:
        leg_data = dict(leg_data)
        leg_data["transactionType"] = "BUY"
        return self.order_service.place_order(symbol, leg_data)

    def place_sell_order(self, symbol: str, leg_data: Dict[str, Any]) -> Dict[str, Any]:
        leg_data = dict(leg_data)
        leg_data["transactionType"] = "SELL"
        return self.order_service.place_order(symbol, leg_data)

    def place_order(self, symbol: str, leg_data: Dict[str, Any]) -> Dict[str, Any]:
        return self.order_service.place_order(symbol, leg_data)

    def place_super_order(self, symbol: str, leg_data: Dict[str, Any]) -> Dict[str, Any]:
        return self.order_service.place_super_order(symbol, leg_data)

    def modify_order(self, order_id: str, order_type: str, leg_data: Dict[str, Any]) -> Dict[str, Any]:
        return self.order_service.modify_order(order_id, order_type, leg_data)

    def cancel_order(self, order_id: str) -> Dict[str, Any]:
        return self.order_service.cancel_order(order_id)

    def get_positions(self) -> List[Dict[str, Any]]:
        return self.order_service.get_positions()

    def get_limits(self) -> Dict[str, Any]:
        return self.order_service.get_limits()

    def get_fund_limits(self) -> Dict[str, Any]:
        return self.order_service.get_limits()

    def kill_switch(self) -> Dict[str, Any]:
        return self.order_service.kill_switch()
