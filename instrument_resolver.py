import logging

from constants import index_id_for, IDX_SEGMENT

logger = logging.getLogger(__name__)

def calculate_quantity_from_margin(broker, itm):
    """
    Returns lot count based on available margin and the real Dhan margin API.
    Delegates to broker.calculate_lots_by_margin(); falls back to 1 lot on error.
    """
    try:
        sec_id = itm.get('security_id')
        ltp = broker.get_ltp(sec_id) or 0
        return broker.calculate_lots_by_margin(sec_id, 'BUY', ltp)
    except Exception as e:
        logger.warning(f"calculate_quantity_from_margin failed: {e} — defaulting to 1 lot")
        return 1


def resolve_index_spot(broker, underlying, leg):
    """
    Resolves the Index spot price for a given underlying.
    """
    if not broker:
        return 0.0
        
    idx_id = index_id_for(underlying)

    spot_index = float(leg.get('spot_index') or 0)
    if spot_index <= 0 and idx_id:
        # Dhan API v2 expects exchange_segment="IDX_I" for Index LTP
        spot_index = broker.get_ltp(idx_id, exchange_segment=IDX_SEGMENT) or 0.0
        
    return spot_index

def round_to_tick(value, tick=0.05):
    """Round a price to the nearest exchange tick (default 0.05)."""
    return round(round(float(value) / tick) * tick, 2)


def derive_entry_trigger(entry_index, spot_index, min_gap=0.05, max_gap_pct=0.25):
    """
    Decide the index-level trigger for a CONDITIONAL entry.

    The operator is derived purely from where the entry level sits relative to
    current spot, so one rule covers breakout entries and dip entries for both
    CALL and PUT:

        entry above spot  -> ABOVE  (fire when the index RISES to the level)
        entry below spot  -> BELOW  (fire when the index FALLS to the level)

    Both values are tick-rounded so the already-crossed check uses the SAME value
    that gets sent to the broker.

    Returns (ok: bool, result: dict).
      ok  -> {"operator": "ABOVE"|"BELOW", "comparing_value": float}
      not -> {"reason": str}   (caller should REJECT and tell the operator)
    """
    try:
        entry = float(entry_index)
        spot = float(spot_index)
    except (TypeError, ValueError):
        return False, {"reason": "entry_index and spot_index must be numbers"}

    if entry <= 0:
        return False, {"reason": f"entry_index must be positive, got {entry}"}
    if spot <= 0:
        return False, {"reason": "spot must be positive to derive the entry trigger"}

    # Fat-finger guard: an entry implausibly far from spot is almost certainly an error.
    if abs(entry - spot) > spot * max_gap_pct:
        pct = int(max_gap_pct * 100)
        return False, {"reason": f"entry_index {entry} is more than {pct}% from spot {spot} — rejected as implausible"}

    entry_r = round_to_tick(entry)
    spot_r = round_to_tick(spot)
    gap = round(entry_r - spot_r, 2)

    # Tie / already-at-level: indistinguishable from already-crossed -> reject.
    if abs(gap) < min_gap:
        return False, {"reason": f"entry_index {entry_r} is at/too close to spot {spot_r} (already crossed) — rejected"}

    operator = "ABOVE" if gap > 0 else "BELOW"
    return True, {"operator": operator, "comparing_value": entry_r}


def validate_sl_target(side, ref_level, sl_index, target_index):
    """
    Validate SL/Target index levels against a reference level (entry for a
    conditional entry, or spot for an immediate entry).

        CALL: SL must be BELOW ref, Target ABOVE ref.
        PUT : SL must be ABOVE ref, Target BELOW ref.

    Returns (ok: bool, reason: str|None).
    """
    try:
        ref = float(ref_level)
        sl = float(sl_index)
        tgt = float(target_index)
    except (TypeError, ValueError) as e:
        return False, f"Invalid SL/Target/ref value: {e}"

    label = "CALL" if side == 'CALL' else "PUT"
    if side == 'CALL':
        if sl >= ref:
            return False, f"{label} SL ({sl}) must be below entry/ref ({ref})"
        if tgt <= ref:
            return False, f"{label} Target ({tgt}) must be above entry/ref ({ref})"
    else:
        if sl <= ref:
            return False, f"{label} SL ({sl}) must be above entry/ref ({ref})"
        if tgt >= ref:
            return False, f"{label} Target ({tgt}) must be below entry/ref ({ref})"
    return True, None


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


