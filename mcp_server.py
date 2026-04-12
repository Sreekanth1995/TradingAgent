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
    """
    return await call_api("/get-state", {"underlying": underlying})

@mcp.tool()
async def place_manual_order(action: str, underlying: str = "NIFTY", quantity: int = 1):
    """
    Manually place a trade order (CALL, PUT, EXIT_CALL, EXIT_PUT, EXIT_ALL).
    
    Args:
        action: The trade action (CALL, PUT, EXIT_CALL, EXIT_PUT, EXIT_ALL)
        underlying: The symbol to trade (default: NIFTY)
        quantity: Order quantity (default: 1 lot)
    """
    return await call_api("/ui-signal", {
        "action": action, 
        "underlying": underlying, 
        "quantity": quantity
    })

@mcp.tool()
async def update_price_levels(levels: dict):
    """
    Update the technical levels (e.g. TP0, TP1, resistance) for indicators.
    Expected format: {"NIFTY": {"tp0_low": 24000, "tp0_high": 24100}, ...}
    """
    return await call_api("/set-levels", {
        "levels": levels
    })

@mcp.tool()
async def set_target_stoploss(underlying: str, side: str, target_price: float, sl_price: float):
    """
    Set GTT (Good Till Triggered) conditional orders for Target and Stop Loss 
    on an active position.
    
    Args:
        underlying: The symbol (NIFTY, BANKNIFTY, FINNIFTY)
        side: Position side (CALL or PUT)
        target_price: The price level for target exit
        sl_price: The price level for stop loss exit
    """
    return await call_api("/set-conditional-orders", {
        "underlying": underlying,
        "side": side,
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
