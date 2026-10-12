"""Broker Dhan adapter module.

Maintains 100% backwards compatibility by re-exporting domain constants, enums,
BrokerDisagreement, and DhanClient facade powered by modular broker services.
"""

from broker.common import (
    ExchangeSegment,
    TransactionType,
    OrderType,
    ProductType,
    Validity,
    BrokerDisagreement,
    DHAN_AVAILABLE,
    _BROKER_DISAGREEMENT_RESERVED,
    logger,
)
from broker.client import DhanClient
from broker.auth_service import DhanAuthService
from broker.instrument_service import DhanInstrumentService
from broker.market_data_service import DhanMarketDataService
from broker.order_service import DhanOrderService
from broker.conditional_order_service import DhanConditionalOrderService
from broker.safety_service import DhanSafetyService
from broker.socket_service import DhanSocketService

__all__ = [
    "DhanClient",
    "ExchangeSegment",
    "TransactionType",
    "OrderType",
    "ProductType",
    "Validity",
    "BrokerDisagreement",
    "DHAN_AVAILABLE",
    "_BROKER_DISAGREEMENT_RESERVED",
    "logger",
    "DhanAuthService",
    "DhanInstrumentService",
    "DhanMarketDataService",
    "DhanOrderService",
    "DhanConditionalOrderService",
    "DhanSafetyService",
    "DhanSocketService",
]
