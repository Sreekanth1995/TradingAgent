import os
import httpx
import json
from mcp.server.fastmcp import FastMCP
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Initialize FastMCP Server
mcp = FastMCP("TradingAgent_AI_Bridge")

# Configuration
SECRET = os.getenv("WEBHOOK_SECRET")
# Target points to Production VPS by default
BASE_URL = os.getenv("TRADING_AGENT_URL", "http://65.20.83.74")

async def call_api(endpoint: str, data: dict = None, method: str = "POST"):
    """Internal helper to communicate with the TradingAgent Flask server."""
    if data is None:
        data = {}
    data["secret"] = SECRET
    
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            if method == "POST":
                response = await client.post(f"{BASE_URL}{endpoint}", json=data)
            else:
                response = await client.get(f"{BASE_URL}{endpoint}", params=data)
            
            response.raise_for_status()
            return response.json()
        except Exception as e:
            return {"status": "error", "message": str(e)}

@mcp.tool()
async def get_trading_status(underlying: str = "NIFTY"):
    """
    Get the current trading status, including active positions, current trend, 
    and NIFTY/BANKNIFTY range positions.
    Active positions include boundary fields if set: `tgt_price`, `sl_price` 
    for premium protective orders, or `idx_target_level`, `idx_sl_level` for 
    Index-based Conditional GTT orders.
    
    IMPORTANT: The state object contains a `range_timestamp`. This timestamp points
    to the exact time the price changed direction. You must compare this timestamp with
    your previously cached timestamp. ONLY read the chart again if this timestamp has changed.
    """
    return await call_api("/get-state", {"underlying": underlying})

@mcp.tool()
async def get_ltp(instrument: str = "NIFTY"):
    """
    Fetch the current Last Traded Price (LTP) for a specific index or security ID.
    
    Args:
        instrument: Symbol name (NIFTY, BANKNIFTY) or Security ID (e.g., 100).
    """
    return await call_api("/get-ltp", {"instrument": instrument})

@mcp.tool()
async def get_itm_option(underlying: str = "NIFTY", side: str = "CE", spot_index: float = None):
    """
    Resolve the current ITM (In-The-Money) option contract for a given underlying and side.

    Use this BEFORE placing any super order or margin query to get the exact
    option symbol and security_id for the nearest ITM strike.

    Lot sizes for reference:
        NIFTY    = 75 units/lot   (step 50)
        BANKNIFTY = 15 units/lot  (step 100)
        FINNIFTY  = 40 units/lot  (step 50)

    Args:
        underlying:  Index symbol — NIFTY, BANKNIFTY, or FINNIFTY (default: NIFTY)
        side:        Option type — CE (Call/bullish) or PE (Put/bearish) (default: CE)
        spot_index:  Optional current spot price. If omitted the server fetches it live.

    Returns:
        security_id, symbol, strike, expiry, spot_index
    """
    payload = {"underlying": underlying, "side": side}
    if spot_index is not None:
        payload["spot_index"] = spot_index
    return await call_api("/get-itm", payload)

@mcp.tool()
async def place_conditional_order(action: str, underlying: str = "NIFTY", quantity: int = 1, spot_index: float = None, sl_index: float = None, target_index: float = None):
    """
    Manually place a trade order (CALL, PUT, EXIT_CALL, EXIT_PUT, EXIT_ALL).
    SL and Target are mandatory for CALL/PUT.
    
    Acceptance Criteria 1: Passing sl_index and target_index will automatically 
    attach Index-based GTT protection to the new position.
    
    Args:
        action: The trade action (CALL, PUT, EXIT_CALL, EXIT_PUT, EXIT_ALL)
        underlying: The symbol to trade (NIFTY, BANKNIFTY)
        quantity: Order quantity (default: 1 lot)
        sl_price: Optional Premium SL (Legacy)
        target_price: Optional Premium Target (Legacy)
        sl_index: [REQUIRED] Index SL level (e.g., 23430). Must be < entry for BUY.
        target_index: [REQUIRED] Index Target level (e.g., 23550).
    """
    return await call_api("/conditional-order", {
        "action": action, 
        "underlying": underlying, 
        "quantity": quantity,
        "spot_index": spot_index,
        "sl_index": sl_index,
        "target_index": target_index
    })

