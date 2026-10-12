"""Shared constants, enums, and error contracts for broker domain."""

import logging
from dhanhq import dhanhq
from dhanhq.orderupdate import OrderSocket
from constants import index_id_for, index_name_for, is_index_id, IDX_SEGMENT

logger = logging.getLogger("broker")

DHAN_AVAILABLE = True


class ExchangeSegment:
    NSE_FNO = "NSE_FNO"
    NSE_EQ = "NSE_EQ"
    BSE_EQ = "BSE_EQ"
    INDEX = "IDX_I"  # Alias for index LTP fetching


class TransactionType:
    BUY = "BUY"
    SELL = "SELL"


class OrderType:
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP_LOSS = "STOP_LOSS"
    STOP_LOSS_MARKET = "STOP_LOSS_MARKET"


class ProductType:
    INTRADAY = "INTRADAY"
    CNC = "CNC"
    MARGIN = "MARGIN"
    CO = "CO"
    BO = "BO"


class Validity:
    DAY = "DAY"
    IOC = "IOC"


_BROKER_DISAGREEMENT_RESERVED = frozenset({
    "success", "status", "reason", "alarm_msg", "error",
})


def BrokerDisagreement(reason, alarm_msg=None, **fields):
    """Canonical return shape for any path where the broker disagrees with the engine."""
    collisions = _BROKER_DISAGREEMENT_RESERVED & fields.keys()
    if collisions:
        raise ValueError(
            f"BrokerDisagreement: reserved keys {sorted(collisions)} cannot be "
            f"passed via **fields — they're set by the helper itself"
        )
    return {
        **fields,
        "success": False,
        "status": "broker_disagreement",
        "reason": reason,
        "alarm_msg": alarm_msg,
        "error": alarm_msg or reason,
    }
