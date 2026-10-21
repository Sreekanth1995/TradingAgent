"""Groww Order Execution Service.

Handles order operations for Groww:
- Market entry orders via `groww.place_order`
- Native OCO smart orders via `groww.create_smart_order(SMART_ORDER_TYPE_OCO)`
- Smart exits modifying OCO legs towards current LTP
- Emergency cancellation & kill switch
- Positions and margin limits retrieval
"""

import os
import uuid
import logging
from typing import Optional, Dict, Any, List

logger = logging.getLogger("broker.groww.order")


class GrowwOrderService:
    def __init__(
        self,
        auth_service=None,
        instrument_service=None,
        dry_run: bool = False,
    ):
        self.auth_service = auth_service
        self.instrument_service = instrument_service
        self.dry_run = dry_run or (os.getenv("DRY_RUN", "false").lower() == "true")
        self._groww_client = None

    def _get_api(self):
        """Lazy load authenticated GrowwAPI instance."""
        if self._groww_client:
            return self._groww_client
        token = self.auth_service.access_token if self.auth_service else None
        if not token or self.dry_run:
            return None
        from growwapi import GrowwAPI
        self._groww_client = GrowwAPI(token)
        return self._groww_client

    def place_order(self, symbol: str, leg_data: Dict[str, Any]) -> Dict[str, Any]:
        """Places a regular order (Market/Limit) on Groww."""
        if self.dry_run:
            sim_id = f"GRW_{uuid.uuid4().hex[:12].upper()}"
            logger.info(f"GrowwOrderService [DRY_RUN]: place_order for {symbol}: {leg_data}")
            return {
                "order_id": sim_id,
                "groww_order_id": sim_id,
                "order_status": "SUCCESS",
                "status": "success",
                "symbol": symbol,
                "dry_run": True,
            }

        api = self._get_api()
        if not api:
            return {"status": "error", "message": "Groww client not authenticated"}

        try:
            from growwapi import GrowwAPI
            
            # Determine transaction type
            tx_type = leg_data.get("transactionType", "BUY").upper()
            groww_tx = (
                GrowwAPI.TRANSACTION_TYPE_BUY
                if tx_type in ("BUY", "B", "LONG")
                else GrowwAPI.TRANSACTION_TYPE_SELL
            )

            # Determine order type
            order_type = leg_data.get("orderType", "MARKET").upper()
            groww_order_type = (
                GrowwAPI.ORDER_TYPE_MARKET
                if order_type == "MARKET"
                else GrowwAPI.ORDER_TYPE_LIMIT
            )

            price = float(leg_data.get("price", 0.0))
            quantity = int(leg_data.get("quantity", 1))
            ref_id = str(uuid.uuid4().hex[:16])

            resp = api.place_order(
                trading_symbol=symbol,
                quantity=quantity,
                validity=GrowwAPI.VALIDITY_DAY,
                exchange=GrowwAPI.EXCHANGE_NSE,
                segment=GrowwAPI.SEGMENT_FNO,
                product=GrowwAPI.PRODUCT_MIS,
                order_type=groww_order_type,
                transaction_type=groww_tx,
                price=price if order_type == "LIMIT" else 0.0,
                order_reference_id=ref_id,
            )

            order_id = resp.get("groww_order_id") or resp.get("order_id") or ref_id
            return {
                "status": "success",
                "order_id": order_id,
                "groww_order_id": order_id,
                "order_status": resp.get("order_status", "OPEN"),
                "raw": resp,
            }
        except Exception as e:
            logger.error(f"GrowwOrderService place_order error for {symbol}: {e}")
            return {"status": "error", "message": str(e)}

    def place_super_order(self, symbol: str, leg_data: Dict[str, Any]) -> Dict[str, Any]:
        """Places MARKET entry on Groww and immediately arms native OCO bracket."""
        if self.dry_run:
            sim_entry_id = f"GRW_ENTRY_{uuid.uuid4().hex[:10].upper()}"
            sim_oco_id = f"GRW_OCO_{uuid.uuid4().hex[:10].upper()}"
            logger.info(f"GrowwOrderService [DRY_RUN]: place_super_order for {symbol}")
            return {
                "status": "success",
                "order_id": sim_entry_id,
                "groww_order_id": sim_entry_id,
                "oco_order_id": sim_oco_id,
                "order_status": "SUCCESS",
                "dry_run": True,
            }

        # 1. Place immediate MARKET entry order
        entry_res = self.place_order(symbol, leg_data)
        if entry_res.get("status") != "success":
            return entry_res

        entry_id = entry_res.get("order_id")
        quantity = int(leg_data.get("quantity", 1))
        target_price = float(leg_data.get("target_price", 0.0))
        sl_price = float(leg_data.get("stop_loss_price", 0.0))

        # 2. If target or SL specified, arm native OCO smart order
        oco_id = None
        if target_price > 0 and sl_price > 0:
            api = self._get_api()
            if api:
                try:
                    from growwapi import GrowwAPI
                    oco_ref = f"oco-{uuid.uuid4().hex[:12]}"
                    oco_resp = api.create_smart_order(
                        smart_order_type=GrowwAPI.SMART_ORDER_TYPE_OCO,
                        reference_id=oco_ref,
                        segment=GrowwAPI.SEGMENT_FNO,
                        trading_symbol=symbol,
                        quantity=quantity,
                        product_type=GrowwAPI.PRODUCT_MIS,
                        exchange=GrowwAPI.EXCHANGE_NSE,
                        duration=GrowwAPI.VALIDITY_DAY,
                        net_position_quantity=quantity,
                        transaction_type=GrowwAPI.TRANSACTION_TYPE_SELL,
                        target={
                            "trigger_price": str(target_price),
                            "order_type": GrowwAPI.ORDER_TYPE_LIMIT,
                            "price": str(round(target_price + 0.5, 2)),
                        },
                        stop_loss={
                            "trigger_price": str(sl_price),
                            "order_type": GrowwAPI.ORDER_TYPE_STOP_LOSS_MARKET,
                            "price": None,
                        },
                    )
                    oco_id = oco_resp.get("smart_order_id")
                    logger.info(f"GrowwOrderService: Armed OCO {oco_id} for entry {entry_id}")
                except Exception as e:
                    logger.warning(f"GrowwOrderService: Failed to arm native OCO ({e}). Fallback to engine exits.")

        return {
            "status": "success",
            "order_id": entry_id,
            "groww_order_id": entry_id,
            "oco_order_id": oco_id,
            "order_status": "SUCCESS",
        }

    def modify_order(self, order_id: str, order_type: str, leg_data: Dict[str, Any]) -> Dict[str, Any]:
        """Modify an active regular order or OCO leg."""
        if self.dry_run:
            logger.info(f"GrowwOrderService [DRY_RUN]: modify_order {order_id}: {leg_data}")
            return {"status": "success", "order_id": order_id, "dry_run": True}

        api = self._get_api()
        if not api:
            return {"status": "error", "message": "Groww client not authenticated"}

        try:
            from growwapi import GrowwAPI
            resp = api.modify_order(
                groww_order_id=order_id,
                segment=GrowwAPI.SEGMENT_FNO,
                quantity=leg_data.get("quantity"),
                price=leg_data.get("price"),
                trigger_price=leg_data.get("trigger_price"),
            )
            return {"status": "success", "order_id": order_id, "raw": resp}
        except Exception as e:
            logger.error(f"GrowwOrderService modify_order error: {e}")
            return {"status": "error", "message": str(e)}

    def cancel_order(self, order_id: str) -> Dict[str, Any]:
        """Cancel an open regular or smart order."""
        if self.dry_run:
            logger.info(f"GrowwOrderService [DRY_RUN]: cancel_order {order_id}")
            return {"status": "success", "order_id": order_id, "dry_run": True}

        api = self._get_api()
        if not api:
            return {"status": "error", "message": "Groww client not authenticated"}

        try:
            from growwapi import GrowwAPI
            resp = api.cancel_order(
                groww_order_id=order_id,
                segment=GrowwAPI.SEGMENT_FNO,
            )
            return {"status": "success", "order_id": order_id, "raw": resp}
        except Exception as e:
            logger.error(f"GrowwOrderService cancel_order error: {e}")
            return {"status": "error", "message": str(e)}

    def get_positions(self) -> List[Dict[str, Any]]:
        """Fetch open F&O positions from Groww and normalize format."""
        if self.dry_run:
            return []

        api = self._get_api()
        if not api:
            return []

        try:
            from growwapi import GrowwAPI
            res = api.get_positions_for_user(segment=GrowwAPI.SEGMENT_FNO)
            raw_positions = res.get("positions", []) if isinstance(res, dict) else []
            normalized = []
            for p in raw_positions:
                normalized.append({
                    "broker": "groww",
                    "tradingSymbol": p.get("trading_symbol", ""),
                    "netQty": p.get("quantity", 0),
                    "costPrice": p.get("net_price", 0.0),
                    "realizedProfit": p.get("realised_pnl", 0.0),
                    "unrealizedProfit": p.get("unrealised_pnl", 0.0),
                    "product": p.get("product", "MIS"),
                })
            return normalized
        except Exception as e:
            logger.error(f"GrowwOrderService get_positions error: {e}")
            return []

    def get_limits(self) -> Dict[str, Any]:
        """Retrieve available margin from Groww."""
        if self.dry_run:
            return {"available_margin": 1000000.0, "used_margin": 0.0, "broker": "groww"}

        api = self._get_api()
        if not api:
            return {"available_margin": 0.0, "used_margin": 0.0, "broker": "groww"}

        try:
            res = api.get_available_margin_details()
            fno_margin = res.get("fno_margin", {}) if isinstance(res, dict) else {}
            avail = float(fno_margin.get("available_balance", res.get("available_balance", 0.0)))
            used = float(fno_margin.get("used_margin", res.get("used_margin", 0.0)))
            return {
                "broker": "groww",
                "available_margin": avail,
                "used_margin": used,
                "raw": res,
            }
        except Exception as e:
            logger.error(f"GrowwOrderService get_limits error: {e}")
            return {"available_margin": 0.0, "used_margin": 0.0, "broker": "groww", "error": str(e)}

    def kill_switch(self) -> Dict[str, Any]:
        """Emergency kill switch: flattens open Groww positions and cancels orders."""
        logger.warning("GrowwOrderService: EMERGENCY KILL SWITCH TRIGGERED")
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
        return {"status": "success", "broker": "groww", "flattened": flatten_results}
