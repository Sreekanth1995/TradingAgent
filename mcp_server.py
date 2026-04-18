import os
import httpx
from mcp.server.fastmcp import FastMCP
from dotenv import load_dotenv

load_dotenv()

mcp = FastMCP("TradingAgent_AI_Bridge")

SECRET = os.getenv("WEBHOOK_SECRET")
BASE_URL = os.getenv("TRADING_AGENT_URL", "http://65.20.83.74")


async def _call(endpoint: str, data: dict = None, method: str = "POST"):
    """HTTP helper — injects secret and calls the Flask server."""
    payload = dict(data or {})
    payload["secret"] = SECRET
    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            if method == "POST":
                resp = await client.post(f"{BASE_URL}{endpoint}", json=payload)
            else:
                resp = await client.get(f"{BASE_URL}{endpoint}", params=payload)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            return {"status": "error", "message": str(e)}


# ─────────────────────────────────────────────────────────────────────────────
# SUPER ORDER TOOLS  (Premium-based Native Bracket Orders)
# ─────────────────────────────────────────────────────────────────────────────

@mcp.tool()
async def place_super_order(
    underlying: str,
    side: str,
    target_price: float,
    sl_price: float,
    quantity: int = 1,
    option: str = None,
):
    """
    Place a Premium-based Native Super Order (bracket order).
    The broker manages the SL and Target legs natively.

    Args:
        underlying:   Index — NIFTY, BANKNIFTY, or FINNIFTY.
        side:         CALL (bullish) or PUT (bearish).
        target_price: Premium target price (e.g. 240.0).
        sl_price:     Premium stop-loss price (e.g. 140.0).
        quantity:     Number of lots (default 1).
        option:       Optional exact option symbol to trade (e.g. NIFTY24APR22500CE).
                      If omitted the server resolves the nearest ITM automatically.
    """
    return await _call("/super-order", {
        "underlying": underlying,
        "side": side,
        "target_price": target_price,
        "sl_price": sl_price,
        "quantity": quantity,
        "option": option,
    })


@mcp.tool()
async def modify_super_order(
    underlying: str,
    target_price: float = None,
    sl_price: float = None,
):
    """
    Modify the Target and/or SL legs of an active Super Order.
    At least one of target_price or sl_price must be provided.

    Args:
        underlying:   Index of the active position — NIFTY, BANKNIFTY, or FINNIFTY.
        target_price: New premium target price (e.g. 280.0).
        sl_price:     New premium stop-loss price (e.g. 160.0).
    """
    if not target_price and not sl_price:
        return {"status": "error", "message": "Provide at least one of target_price or sl_price"}
    return await _call("/update-super-order", {
        "underlying": underlying,
        "target_price": target_price,
        "sl_price": sl_price,
    })


@mcp.tool()
async def cancel_super_order(underlying: str):
    """
    Cancel the pending (not yet filled) entry leg of a Super Order.
    Use this when the entry order is still in TRANSIT/PENDING state.
    For an already-filled position use exit_super_order instead.

    Args:
        underlying: Index of the pending order — NIFTY, BANKNIFTY, or FINNIFTY.
    """
    return await _call("/cancel-super-order", {"underlying": underlying})


@mcp.tool()
async def exit_super_order(underlying: str):
    """
    Exit (square off) an active Super Order position at market price.
    Places an opposite MARKET order and cancels all remaining bracket legs.

    Args:
        underlying: Index of the active position — NIFTY, BANKNIFTY, or FINNIFTY.
    """
    return await _call("/exit-super-order", {"underlying": underlying})


# ─────────────────────────────────────────────────────────────────────────────
# CONDITIONAL ORDER TOOLS  (Index-level GTT / Polling-based Orders)
# ─────────────────────────────────────────────────────────────────────────────

