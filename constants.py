"""Shared constants — single source of truth for index identifiers and segments.

No imports here, so any module (brokers, server, engines, resolver) can import
this without risk of a circular import.
"""

# Dhan index security IDs.
INDEX_NAME_TO_ID = {
    "NIFTY": "13",
    "BANKNIFTY": "25",
    "FINNIFTY": "27",
}
INDEX_ID_TO_NAME = {v: k for k, v in INDEX_NAME_TO_ID.items()}
INDEX_IDS = frozenset(INDEX_NAME_TO_ID.values())  # {"13", "25", "27"}

# Dhan exchange segment for index LTP fetches and index-triggered conditions.
IDX_SEGMENT = "IDX_I"

# Product type for options legs. MUST be identical across the entry order, the
# SL/Target GTT exits, and the manual exit — otherwise the exit SELL opens a new
# short instead of netting the long position. INTRADAY matches the direct market
# entry in broker_dhan._place_order (ProductType.INTRADAY).
OPTIONS_PRODUCT_TYPE = "INTRADAY"


def index_id_for(underlying):
    """Name -> Dhan index security id ('NIFTY' -> '13'). None if unknown."""
    if not underlying:
        return None
    return INDEX_NAME_TO_ID.get(str(underlying).upper())


def index_name_for(sec_id):
    """Dhan index security id -> name ('13' -> 'NIFTY'). None if unknown."""
    return INDEX_ID_TO_NAME.get(str(sec_id))


def is_index_id(sec_id):
    """True if sec_id is a known Dhan index security id."""
    return str(sec_id) in INDEX_IDS
