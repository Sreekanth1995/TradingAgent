"""FlatTrade Order Execution Service.

Handles order operations for FlatTrade via NorenRestApi OMS:
- Intraday MIS ('I') market entry orders
- Stop loss order placement and arming
- Modifying open SL order to Market on reversal/exit
- Position checks, margins, and emergency kill switch
"""

import os
import uuid
import logging
from typing import Optional, Dict, Any, List

logger = logging.getLogger("broker.flattrade.order")


class FlatTradeOrderService:
    def __init__(
        self,
        auth_service=None,
        instrument_service=None,
        dry_run: bool = False,
    ):
        self.auth_service = auth_service
        self.instrument_service = instrument_service
        self.dry_run = dry_run or (os.getenv("DRY_RUN", "false").lower() == "true")
        self._api = None

    def _get_api(self):
        """Lazy load authenticated NorenApi instance."""
        if self._api:
            return self._api
        token = self.auth_service.token if self.auth_service else None
        if not token or self.dry_run:
            return None
        from NorenRestApiPy.NorenApi import NorenApi
        self._api = NorenApi(
            host="https://piconnect.flattrade.in/PiConnectTP/",
            websocket="wss://piconnect.flattrade.in/PiConnectWSTP/"
        )
        self._api.set_token(token)
        return self._api

    def place_order(self, symbol: str, leg_data: Dict[str, Any]) -> Dict[str, Any]:
        """Place an Intraday order on FlatTrade."""
        if self.dry_run:
            sim_id = f"FT_{uuid.uuid4().hex[:10].upper()}"
            logger.info(f"FlatTradeOrderService [DRY_RUN]: place_order for {symbol}: {leg_data}")
            return {
                "status": "success",
                "order_id": sim_id,
                "noren_order_id": sim_id,
                "order_status": "COMPLETE",
                "symbol": symbol,
                "dry_run": True,
            }

        api = self._get_api()
        if not api:
            return {"status": "error", "message": "FlatTrade client not authenticated"}

        try:
            tx_type = leg_data.get("transactionType", "BUY").upper()
            buy_or_sell = "B" if tx_type in ("BUY", "B", "LONG") else "S"
            order_type = leg_data.get("orderType", "MARKET").upper()
            price_type = "MKT" if order_type == "MARKET" else "LMT"
            price = float(leg_data.get("price", 0.0))
            trigger_price = float(leg_data.get("trigger_price", 0.0)) if leg_data.get("trigger_price") else None
            quantity = int(leg_data.get("quantity", 1))
            remarks = str(leg_data.get("remarks") or f"algo_{uuid.uuid4().hex[:6]}")

            resp = api.place_order(
                buy_or_sell=buy_or_sell,
                product_type="I",
                exchange="NFO",
                tradingsymbol=symbol,
                quantity=quantity,
                discloseqty=0,
                price_type=price_type,
                price=price if price_type == "LMT" else 0.0,
                trigger_price=trigger_price,
                retention="DAY",
                remarks=remarks,
            )

            if isinstance(resp, dict) and resp.get("stat") == "Ok":
                order_id = resp.get("norenordno", remarks)
                return {
                    "status": "success",
                    "order_id": order_id,
                    "noren_order_id": order_id,
                    "order_status": "OPEN",
                    "raw": resp,
                }
            else:
                err_msg = resp.get("emsg", "Failed to place FlatTrade order") if isinstance(resp, dict) else str(resp)
                return {"status": "error", "message": err_msg}
        except Exception as e:
            logger.error(f"FlatTradeOrderService place_order error: {e}")
            return {"status": "error", "message": str(e)}

    def place_super_order(self, symbol: str, leg_data: Dict[str, Any]) -> Dict[str, Any]:
        """Places MARKET entry on FlatTrade and immediately arms Stop-Loss order."""
        if self.dry_run:
            sim_entry = f"FT_ENTRY_{uuid.uuid4().hex[:8].upper()}"
            sim_sl = f"FT_SL_{uuid.uuid4().hex[:8].upper()}"
            logger.info(f"FlatTradeOrderService [DRY_RUN]: place_super_order for {symbol}")
            return {
                "status": "success",
                "order_id": sim_entry,
                "noren_order_id": sim_entry,
                "sl_order_id": sim_sl,
                "order_status": "COMPLETE",
                "dry_run": True,
            }

        # 1. Place immediate MARKET entry order
        entry_res = self.place_order(symbol, leg_data)
        if entry_res.get("status") != "success":
            return entry_res

        entry_id = entry_res.get("order_id")
        quantity = int(leg_data.get("quantity", 1))
        sl_price = float(leg_data.get("stop_loss_price", 0.0))

        # 2. Arm Stop-Loss order if sl_price specified
        sl_order_id = None
        if sl_price > 0:
            api = self._get_api()
            if api:
                try:
                    tx_type = leg_data.get("transactionType", "BUY").upper()
                    sl_side = "S" if tx_type in ("BUY", "B", "LONG") else "B"
                    sl_resp = api.place_order(
                        buy_or_sell=sl_side,
                        product_type="I",
                        exchange="NFO",
                        tradingsymbol=symbol,
                        quantity=quantity,
                        discloseqty=0,
                        price_type="SL-LMT",
                        price=round(sl_price - 0.5, 2) if sl_side == "S" else round(sl_price + 0.5, 2),
                        trigger_price=sl_price,
                        retention="DAY",
                        remarks=f"sl_{entry_id}",
                    )
                    if isinstance(sl_resp, dict) and sl_resp.get("stat") == "Ok":
                        sl_order_id = sl_resp.get("norenordno")
                        logger.info(f"FlatTradeOrderService: Armed SL {sl_order_id} for entry {entry_id}")
                except Exception as e:
                    logger.warning(f"FlatTradeOrderService: Failed to arm SL order ({e})")

        return {
            "status": "success",
            "order_id": entry_id,
            "noren_order_id": entry_id,
            "sl_order_id": sl_order_id,
            "order_status": "SUCCESS",
        }

    def modify_order(self, order_id: str, order_type: str, leg_data: Dict[str, Any]) -> Dict[str, Any]:
        """Modify an active FlatTrade order or change SL order to MARKET."""
        if self.dry_run:
            logger.info(f"FlatTradeOrderService [DRY_RUN]: modify_order {order_id}: {leg_data}")
            return {"status": "success", "order_id": order_id, "dry_run": True}

        api = self._get_api()
        if not api:
            return {"status": "error", "message": "FlatTrade client not authenticated"}

        try:
            symbol = leg_data.get("symbol", "")
            new_qty = leg_data.get("quantity")
            new_price = leg_data.get("price", 0.0)
            new_prctyp = leg_data.get("price_type", "MKT" if order_type.upper() == "MARKET" else "LMT")

            resp = api.modify_order(
                exchange="NFO",
                tradingsymbol=symbol,
                orderno=order_id,
                newquantity=new_qty,
                newprice_type=new_prctyp,
                newprice=new_price,
            )
            return {"status": "success", "order_id": order_id, "raw": resp}
        except Exception as e:
            logger.error(f"FlatTradeOrderService modify_order error: {e}")
            return {"status": "error", "message": str(e)}

    def cancel_order(self, order_id: str) -> Dict[str, Any]:
        """Cancel an open FlatTrade order."""
        if self.dry_run:
            logger.info(f"FlatTradeOrderService [DRY_RUN]: cancel_order {order_id}")
            return {"status": "success", "order_id": order_id, "dry_run": True}

        api = self._get_api()
        if not api:
            return {"status": "error", "message": "FlatTrade client not authenticated"}

        try:
            resp = api.cancel_order(orderno=order_id)
            return {"status": "success", "order_id": order_id, "raw": resp}
        except Exception as e:
            logger.error(f"FlatTradeOrderService cancel_order error: {e}")
            return {"status": "error", "message": str(e)}

    def get_positions(self) -> List[Dict[str, Any]]:
        """Fetch open FlatTrade positions and normalize format."""
        if self.dry_run:
            return []

        api = self._get_api()
        if not api:
            return []

        try:
            res = api.get_positions()
            normalized = []
            if isinstance(res, list):
                for p in res:
                    net_qty = int(p.get("netqty", 0))
                    normalized.append({
                        "broker": "flattrade",
                        "tradingSymbol": p.get("tsym", ""),
                        "netQty": net_qty,
                        "costPrice": float(p.get("netavgprc", 0.0)),
                        "realizedProfit": float(p.get("rpnl", 0.0)),
                        "unrealizedProfit": float(p.get("urmtom", 0.0)),
                        "product": p.get("prd", "I"),
                    })
            return normalized
        except Exception as e:
            logger.error(f"FlatTradeOrderService get_positions error: {e}")
            return []

    def get_limits(self) -> Dict[str, Any]:
        """Fetch available margin limits from FlatTrade."""
        if self.dry_run:
            return {"available_margin": 1000000.0, "used_margin": 0.0, "broker": "flattrade"}

        api = self._get_api()
        if not api:
            return {"available_margin": 0.0, "used_margin": 0.0, "broker": "flattrade"}

        try:
            res = api.get_limits()
            avail = float(res.get("cash", 0.0)) if isinstance(res, dict) else 0.0
            used = float(res.get("marginused", 0.0)) if isinstance(res, dict) else 0.0
            return {
                "broker": "flattrade",
                "available_margin": avail,
                "used_margin": used,
                "raw": res,
            }
        except Exception as e:
            logger.error(f"FlatTradeOrderService get_limits error: {e}")
            return {"available_margin": 0.0, "used_margin": 0.0, "broker": "flattrade", "error": str(e)}

    def kill_switch(self) -> Dict[str, Any]:
        """Emergency kill switch: flatten all open positions and cancel orders."""
        logger.warning("FlatTradeOrderService: EMERGENCY KILL SWITCH TRIGGERED")
        positions = self.get_positions()
        flatten_results = []
        for p in positions:
            qty = p.get("netQty", 0)
            sym = p.get("tradingSymbol", "")
            if qty != 0 and sym:
                side = "SELL" if qty > 0 else "BUY"
                res = self.place_order(sym, {
                    "transactionType": side,
                    "orderType": "MARKET",
                    "quantity": abs(qty),
                })
                flatten_results.append({"symbol": sym, "side": side, "qty": qty, "result": res})
        return {"status": "success", "broker": "flattrade", "flattened": flatten_results}