@mcp.tool()
async def modify_index_gtt_levels(underlying: str, idx_target_level: float, idx_sl_level: float, quantity: int = None):
    """
    Set or update GTT triggers for an active NIFTY/BANKNIFTY position.
    Triggers SELL on Option when Price crosses index level.

    Args:
        underlying: Symbol (NIFTY, BANKNIFTY)
        idx_target_level: [REQUIRED] Index level for target exit (e.g., 23550.50)
        idx_sl_level: [REQUIRED] Index level for stop loss exit (e.g., 23400.00)
        quantity: Optional lot quantity (defaults to active position size)
    """
    return await call_api("/conditional-index-order", {
        "underlying": underlying,
        "idx_target_level": idx_target_level,
        "idx_sl_level": idx_sl_level,
        "quantity": quantity
    })

@mcp.tool()
async def place_super_order(underlying: str, option: str, spot_price: float, target_price: float, sl_price: float, quantity: int = 1):
    """
    Places a Premium-based Super Order (Bracket Order).
    The broker handles SL/Target natively as legs of the entry order.
    
    Args:
        underlying: Symbol (NIFTY, BANKNIFTY)
        option: The direct exact option symbol to trade (e.g. NIFTY24APR22500CE)
        target_price: [REQUIRED] Premium target (e.g., 240)
        sl_price: [REQUIRED] Premium SL (e.g., 140)
        quantity: Lot size
    """
    return await call_api("/super-order", {
        "underlying": underlying,
        "option": option,
        "spot_price": spot_price,
        "target_price": target_price,
        "sl_price": sl_price,
        "quantity": quantity
    })

@mcp.tool()
async def modify_super_order(underlying: str, tgt_price: float, sl_price: float):
    """
    Updates the target and sl legs of an active Premium-based Super Order natively.

    Args:
        underlying: Symbol (NIFTY, BANKNIFTY)
        tgt_price: [REQUIRED] The new premium price level for target exit (e.g., 240.25)
        sl_price: [REQUIRED] The new premium price level for stop loss exit (e.g., 150.00)
    """
    return await call_api("/update-super-order", {
        "underlying": underlying,
        "tgt_price": tgt_price,
        "sl_price": sl_price
    })

@mcp.tool()
async def cancel_target_stoploss(underlying: str = "NIFTY"):
    """
    Cancel all active GTT conditional orders for a given underlying.
    """
    return await call_api("/cancel-conditional-orders", {"underlying": underlying})

@mcp.tool()
async def get_fund_limits():
    """
    Retrieve the current available fund limits from Dhan.
    Returns availableBalance, utilizedAmount, and withdrawableBalance.
    """
    # Note: Using POST internal proxy to manage SECRET safely
    return await call_api("/fundlimit", method="POST")

@mcp.tool()
async def get_margin_requirement(security_id: str, exchange_segment: str, transaction_type: str, quantity: int, price: float = 0.0, product_type: str = "INTRADAY"):
    """
    Calculate the margin required for a specific order before placement.

    ⚠️  IMPORTANT — Options Buying Capital Check:
    For buying NIFTY/BANKNIFTY option contracts the required capital is simply:
        premium_price × lot_size × quantity
    Use `calculate_options_buy_cost` for that instead — it returns the correct
    number without an API call.

    This tool is for SELLING options or for equity/futures margin queries where
    Dhan's margin API is meaningful.  Passing the INDEX security_id (e.g. '13'
    for NIFTY or '25' for BANKNIFTY) will always return zeros because the index
    itself is not a tradeable contract — you must pass the OPTION CONTRACT's
    security_id (obtained from the scrip master or instrument resolver).
    
    Args:
        security_id: Dhan Security ID of the OPTION CONTRACT (not the index).
        exchange_segment: NSE_FNO, NSE_EQ, etc.
        transaction_type: BUY or SELL
        quantity: Order quantity (number of lots × lot_size)
        price: Limit price (0 for MARKET)
        product_type: INTRADAY, MARGIN, CNC, etc. (Default: INTRADAY)
    """
    payload = {
        "security_id": security_id,
        "exchange_segment": exchange_segment,
        "transaction_type": transaction_type,
        "quantity": quantity,
        "price": price,
        "product_type": product_type
    }
    return await call_api("/margincalculator", data=payload)

