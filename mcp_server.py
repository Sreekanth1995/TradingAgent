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
    
    IMPORTANT: The state object contains a `range_timestamp`. This timestamp points
    to the exact time the price changed direction. You must compare this timestamp with
    your previously cached timestamp. ONLY read the chart again if this timestamp has changed.
    """
    return await call_api("/get-state", {"underlying": underlying})

@mcp.tool()
async def place_manual_order(action: str, underlying: str = "NIFTY", quantity: int = 1, sl_price: float = None, target_price: float = None, sl_index: float = None, target_index: float = None):
    """
    Manually place a trade order (CALL, PUT, EXIT_CALL, EXIT_PUT, EXIT_ALL).
    SL and Target are mandatory for CALL/PUT.
    
    Args:
        action: The trade action (CALL, PUT, EXIT_CALL, EXIT_PUT, EXIT_ALL)
        underlying: The symbol to trade (NIFTY, BANKNIFTY)
        quantity: Order quantity (default: 1 lot)
        sl_price: Optional Premium SL (Legacy)
        target_price: Optional Premium Target (Legacy)
        sl_index: Optional Index SL level
        target_index: Optional Index Target level
    """
    return await call_api("/ui-signal", {
        "action": action, 
        "underlying": underlying, 
        "quantity": quantity,
        "sl_price": sl_price,
        "target_price": target_price,
        "sl_index": sl_index,
        "target_index": target_index
    })

@mcp.tool()
async def set_premium_gtt_levels(underlying: str, side: str, target_price: float, sl_price: float):
    """
    Set or update Premium-based GTT levels (Target/SL) for an active position.
    
    Args:
        underlying: The symbol (NIFTY, BANKNIFTY, FINNIFTY)
        side: Position side (CALL or PUT)
        target_price: [REQUIRED] The premium price level for target exit
        sl_price: [REQUIRED] The premium price level for stop loss exit
    """
    # Note: Using the updated endpoint if available, or fallback to existing
    return await call_api("/conditional-index-order" if False else "/set-conditional-orders", {
        "underlying": underlying,
        "side": side,
        "target_price": target_price,
        "sl_price": sl_price
    })

@mcp.tool()
async def modify_index_gtt_levels(underlying: str, target_level: float, sl_level: float, quantity: int = None):
    """
    Set or update GTT triggers for an active NIFTY/BANKNIFTY position.
    Triggers SELL on Option when Price crosses index level.
    
    Args:
        underlying: Symbol (NIFTY, BANKNIFTY)
        target_level: [REQUIRED] Index level for target exit (e.g., 23550)
        sl_level: [REQUIRED] Index level for stop loss exit (e.g., 23430)
        quantity: Optional lot quantity (defaults to active position size)
    """
    return await call_api("/conditional-index-order", {
        "underlying": underlying,
        "target_level": target_level,
        "sl_level": sl_level,
        "quantity": quantity
    })

@mcp.tool()
async def place_super_order(underlying: str, option: str, target_price: float, sl_price: float, quantity: int = 1):
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
        "target_price": target_price,
        "sl_price": sl_price,
        "quantity": quantity
    })

@mcp.tool()
async def update_super_order(underlying: str, target_price: float, sl_price: float):
    """
    Updates the target and sl legs of an active Premium-based Super Order.
    
    Args:
        underlying: Symbol (NIFTY, BANKNIFTY)
        target_price: [REQUIRED] The new premium price level for target exit
        sl_price: [REQUIRED] The new premium price level for stop loss exit
    """
    return await call_api("/update-super-order", {
        "underlying": underlying,
        "target_price": target_price,
        "sl_price": sl_price
    })

@mcp.tool()
async def cancel_target_stoploss(underlying: str = "NIFTY"):
    """
    Cancel all active GTT conditional orders for a given underlying.
    """
    return await call_api("/cancel-conditional-orders", {"underlying": underlying})

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
