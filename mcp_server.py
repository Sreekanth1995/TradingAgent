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
async def calculate_options_buy_cost(premium: float, lot_size: int = 75, quantity: int = 1) -> dict:
    """
    Calculate the total capital required to BUY an options contract.

    For options buying there is no complex margin — the cost is simply:
        total_cost = premium × lot_size × quantity

    Use this tool INSTEAD of get_margin_requirement when checking whether
    you have enough funds to buy a NIFTY or BANKNIFTY option.

    Args:
        premium:   Current LTP / limit price of the option (e.g. 185.50)
        lot_size:  Lot size for the underlying (NIFTY=75, BANKNIFTY=15). Default: 75
        quantity:  Number of lots to buy (default: 1)

    Returns:
        A dict with `total_cost`, `per_lot_cost`, `lot_size`, and `quantity`.
    """
    per_lot = round(premium * lot_size, 2)
    total = round(per_lot * quantity, 2)
    return {
        "status": "ok",
        "premium": premium,
        "lot_size": lot_size,
        "quantity": quantity,
        "per_lot_cost": per_lot,
        "total_cost": total,
        "note": "Options buying cost = premium × lot_size × quantity. No broker margin API needed."
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