@mcp.tool()
async def get_option_margin_requirement(
    underlying: str = "NIFTY",
    side: str = "CE",
    quantity: int = 1,
    transaction_type: str = "BUY",
    product_type: str = "INTRADAY",
    spot_index: float = None,
    security_id: str = None,
):
    """
    All-in-one margin check for an option contract.

    Resolves the nearest ITM option for the given underlying + side, then
    queries Dhan's margin calculator — all in a single tool call.

    Args:
        underlying:       Index symbol — NIFTY, BANKNIFTY, or FINNIFTY (default: NIFTY)
        side:             CE (Call) or PE (Put) (default: CE)
        quantity:         Number of lots (default: 1)
        transaction_type: BUY or SELL (default: BUY)
        product_type:     INTRADAY, MARGIN, or CNC (default: INTRADAY)
        spot_index:       Optional current spot price. Omit to let the server
                          fetch it live.
        security_id:      Optional — if you already know the contract's
                          security_id (from get_itm_option) pass it here to
                          skip the resolution step.

    Returns:
        Resolved contract details (symbol, strike, expiry, security_id) plus
        margin fields from Dhan: totalMarginRequired, spanMargin,
        exposureMargin, and available_balance for a go/no-go decision.
    """
    # ── Step 1: resolve security_id if not supplied ──────────────────────────
    if not security_id:
        itm_payload = {"underlying": underlying, "side": side}
        if spot_index is not None:
            itm_payload["spot_index"] = spot_index

        itm = await call_api("/get-itm", itm_payload)
        if itm.get("status") != "success":
            return {
                "status": "error",
                "step": "itm_resolution",
                "message": itm.get("message", "Failed to resolve ITM contract"),
            }

        security_id = itm.get("security_id")
        resolved = {
            "underlying": underlying,
            "side": side,
            "strike": itm.get("strike"),
            "expiry": itm.get("expiry"),
            "symbol": itm.get("symbol"),
            "security_id": security_id,
            "spot_index": itm.get("spot_index"),
        }
    else:
        resolved = {
            "underlying": underlying,
            "side": side,
            "security_id": security_id,
        }

    # ── Step 2: fetch LTP for the option ────────────────────────────────────
    ltp_resp = await call_api("/get-ltp", {"instrument": security_id})
    if ltp_resp.get("status") != "success":
        return {"status": "error", "step": "ltp_fetch", "message": ltp_resp.get("message", "Failed to fetch LTP")}
    premium = ltp_resp.get("ltp", 0)

    # ── Step 3: calculate cost ───────────────────────────────────────────────
    lot_map = {"NIFTY": 65, "BANKNIFTY": 15, "FINNIFTY": 40}
    lot_size = lot_map.get(underlying.upper(), 65)
    total_units = quantity * lot_size
    per_lot_cost = round(premium * lot_size, 2)
    total_required = round(per_lot_cost * quantity, 2)

    # ── Step 4: fetch available balance for a go/no-go decision ─────────────
    funds_resp = await call_api("/fundlimit", method="POST")
    available_balance = None
    if funds_resp.get("status") == "success":
        funds_data = funds_resp.get("data", {})
        available_balance = funds_data.get("availabelBalance") or funds_data.get("availableBalance")

    can_trade = (available_balance is not None) and (available_balance >= total_required)

    return {
        "status": "success",
        "contract": resolved,
        "quantity_lots": quantity,
        "lot_size": lot_size,
        "total_units": total_units,
        "premium": premium,
        "per_lot_cost": per_lot_cost,
        "total_required": total_required,
        "transaction_type": transaction_type,
        "product_type": product_type,
        "funds": {
            "availableBalance": available_balance,
            "can_trade": can_trade,
        },
    }

@mcp.tool()
async def get_performance_history():
    """
    View the most recent historical trades and performance metadata.
    """
    return await call_api("/get-history")

@mcp.tool()
async def get_activity_logs():
    """
    Retrieve recent system activity logs, signals, and ranking engine decisions.
    """
    return await call_api("/activity-logs")

if __name__ == "__main__":
    mcp.run()
