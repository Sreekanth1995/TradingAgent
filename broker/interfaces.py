"""Broker Service Protocols and Contracts.

Defines isolated interfaces for each specialized broker domain:
- AuthServiceInterface
- InstrumentServiceInterface
- MarketDataServiceInterface
- OrderServiceInterface
- ConditionalOrderServiceInterface
- SafetyServiceInterface
- SocketServiceInterface
"""

from typing import Protocol, runtime_checkable, Any, Dict, List, Optional, Callable


@runtime_checkable
class AuthServiceInterface(Protocol):
    def save_access_token(self, token: str) -> None:
        """Save access token to memory and Redis."""
        ...

    def refresh_client(self, new_token: str) -> None:
        """Update client access token and re-initialize."""
        ...

    def sync_token_from_redis(self) -> None:
        """Check Redis for newer token and sync if found."""
        ...

    def get_consent_url(self) -> Dict[str, Any]:
        """Generate Dhan login consent URL."""
        ...

    def consume_consent(self, token_id: str) -> Dict[str, Any]:
        """Exchange consent token for access token."""
        ...

    def renew_token(self) -> Dict[str, Any]:
        """Renew current access token for 24h."""
        ...


@runtime_checkable
class InstrumentServiceInterface(Protocol):
    @property
    def scrip_map(self) -> Dict[str, Any]: ...
    @property
    def lot_map(self) -> Dict[str, int]: ...
    @property
    def exact_symbol_map(self) -> Dict[str, str]: ...
    @property
    def scrip_loaded(self) -> bool: ...

    def is_expiry_day(self, underlying: str) -> bool:
        """Check if today is expiry day for underlying."""
        ...

    def get_nearest_expiry(self, symbol: str) -> Optional[str]:
        """Get closest expiry date string."""
        ...

    def get_next_expiry(self, symbol: str) -> Optional[str]:
        """Get second nearest expiry date string."""
        ...

    def get_itm_contract(self, underlying: str, side: str, spot_price: float) -> Optional[Dict[str, Any]]:
        """Resolve ITM option contract based on underlying, side, and spot price."""
        ...

    def get_security_info_by_symbol(self, exact_symbol: str) -> Optional[Dict[str, Any]]:
        """Look up security info from scrip map by exact symbol."""
        ...

    def get_security_id(self, symbol: str, strike: float, opt_type: str, expiry: Optional[str] = None) -> Optional[str]:
        """Resolve security ID from scrip map."""
        ...

    def get_index_id(self, symbol: str) -> Optional[str]:
        """Map underlying index symbol to security ID."""
        ...

    def reload_scrip_master(self, force_download: bool = True) -> int:
        """Forces a thread-safe reload of the scrip master without clearing active maps."""
        ...


@runtime_checkable
class MarketDataServiceInterface(Protocol):
    def get_ltp(self, security_id: str, exchange_segment: str = ...) -> float:
        """Fetch Last Traded Price with TTL caching."""
        ...

    def get_index_spot_fallback(self, symbol: str) -> float:
        """Get spot price using dedicated index endpoints or fallback."""
        ...

    def round_to_tick(self, price: float, tick: float = 0.05) -> float:
        """Round price to valid exchange tick."""
        ...

    def get_fund_limits(self) -> Dict[str, Any]:
        """Fetch available margin limits."""
        ...

    def margin_calculator(self, order_data: Dict[str, Any]) -> Dict[str, Any]:
        """Calculate required margin for single order."""
        ...

    def get_multi_margin_calculator(self, orders_list: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Calculate required margin for multiple orders."""
        ...

    def calculate_lots_by_margin(self, security_id: str, transaction_type: str = "BUY", ltp: float = 0) -> int:
        """Calculate max allowable lots based on available margin."""
        ...


@runtime_checkable
class OrderServiceInterface(Protocol):
    def place_buy_order(self, symbol: str, leg_data: Dict[str, Any]) -> Dict[str, Any]: ...
    def place_sell_order(self, symbol: str, leg_data: Dict[str, Any]) -> Dict[str, Any]: ...
    def place_order(self, symbol: str, leg_data: Dict[str, Any]) -> Dict[str, Any]: ...
    def cancel_order(self, order_id: str) -> Dict[str, Any]: ...
    def modify_order(self, order_id: str, order_type: str, leg_data: Dict[str, Any]) -> Dict[str, Any]: ...
    def get_order_status(self, order_id: str) -> Dict[str, Any]: ...
    def get_pending_orders(self, security_id: Optional[str] = None) -> List[Dict[str, Any]]: ...
    def get_all_orders(self) -> List[Dict[str, Any]]: ...
    def get_positions(self) -> List[Dict[str, Any]]: ...
    def place_super_order(self, symbol: str, leg_data: Dict[str, Any]) -> Dict[str, Any]: ...
    def get_super_orders(self, security_id: Optional[str] = None) -> List[Dict[str, Any]]: ...
    def modify_super_target_leg(self, order_id: str, target_price: float) -> Dict[str, Any]: ...
    def modify_super_sl_leg(self, order_id: str, stop_loss_price: float, trailing_jump: float = 1.0) -> Dict[str, Any]: ...
    def modify_super_entry_leg(self, order_id: str, price: float, quantity: Optional[int] = None) -> Dict[str, Any]: ...
    def cancel_super_order(self, order_id: str, leg_name: str = 'ENTRY_LEG') -> Dict[str, Any]: ...


@runtime_checkable
class ConditionalOrderServiceInterface(Protocol):
    def place_conditional_order(
        self,
        sec_id: str,
        exchange_seg: str,
        quantity: int,
        operator: str,
        comparing_value: float,
        transaction_type: str = "SELL",
        product_type: str = "MARGIN",
        trigger_sec_id: Optional[str] = None,
        user_note: Optional[str] = None
    ) -> Dict[str, Any]: ...

    def cancel_conditional_order(self, alert_id: str) -> Dict[str, Any]: ...
    def modify_conditional_order(self, alert_id: str, quantity: int, comparing_value: float) -> Dict[str, Any]: ...
    def get_conditional_order_details(self, alert_id: str) -> Dict[str, Any]: ...
    def get_all_gtt_orders(self) -> List[Dict[str, Any]]: ...


@runtime_checkable
class SafetyServiceInterface(Protocol):
    def alarm(self, msg: str, prefix: str = "🚨 ") -> None: ...
    def kill_switch(self) -> Dict[str, Any]: ...


@runtime_checkable
class SocketServiceInterface(Protocol):
    def start_order_update_listener(self, on_update: Callable[[Dict[str, Any]], None]) -> None: ...