@mcp.tool()
async def place_conditional_order(
    action: str,
    underlying: str = "NIFTY",
    quantity: int = 1,
    sl_index: float = None,
    target_index: float = None,
    spot_index: float = None,
):
    """
    Place a Conditional (GTT / index-level protected) order.

    Actions:
        CALL      — Buy a Call option. sl_index and target_index are REQUIRED.
        PUT       — Buy a Put option. sl_index and target_index are REQUIRED.
        EXIT_CALL — Close an active CALL position.
        EXIT_PUT  — Close an active PUT position.

    The SL and Target are expressed as INDEX price levels (not option premium).
    A polling monitor exits the trade when the index crosses those levels.

    Args:
        action:       CALL | PUT | EXIT_CALL | EXIT_PUT
        underlying:   NIFTY, BANKNIFTY, or FINNIFTY (default NIFTY).
        quantity:     Number of lots (default 1).
        sl_index:     Index SL level. For CALL must be < spot; for PUT must be > spot.
        target_index: Index target level.
        spot_index:   Optional current index spot. Omit to fetch live.
    """
    return await _call("/conditional-order", {
        "action": action,
        "underlying": underlying,
        "quantity": quantity,
        "sl_index": sl_index,
        "target_index": target_index,
        "spot_index": spot_index,
    })


@mcp.tool()
async def modify_conditional_order(
    underlying: str,
    target_level: float,
    sl_level: float,
    quantity: int = None,
):
    """
    Update the Index SL and Target levels for an active Conditional position.
    Replaces any existing GTT triggers with the new levels.

    Args:
        underlying:   Index of the active position — NIFTY, BANKNIFTY, or FINNIFTY.
        target_level: New index target level (e.g. 23550.0).
        sl_level:     New index stop-loss level (e.g. 23400.0).
        quantity:     Optional lot quantity override (defaults to active position size).
    """
    return await _call("/conditional-index-order", {
        "underlying": underlying,
        "target_level": target_level,
        "sl_level": sl_level,
        "quantity": quantity,
    })


@mcp.tool()
async def cancel_conditional_order(underlying: str):
    """
    Cancel the active GTT conditional orders (SL + Target alerts) for a position.
    Does NOT close the option position itself — use exit_conditional_order for that.

    Args:
        underlying: Index — NIFTY, BANKNIFTY, or FINNIFTY.
    """
    return await _call("/cancel-conditional-orders", {"underlying": underlying})


@mcp.tool()
async def exit_conditional_order(underlying: str):
    """
    Exit (square off) an active Conditional Order position at market price.
    Also cancels any live GTT triggers attached to it.

    Args:
        underlying: Index of the active position — NIFTY, BANKNIFTY, or FINNIFTY.
    """
    return await _call("/exit-conditional-order", {"underlying": underlying})


# ─────────────────────────────────────────────────────────────────────────────
# BROKER STATE — Positions & Orders
# ─────────────────────────────────────────────────────────────────────────────

@mcp.tool()
async def get_positions():
    """
    Fetch all current open positions directly from Dhan.
    Each position includes: tradingSymbol, securityId, exchangeSegment,
    productType, netQty, buyAvg, sellAvg, unrealizedProfit, realizedProfit.
    netQty > 0 = net long; netQty < 0 = net short; 0 = flat.
    """
    return await _call("/positions")


@mcp.tool()
async def get_orders():
    """
    Fetch the full order book from Dhan.
    Each order includes: orderId, tradingSymbol, orderStatus, transactionType,
    quantity, price, averageTradedPrice, orderType, productType, updateTime.

    Possible orderStatus values:
        TRANSIT, PENDING, PART_TRADED — still open / cancellable
        TRADED                        — fully filled
        CANCELLED, REJECTED, EXPIRED  — terminal states
    """
    return await _call("/orders")


# ─────────────────────────────────────────────────────────────────────────────
# CONTEXT & LOGS
# ─────────────────────────────────────────────────────────────────────────────

@mcp.tool()
async def get_activity_logs():
    """Retrieve recent system activity: signals received, orders placed, exits triggered."""
    return await _call("/activity-logs")


@mcp.tool()
async def get_last_signal():
    """
    Retrieve the most recent enriched TradingView signal.
    Use after an SSE notification to get the full payload if you don't have it.
    """
    return await _call("/last-signal", method="GET")


@mcp.tool()
async def get_performance_history():
    """View the last 50 completed trades and performance metadata."""
    return await _call("/get-history")


if __name__ == "__main__":
    mcp.run()
