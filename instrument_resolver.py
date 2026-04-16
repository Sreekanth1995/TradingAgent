import logging

logger = logging.getLogger(__name__)

def resolve_index_spot(broker, underlying, leg):
    """
    Resolves the Index spot price for a given underlying.
    """
    if not broker:
        return 0.0
        
    index_ids = {"NIFTY": "13", "BANKNIFTY": "25", "FINNIFTY": "27"}
    idx_id = index_ids.get(underlying.upper())
    
    spot_index = float(leg.get('spot_index', 0))
    if spot_index <= 0 and idx_id:
        # Dhan API v2 expects exchange_segment="IDX_I" for Index LTP
        spot_index = broker.get_ltp(idx_id, exchange_segment="IDX_I") or 0.0
        
    return spot_index

def resolve_call_itm(broker, underlying, spot_index):
    """
    Resolves the CALL ITM contract for the given index spot.
    """
    if not broker or spot_index <= 0:
        return None
    return broker.get_itm_contract(underlying, 'CE', spot_index)

def resolve_put_itm(broker, underlying, spot_index):
    """
    Resolves the PUT ITM contract for the given index spot.
    """
    if not broker or spot_index <= 0:
        return None
    return broker.get_itm_contract(underlying, 'PE', spot_index)


