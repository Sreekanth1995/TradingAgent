"""DhanClient Facade orchestrating dedicated broker domain services.

Provides 100% backwards compatibility for existing callers while delegating all
underlying operations to specialized domain services:
- DhanAuthService
- DhanInstrumentService
- DhanMarketDataService
- DhanOrderService
- DhanConditionalOrderService
- DhanSafetyService
- DhanSocketService
"""

import os
import logging
import threading
from typing import Optional, Dict, Any, List, Callable

from broker.common import ExchangeSegment, TransactionType, OrderType, ProductType, Validity, BrokerDisagreement
from broker.auth_service import DhanAuthService
from broker.instrument_service import DhanInstrumentService
from broker.market_data_service import DhanMarketDataService
from broker.order_service import DhanOrderService
from broker.conditional_order_service import DhanConditionalOrderService
from broker.safety_service import DhanSafetyService
from broker.socket_service import DhanSocketService

logger = logging.getLogger("broker.client")


class DhanClient:
    def __init__(
        self,
        redis_client=None,
        activity_log_fn: Optional[Callable[[str, str], None]] = None,
        load_scrip: bool = True,
        csv_path: Optional[str] = None,
        auth_service: Optional[DhanAuthService] = None,
        instrument_service: Optional[DhanInstrumentService] = None,
        market_data_service: Optional[DhanMarketDataService] = None,
        order_service: Optional[DhanOrderService] = None,
        conditional_order_service: Optional[DhanConditionalOrderService] = None,
        safety_service: Optional[DhanSafetyService] = None,
        socket_service: Optional[DhanSocketService] = None,
    ):
        dry_run = os.getenv("DRY_RUN", "false").lower() == "true"

        # 1. Initialize Auth Service
        self.auth_service = auth_service or DhanAuthService(
            redis_client=redis_client,
            dry_run=dry_run,
        )

        # 2. Initialize Instrument Service (without auto-starting thread)
        self.instrument_service = instrument_service or DhanInstrumentService(
            csv_path=csv_path,
            load_scrip=load_scrip,
            alarm_fn=self._alarm,
            start_thread=False,
        )

        # 3. Initialize Market Data Service
        self.market_data_service = market_data_service or DhanMarketDataService(
            auth_service=self.auth_service,
            instrument_service=self.instrument_service,
        )

        # 4. Initialize Order Service
        self.order_service = order_service or DhanOrderService(
            auth_service=self.auth_service,
            instrument_service=self.instrument_service,
            market_data_service=self.market_data_service,
        )

        # 5. Initialize Conditional Order Service
        self.conditional_order_service = conditional_order_service or DhanConditionalOrderService(
            auth_service=self.auth_service,
            market_data_service=self.market_data_service,
        )

        # 6. Initialize Safety Service
        self.safety_service = safety_service or DhanSafetyService(
            order_service=self.order_service,
            auth_service=self.auth_service,
            conditional_order_service=self.conditional_order_service,
            activity_log_fn=activity_log_fn,
        )

        # 7. Initialize Socket Service
        self.socket_service = socket_service or DhanSocketService(
            auth_service=self.auth_service,
        )

        # Start background scrip master load calling self._load_scrip_master()
        # so any monkeypatched _load_scrip_master in tests is honored
        if load_scrip:
            def load_scrip_background():
                try:
                    self._load_scrip_master()
                    self.instrument_service.scrip_loaded = True
                    logger.info("✅ Scrip Master loaded successfully in background")
                except Exception as e:
                    logger.error(f"Failed to load Scrip Master: {e}")
                finally:
                    self.instrument_service._scrip_ready.set()

            threading.Thread(target=load_scrip_background, daemon=True).start()
        else:
            if hasattr(self.instrument_service, '_scrip_ready') and self.instrument_service._scrip_ready:
                self.instrument_service._scrip_ready.set()

    # --- Backwards Compatibility Properties & Setters ---

    @property
    def client_id(self):
        return self.auth_service.client_id

    @client_id.setter
    def client_id(self, val):
        self.auth_service.client_id = val

    @property
    def access_token(self):
        return self.auth_service.access_token

    @access_token.setter
    def access_token(self, val):
        self.auth_service.access_token = val

    @property
    def api_id(self):
        return self.auth_service.api_id

    @api_id.setter
    def api_id(self, val):
        self.auth_service.api_id = val

    @property
    def api_secret(self):
        return self.auth_service.api_secret

    @api_secret.setter
    def api_secret(self, val):
        self.auth_service.api_secret = val

    @property
    def r(self):
        return self.auth_service.r

    @r.setter
    def r(self, val):
        self.auth_service.r = val

    @property
    def dry_run(self):
        return self.auth_service.dry_run

    @dry_run.setter
    def dry_run(self, val):
        self.auth_service.dry_run = val

    @property
    def dhan(self):
        return self.auth_service.dhan

    @dhan.setter
    def dhan(self, val):
        self.auth_service.dhan = val

    @property
    def scrip_map(self):
        return self.instrument_service.scrip_map

    @scrip_map.setter
    def scrip_map(self, val):
        self.instrument_service.scrip_map = val

    @property
    def lot_map(self):
        return self.instrument_service.lot_map

    @lot_map.setter
    def lot_map(self, val):
        self.instrument_service.lot_map = val

    @property
    def exact_symbol_map(self):
        return self.instrument_service.exact_symbol_map

    @exact_symbol_map.setter
    def exact_symbol_map(self, val):
        self.instrument_service.exact_symbol_map = val

    @property
    def scrip_loaded(self):
        return self.instrument_service.scrip_loaded

    @scrip_loaded.setter
    def scrip_loaded(self, val):
        self.instrument_service.scrip_loaded = val

    @property
    def _scrip_ready(self):
        return self.instrument_service._scrip_ready

    @_scrip_ready.setter
    def _scrip_ready(self, val):
        self.instrument_service._scrip_ready = val

    @property
    def expiry_indices(self):
        return self.instrument_service.expiry_indices

    @expiry_indices.setter
    def expiry_indices(self, val):
        self.instrument_service.expiry_indices = val

    @property
    def scrip_csv_path(self):
        return self.instrument_service.scrip_csv_path

    @property
    def _ltp_cache(self):
        return self.market_data_service._ltp_cache

    @_ltp_cache.setter
    def _ltp_cache(self, val):
        self.market_data_service._ltp_cache = val

    @property
    def _ltp_cache_ttl(self):
        return self.market_data_service._ltp_cache_ttl

    @_ltp_cache_ttl.setter
    def _ltp_cache_ttl(self, val):
        self.market_data_service._ltp_cache_ttl = val

    @property
    def active_ws(self):
        return self.socket_service.active_ws

    @active_ws.setter
    def active_ws(self, val):
        self.socket_service.active_ws = val

    @property
    def _activity_log_fn(self):
        return self.safety_service.activity_log_fn

    @_activity_log_fn.setter
    def _activity_log_fn(self, val):
        self.safety_service.activity_log_fn = val
        if hasattr(self, 'instrument_service'):
            self.instrument_service.alarm_fn = self._alarm

    # --- Delegated Methods: Safety & Alarms ---

    def _alarm(self, msg: str, prefix: str = "🚨 ") -> None:
        self.safety_service.alarm(msg, prefix)

    def kill_switch(self) -> Dict[str, Any]:
        return self.safety_service.kill_switch()

    # --- Delegated Methods: Auth & Lifecycle ---

    def save_access_token(self, token: str) -> None:
        self.auth_service.save_access_token(token)
        if hasattr(self.socket_service, 'active_ws') and self.socket_service.active_ws:
            logger.info("Closing active websocket connection to force reconnection with new token.")

    def refresh_client(self, new_token: str) -> bool:
        return self.auth_service.refresh_client(new_token)

    def _sync_token_from_redis(self) -> bool:
        return self.auth_service.sync_token_from_redis()

    def get_consent_url(self) -> Optional[str]:
        return self.auth_service.get_consent_url()

    def consume_consent(self, token_id: str):
        return self.auth_service.consume_consent(token_id)

    def renew_token(self):
        return self.auth_service.renew_token()

    # --- Delegated Methods: Real-Time Sockets ---

    def start_order_update_listener(self, on_update: Callable[[str, str, Any], None]) -> None:
        self.socket_service.start_order_update_listener(on_update)

    # --- Delegated Methods: Instruments & Expiry ---

    def get_index_id(self, symbol: str) -> Optional[str]:
        return self.instrument_service.get_index_id(symbol)

    def _load_scrip_master(self) -> None:
        self.instrument_service._load_scrip_master()

    def reload_scrip_master(self, force_download: bool = True) -> int:
        return self.instrument_service.reload_scrip_master(force_download=force_download)

    def is_expiry_day(self, underlying: str) -> bool:
        return self.instrument_service.is_expiry_day(underlying)

    def get_nearest_expiry(self, symbol: str) -> Optional[str]:
        return self.instrument_service.get_nearest_expiry(symbol)

    def get_next_expiry(self, symbol: str) -> Optional[str]:
        return self.instrument_service.get_next_expiry(symbol)

    def get_itm_contract(self, underlying: str, side: str, spot_price: float) -> Optional[Dict[str, Any]]:
        return self.instrument_service.get_itm_contract(underlying, side, spot_price)

    def get_security_info_by_symbol(self, exact_symbol: str) -> Optional[Dict[str, Any]]:
        return self.instrument_service.get_security_info_by_symbol(exact_symbol)

    def _get_security_id(self, symbol: str, strike: float, opt_type: str, expiry: Optional[str] = None) -> Optional[str]:
        return self.instrument_service.get_security_id(symbol, strike, opt_type, expiry)

    # --- Delegated Methods: Market Data & Margin ---

    def _round_to_tick(self, price: float, tick: float = 0.05) -> float:
        return self.market_data_service.round_to_tick(price, tick)

    def get_index_spot_fallback(self, symbol: str) -> Optional[float]:
        return self.market_data_service.get_index_spot_fallback(symbol)

    def get_ltp(self, security_id: str, exchange_segment: str = ExchangeSegment.NSE_FNO) -> Optional[float]:
        return self.market_data_service.get_ltp(security_id, exchange_segment)

    def get_fund_limits(self) -> Dict[str, Any]:
        return self.market_data_service.get_fund_limits()

    def margin_calculator(self, order_data: Dict[str, Any]) -> Dict[str, Any]:
        return self.market_data_service.margin_calculator(order_data)

    def get_multi_margin_calculator(self, orders_list: List[Dict[str, Any]]) -> Dict[str, Any]:
        return self.market_data_service.get_multi_margin_calculator(orders_list)

    def calculate_lots_by_margin(self, security_id: str, transaction_type: str = 'BUY', ltp: float = 0) -> int:
        return self.market_data_service.calculate_lots_by_margin(security_id, transaction_type, ltp)

    # --- Delegated Methods: Standard Orders & Positions ---

    def place_buy_order(self, symbol: str, leg_data: Dict[str, Any]) -> Dict[str, Any]:
        return self.order_service.place_buy_order(symbol, leg_data)

    def place_sell_order(self, symbol: str, leg_data: Dict[str, Any]) -> Dict[str, Any]:
        return self.order_service.place_sell_order(symbol, leg_data)

    def place_order(self, symbol: str, leg_data: Dict[str, Any]) -> Dict[str, Any]:
        return self.order_service.place_order(symbol, leg_data)

    def _place_order(self, symbol: str, leg_data: Dict[str, Any], transaction_type: str) -> Dict[str, Any]:
        return self.order_service._place_order(symbol, leg_data, transaction_type)

    def cancel_order(self, order_id: str) -> Dict[str, Any]:
        return self.order_service.cancel_order(order_id)

    def modify_order(self, order_id: str, order_type: str, leg_data: Dict[str, Any]) -> Dict[str, Any]:
        return self.order_service.modify_order(order_id, order_type, leg_data)

    def get_order_status(self, order_id: str) -> Optional[Dict[str, Any]]:
        return self.order_service.get_order_status(order_id)

    def get_pending_orders(self, security_id: Optional[str] = None) -> List[Dict[str, Any]]:
        return self.order_service.get_pending_orders(security_id)

    def get_all_orders(self) -> List[Dict[str, Any]]:
        return self.order_service.get_all_orders()

    def get_positions(self) -> List[Dict[str, Any]]:
        return self.order_service.get_positions()

    # --- Delegated Methods: Super Orders (Native Brackets) ---

    def place_super_order(self, symbol: str, leg_data: Dict[str, Any]) -> Dict[str, Any]:
        return self.order_service.place_super_order(symbol, leg_data)

    def get_super_orders(self, security_id: Optional[str] = None) -> List[Dict[str, Any]]:
        return self.order_service.get_super_orders(security_id)

    def modify_super_target_leg(self, order_id: str, target_price: float) -> Dict[str, Any]:
        return self.order_service.modify_super_target_leg(order_id, target_price)

    def modify_super_sl_leg(self, order_id: str, stop_loss_price: float, trailing_jump: float = 1.0) -> Dict[str, Any]:
        return self.order_service.modify_super_sl_leg(order_id, stop_loss_price, trailing_jump)

    def modify_super_entry_leg(self, order_id: str, price: float, quantity: Optional[int] = None) -> Dict[str, Any]:
        return self.order_service.modify_super_entry_leg(order_id, price, quantity)

    def cancel_super_order(self, order_id: str, leg_name: str = 'ENTRY_LEG') -> Dict[str, Any]:
        return self.order_service.cancel_super_order(order_id, leg_name)

    # --- Delegated Methods: Conditional Orders (GTT) ---

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
    ) -> Dict[str, Any]:
        return self.conditional_order_service.place_conditional_order(
            sec_id, exchange_seg, quantity, operator, comparing_value,
            transaction_type, product_type, trigger_sec_id, user_note
        )

    def cancel_conditional_order(self, alert_id: str) -> Dict[str, Any]:
        return self.conditional_order_service.cancel_conditional_order(alert_id)

    def modify_conditional_order(self, alert_id: str, quantity: int, comparing_value: float) -> Dict[str, Any]:
        return self.conditional_order_service.modify_conditional_order(alert_id, quantity, comparing_value)

    def get_conditional_order_details(self, alert_id: str) -> Optional[Dict[str, Any]]:
        return self.conditional_order_service.get_conditional_order_details(alert_id)

    def get_all_gtt_orders(self) -> List[Dict[str, Any]]:
        return self.conditional_order_service.get_all_gtt_orders()
