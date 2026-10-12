"""Dhan Order Execution Service (Standard and Super/Bracket Orders)."""

import time
import uuid
import logging
import requests
from typing import Dict, Any, List, Optional
from broker.common import ExchangeSegment, TransactionType, OrderType, ProductType, Validity

logger = logging.getLogger("broker.order")


class DhanOrderService:
    def __init__(self, auth_service, instrument_service=None, market_data_service=None):
        self.auth = auth_service
        self.instrument = instrument_service
        self.market_data = market_data_service

    def _round_to_tick(self, price: float, tick: float = 0.05) -> float:
        if self.market_data:
            return self.market_data.round_to_tick(price, tick)
        if not price:
            return 0.0
        return round(round(float(price) / tick) * tick, 2)

    def place_buy_order(self, symbol: str, leg_data: Dict[str, Any]) -> Dict[str, Any]:
        return self._place_order(symbol, leg_data, TransactionType.BUY)

    def place_sell_order(self, symbol: str, leg_data: Dict[str, Any]) -> Dict[str, Any]:
        return self._place_order(symbol, leg_data, TransactionType.SELL)

    def place_order(self, symbol: str, leg_data: Dict[str, Any]) -> Dict[str, Any]:
        txn_type = leg_data.get('transaction_type', TransactionType.BUY)
        return self._place_order(symbol, leg_data, txn_type)

    def _place_order(self, symbol: str, leg_data: Dict[str, Any], transaction_type: str) -> Dict[str, Any]:
        if self.instrument and not self.instrument.scrip_loaded:
            logger.warning("Scrip Master still loading, waiting...")
            max_wait = 30
            waited = 0
            while not self.instrument.scrip_loaded and waited < max_wait:
                time.sleep(1)
                waited += 1

            if not self.instrument.scrip_loaded:
                logger.error("Scrip Master failed to load in time")
                return {"success": False, "order_id": None, "error": "Scrip Master not ready"}

        try:
            sec_id = leg_data.get('security_id')
            if not sec_id and self.instrument:
                base_symbol = leg_data.get('symbol', symbol)
                strike = leg_data.get('strike_price')
                opt_type = leg_data.get('option_type')
                expiry = leg_data.get('expiry_date')
                sec_id = self.instrument.get_security_id(base_symbol, strike, opt_type, expiry)

            lots = int(leg_data.get('quantity', 1))
            lot_size = 1
            if self.instrument and hasattr(self.instrument, 'lot_map'):
                lot_size = self.instrument.lot_map.get(sec_id, 1)
            final_qty = lots * lot_size

            logger.info(f"$$$ [BROKER] PLACING {transaction_type} ORDER: {lots} Lots ({final_qty} units) x {symbol} (ID: {sec_id}, LotSize: {lot_size}) $$$")

            if self.auth.dhan and not self.auth.dry_run:
                order_type = leg_data.get('order_type', OrderType.MARKET)
                price = leg_data.get('price', 0.0)
                trigger_price = leg_data.get('trigger_price', 0.0)

                if order_type == "LIMIT": order_type = OrderType.LIMIT
                if order_type in ("STOP_LOSS", "SL"): order_type = OrderType.STOP_LOSS
                if order_type == "SL-M": order_type = OrderType.STOP_LOSS_MARKET

                logger.info(f"Placing Order: Type={order_type}, Price={price}, Trigger={trigger_price}")

                resp = self.auth.dhan.place_order(
                    security_id=sec_id,
                    exchange_segment=ExchangeSegment.NSE_FNO,
                    transaction_type=transaction_type,
                    quantity=final_qty,
                    order_type=order_type,
                    product_type=ProductType.INTRADAY,
                    price=price,
                    trigger_price=trigger_price,
                    validity=Validity.DAY
                )

                if resp.get('status') == 'success':
                    return {"success": True, "order_id": resp.get('data', {}).get('orderId'), "error": None}
                elif resp.get('errorCode') == 'DH-901' or 'Unauthorized' in str(resp):
                    logger.warning("Order Placement: 401 Unauthorized detected. Syncing token...")
                    if self.auth.sync_token_from_redis():
                        resp = self.auth.dhan.place_order(
                            security_id=sec_id,
                            exchange_segment=ExchangeSegment.NSE_FNO,
                            transaction_type=transaction_type,
                            quantity=final_qty,
                            order_type=order_type,
                            product_type=ProductType.INTRADAY,
                            price=price,
                            trigger_price=trigger_price,
                            validity=Validity.DAY
                        )
                        if resp.get('status') == 'success':
                            return {"success": True, "order_id": resp.get('data', {}).get('orderId'), "error": None}

                    return {"success": False, "order_id": None, "error": resp.get('remarks', 'Authentication Failed')}
                else:
                    err = resp.get('remarks') or resp.get('errorCode') or str(resp)
                    logger.error(f"Order Placement failed: {err} | full response: {resp}")
                    return {"success": False, "order_id": None, "error": err}
            else:
                return {"success": True, "order_id": "mock_id_999", "error": None}

        except Exception as e:
            logger.error(f"Order Placement FAILED: {e}")
            return {"success": False, "order_id": None, "error": str(e)}

    def cancel_order(self, order_id: str) -> Dict[str, Any]:
        """Cancels a pending order."""
        if self.auth.dry_run:
            logger.info(f"$$$ [BROKER] MOCK CANCEL Order {order_id} $$$")
            return {"success": True, "message": "Mock Cancel Success"}

        if self.auth.dhan:
            try:
                resp = self.auth.dhan.cancel_order(order_id)
                if resp.get('status') == 'success':
                    logger.info(f"Order {order_id} cancelled successfully.")
                    return {"success": True}
                else:
                    logger.error(f"Failed to cancel order {order_id}: {resp}")
                    return {"success": False, "error": resp.get('remarks')}
            except Exception as e:
                logger.error(f"Exception cancelling order {order_id}: {e}")
                return {"success": False, "error": str(e)}
        return {"success": False, "error": "Broker not initialized"}

    def get_positions(self) -> List[Dict[str, Any]]:
        """Fetches current positions from Dhan."""
        if self.auth.dry_run:
            return []

        if self.auth.dhan:
            try:
                resp = self.auth.dhan.get_positions()
                if resp.get('status') == 'success':
                    return resp.get('data', [])
                elif resp.get('errorCode') == 'DH-901' or 'Unauthorized' in str(resp):
                    logger.warning("Get Positions: 401 Unauthorized. Syncing token...")
                    if self.auth.sync_token_from_redis():
                        return self.auth.dhan.get_positions()
                else:
                    logger.error(f"Failed to fetch positions: {resp}")
                    return []
            except Exception as e:
                logger.error(f"Exception fetching positions: {e}")
                return []
        return []

    def get_all_orders(self) -> List[Dict[str, Any]]:
        """Fetches the full order book from Dhan."""
        if self.auth.dry_run or not self.auth.dhan:
            return []
        try:
            resp = self.auth.dhan.get_order_list()
            if resp.get('status') == 'success':
                return resp.get('data', [])
            if resp.get('errorCode') == 'DH-901' or 'Unauthorized' in str(resp):
                logger.warning("Get Orders: 401 Unauthorized. Syncing token...")
                if self.auth.sync_token_from_redis():
                    resp = self.auth.dhan.get_order_list()
                    return resp.get('data', []) if resp.get('status') == 'success' else []
            logger.error(f"Failed to fetch order list: {resp}")
            return []
        except Exception as e:
            logger.error(f"Exception fetching order list: {e}")
            return []

    def get_order_status(self, order_id: str) -> Optional[Dict[str, Any]]:
        """Retrieves order status and details."""
        if self.auth.dry_run:
            return {"orderStatus": "TRADED", "averagePrice": 100.0}

        if self.auth.dhan:
            try:
                resp = self.auth.dhan.get_order_by_id(order_id)
                if isinstance(resp, list):
                    logger.warning(f"Dhan API returned LIST for order {order_id}: {resp}")
                    if len(resp) > 0 and isinstance(resp[0], dict):
                        return resp[0]
                    return None

                if isinstance(resp, dict) and resp.get('status') == 'success':
                    return resp.get('data', {})
                elif isinstance(resp, dict) and (resp.get('errorCode') == 'DH-901' or 'Unauthorized' in str(resp)):
                    logger.warning("Get Order Status: 401 Unauthorized. Syncing token...")
                    if self.auth.sync_token_from_redis():
                        return self.auth.dhan.get_order_by_id(order_id)
                else:
                    logger.error(f"Failed to fetch order status for {order_id}: {resp}")
                    return None
            except Exception as e:
                logger.error(f"Exception fetching order status {order_id}: {e}")
                return None
        return None

    def modify_order(self, order_id: str, order_type: str, leg_data: Dict[str, Any]) -> Dict[str, Any]:
        """Modifies a pending order."""
        if self.auth.dry_run:
            logger.info(f"$$$ [BROKER] MOCK MODIFY Order {order_id}: {leg_data} $$$")
            return {"success": True, "order_id": order_id}

        if self.auth.dhan:
            qty = int(leg_data.get('quantity', 0))
            price = leg_data.get('price', 0.0)
            trigger_price = leg_data.get('trigger_price', 0.0)

            dhan_order_type = OrderType.LIMIT
            if order_type in ('SL', 'STOP_LOSS'): dhan_order_type = OrderType.STOP_LOSS
            if order_type in ('SL-M', 'STOP_LOSS_MARKET'): dhan_order_type = OrderType.STOP_LOSS_MARKET

            try:
                resp = self.auth.dhan.modify_order(
                    order_id=order_id,
                    order_type=dhan_order_type,
                    leg_name='ENTRY_LEG',
                    quantity=qty if qty > 0 else None,
                    price=price,
                    trigger_price=trigger_price,
                    exchange_segment=ExchangeSegment.NSE_FNO,
                    validity=Validity.DAY
                )
                if resp.get('status') == 'success':
                    logger.info(f"Order {order_id} modified successfully. P={price}, Trg={trigger_price}")
                    return {"success": True, "order_id": order_id}
                else:
                    logger.error(f"Failed to modify order {order_id}: {resp}")
                    return {"success": False, "error": resp.get('remarks')}
            except Exception as e:
                logger.error(f"Exception modifying order {order_id}: {e}")
                return {"success": False, "error": str(e)}
        return {"success": False}

    def get_pending_orders(self, security_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Fetches all PENDING standard orders."""
        if self.auth.dry_run:
            return []

        if self.auth.dhan:
            try:
                resp = self.auth.dhan.get_order_list()
                if isinstance(resp, list):
                    all_orders = resp
                elif isinstance(resp, dict) and resp.get('status') == 'success':
                    all_orders = resp.get('data', [])
                elif isinstance(resp, dict) and (resp.get('errorCode') == 'DH-901' or 'Unauthorized' in str(resp)):
                    logger.warning("Get Pending Orders: 401 Unauthorized. Syncing token...")
                    if self.auth.sync_token_from_redis():
                        resp = self.auth.dhan.get_order_list()
                        if isinstance(resp, list): all_orders = resp
                        elif isinstance(resp, dict) and resp.get('status') == 'success':
                            all_orders = resp.get('data', [])
                        else: all_orders = []
                    else:
                        all_orders = []
                else:
                    all_orders = []

                pending = [o for o in all_orders if o.get('orderStatus') in ['PENDING', 'TRIGGER_PENDING', 'TRANSIT', 'PARTIALLY_FILLED', 'MODIFY_PENDING']]
                if security_id:
                    sid_str = str(security_id).strip()
                    return [o for o in pending if str(o.get('securityId') or o.get('security_id') or '').strip() == sid_str]
                return pending
            except Exception as e:
                logger.error(f"Exception fetching order list: {e}")
                return []
        return []

    def get_super_orders(self, security_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Fetches Super Orders from dedicated endpoint."""
        if self.auth.dry_run:
            return []

        url = "https://api.dhan.co/v2/super/orders"
        headers = {
            'Content-Type': 'application/json',
            'access-token': self.auth.access_token
        }

        try:
            resp = requests.get(url, headers=headers, timeout=(5, 10))
            if resp.status_code == 200:
                data = resp.json()
                if not isinstance(data, list):
                    if isinstance(data, dict):
                        data = data.get('data', [])
                    else:
                        return []

                active_legs = []
                for so in data:
                    so_sid = str(so.get('securityId') or '').strip()
                    if security_id and so_sid != str(security_id).strip():
                        continue

                    main_oid = so.get('orderId')
                    for leg in so.get('legDetails', []):
                        leg_status = leg.get('orderStatus')
                        if leg_status in ['PENDING', 'TRIGGER_PENDING', 'TRANSIT']:
                            leg_info = {
                                'orderId': main_oid,
                                'legName': leg.get('legName'),
                                'orderType': leg.get('orderType') or ('LIMIT' if leg.get('legName') == 'TARGET_LEG' else 'STOP_LOSS_LEG'),
                                'transactionType': leg.get('transactionType'),
                                'price': leg.get('price'),
                                'triggerPrice': leg.get('triggerPrice'),
                                'trailingJump': leg.get('trailingJump'),
                                'quantity': leg.get('quantity') or leg.get('totalQuatity') or so.get('quantity'),
                                'securityId': so_sid,
                                'tradingSymbol': so.get('tradingSymbol'),
                                'is_super_order': True
                            }
                            active_legs.append(leg_info)
                return active_legs
            else:
                logger.error(f"Failed to fetch Super Order list: {resp.status_code} {resp.text}")
                return []
        except Exception as e:
            logger.error(f"Exception fetching Super Orders: {e}")
            return []

    def place_super_order(self, symbol: str, leg_data: Dict[str, Any]) -> Dict[str, Any]:
        """Places a Native Bracket Order (Super Order) using Dhan API v2."""
        if self.auth.dry_run:
            logger.info(f"$$$ [BROKER] MOCK SUPER ORDER for {symbol} $$$")
            return {"success": True, "order_id": "mock_bo_123", "error": None}

        if not self.auth.access_token or not self.auth.client_id:
            return {"success": False, "error": "Missing Info"}

        url = "https://api.dhan.co/v2/super/orders"
        headers = {
            'Content-Type': 'application/json',
            'access-token': self.auth.access_token
        }

        txn_type = leg_data.get('transaction_type', 'BUY')
        exchange_segment = "NSE_FNO"
        product_type = "INTRADAY"

        if leg_data.get('order_type') == 'LIMIT':
            order_type = "LIMIT"
            price = leg_data.get('price', 0)
        else:
            order_type = "MARKET"
            price = 0

        qty = int(leg_data.get('quantity', 1))
        sec_id = leg_data.get('security_id')
        if not sec_id:
            return {"success": False, "error": "Security ID missing for Super Order"}

        lot_size = 1
        if self.instrument and hasattr(self.instrument, 'lot_map'):
            lot_size = self.instrument.lot_map.get(sec_id, 1)
        final_qty = qty * lot_size

        target_price = leg_data.get('target_price')
        stop_loss_price = leg_data.get('stop_loss_price')
        trailing_jump = leg_data.get('trailing_jump')

        if not target_price or not stop_loss_price:
            return {"success": False, "error": "Target/SL Prices missing for Super Order"}

        try:
            tp = float(target_price)
            if tp > 10000 and len(str(sec_id)) >= 5:
                logger.error(f"ABNORMAL PRICE detected for Super Order: TGT={tp}. Likely Index spot passed to Option. REJECTING.")
                return {"success": False, "error": "Invalid Price: Index spot passed as Option price"}
        except (TypeError, ValueError) as e:
            logger.warning(f"Price validation skipped: {e}")

        price = self._round_to_tick(price)
        target_price = self._round_to_tick(target_price)
        stop_loss_price = self._round_to_tick(stop_loss_price)
        trailing_jump = self._round_to_tick(trailing_jump) if trailing_jump else 1.0

        correlation_id = f"b{int(time.time() * 1000):x}{uuid.uuid4().hex[:6]}"
        payload = {
            "dhanClientId": str(self.auth.client_id),
            "correlationId": correlation_id,
            "transactionType": txn_type,
            "exchangeSegment": exchange_segment,
            "productType": product_type,
            "orderType": order_type,
            "securityId": str(sec_id),
            "quantity": int(final_qty),
            "price": float(price) if order_type == "LIMIT" else 0.0,
            "targetPrice": float(target_price),
            "stopLossPrice": float(stop_loss_price),
            "trailingJump": float(trailing_jump)
        }

        logger.info(f"$$$ [BROKER] PLACING SUPER ORDER: {payload} $$$")

        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=(5, 10))
            if resp.status_code == 200:
                data = resp.json()
                order_id = data.get('orderId') or data.get('data', {}).get('orderId')
                status = data.get('orderStatus') or data.get('data', {}).get('orderStatus')
                if order_id:
                    return {"success": True, "order_id": order_id, "status": status}
                return {"success": False, "error": f"No orderId in response: {resp.text}"}
            elif resp.status_code == 401:
                logger.warning("Super Order Placement: 401 Unauthorized. Syncing token...")
                if self.auth.sync_token_from_redis():
                    headers['access-token'] = self.auth.access_token
                    resp = requests.post(url, headers=headers, json=payload, timeout=(5, 10))
                    if resp.status_code == 200:
                        data = resp.json()
                        order_id = data.get('orderId') or data.get('data', {}).get('orderId')
                        status = data.get('orderStatus') or data.get('data', {}).get('orderStatus')
                        return {"success": True, "order_id": order_id, "status": status}
                return {"success": False, "error": f"Auth failed after sync: {resp.text}"}
            elif resp.status_code == 500:
                logger.warning(f"Super Order: 500 Internal Server Error from Dhan. Retrying in 2s...")
                time.sleep(2)
                resp = requests.post(url, headers=headers, json=payload, timeout=(5, 10))
                if resp.status_code == 200:
                    data = resp.json()
                    order_id = data.get('orderId') or data.get('data', {}).get('orderId')
                    status = data.get('orderStatus') or data.get('data', {}).get('orderStatus')
                    if order_id:
                        logger.info(f"Super Order retry succeeded: {order_id}")
                        return {"success": True, "order_id": order_id, "status": status}
                logger.error(f"Super Order: Retry after 500 failed: {resp.status_code} {resp.text}")
                return {"success": False, "error": f"Dhan 500 after retry: {resp.text}"}
            else:
                logger.error(f"Super Order Failed: {resp.status_code} {resp.text}")
                return {"success": False, "error": resp.text}
        except Exception as e:
            logger.error(f"Super Order Exception: {e}")
            return {"success": False, "error": str(e)}

    def modify_super_target_leg(self, order_id: str, target_price: float) -> Dict[str, Any]:
        """Modifies the Target Leg of a Super Order."""
        if self.auth.dry_run:
            logger.info(f"$$$ [BROKER] MOCK MODIFY SUPER TARGET {order_id} -> {target_price} $$$")
            return {"success": True}

        if not self.auth.access_token or not self.auth.client_id:
            return {"success": False, "error": "Missing Info"}

        url = f"https://api.dhan.co/v2/super/orders/{order_id}"
        headers = {
            'Content-Type': 'application/json',
            'access-token': self.auth.access_token
        }
        payload = {
            "dhanClientId": str(self.auth.client_id),
            "orderId": str(order_id),
            "legName": "TARGET_LEG",
            "targetPrice": float(self._round_to_tick(target_price))
        }

        try:
            resp = requests.put(url, headers=headers, json=payload, timeout=(5, 10))
            if resp.status_code == 200:
                return {"success": True, "data": resp.json()}
            elif resp.status_code == 401:
                logger.warning("Modify Super Target: 401 Unauthorized. Syncing token...")
                if self.auth.sync_token_from_redis():
                    headers['access-token'] = self.auth.access_token
                    resp = requests.put(url, headers=headers, json=payload, timeout=(5, 10))
                    if resp.status_code == 200:
                        return {"success": True, "data": resp.json()}
                return {"success": False, "error": f"Auth failed after sync: {resp.text}"}
            else:
                return {"success": False, "error": resp.text}
        except Exception as e:
            logger.error(f"Modify Super Target Exception: {e}")
            return {"success": False, "error": str(e)}

    def modify_super_sl_leg(self, order_id: str, stop_loss_price: float, trailing_jump: float = 1.0) -> Dict[str, Any]:
        """Modifies the Stop Loss Leg of a Super Order."""
        if self.auth.dry_run:
            logger.info(f"$$$ [BROKER] MOCK MODIFY SUPER SL {order_id} -> SL:{stop_loss_price} $$$")
            return {"success": True}

        if not self.auth.access_token or not self.auth.client_id:
            return {"success": False, "error": "Missing Info"}

        url = f"https://api.dhan.co/v2/super/orders/{order_id}"
        headers = {
            'Content-Type': 'application/json',
            'access-token': self.auth.access_token
        }
        payload = {
            "dhanClientId": str(self.auth.client_id),
            "orderId": str(order_id),
            "legName": "STOP_LOSS_LEG",
            "stopLossPrice": float(self._round_to_tick(stop_loss_price)),
            "trailingJump": float(self._round_to_tick(trailing_jump))
        }

        try:
            resp = requests.put(url, headers=headers, json=payload, timeout=(5, 10))
            if resp.status_code == 200:
                return {"success": True, "data": resp.json()}
            elif resp.status_code == 401:
                logger.warning("Modify Super SL: 401 Unauthorized. Syncing token...")
                if self.auth.sync_token_from_redis():
                    headers['access-token'] = self.auth.access_token
                    resp = requests.put(url, headers=headers, json=payload, timeout=(5, 10))
                    if resp.status_code == 200:
                        return {"success": True, "data": resp.json()}
                return {"success": False, "error": f"Auth failed after sync: {resp.text}"}
            else:
                return {"success": False, "error": resp.text}
        except Exception as e:
            logger.error(f"Modify Super SL Exception: {e}")
            return {"success": False, "error": str(e)}

    def modify_super_entry_leg(self, order_id: str, price: float, quantity: Optional[int] = None) -> Dict[str, Any]:
        """Modifies the Entry Leg of a Super Order."""
        if self.auth.dry_run:
            logger.info(f"$$$ [BROKER] MOCK MODIFY SUPER ENTRY {order_id} -> P:{price} $$$")
            return {"success": True}

        if not self.auth.access_token or not self.auth.client_id:
            return {"success": False, "error": "Missing Info"}

        url = f"https://api.dhan.co/v2/super/orders/{order_id}"
        headers = {
            'Content-Type': 'application/json',
            'access-token': self.auth.access_token
        }
        payload = {
            "dhanClientId": str(self.auth.client_id),
            "orderId": str(order_id),
            "legName": "ENTRY_LEG",
            "price": float(self._round_to_tick(price)),
        }
        if quantity:
            payload["quantity"] = int(quantity)

        try:
            resp = requests.put(url, headers=headers, json=payload, timeout=(5, 10))
            if resp.status_code == 200:
                return {"success": True, "data": resp.json()}
            elif resp.status_code == 401:
                logger.warning("Modify Super Entry: 401 Unauthorized. Syncing token...")
                if self.auth.sync_token_from_redis():
                    headers['access-token'] = self.auth.access_token
                    resp = requests.put(url, headers=headers, json=payload, timeout=(5, 10))
                    if resp.status_code == 200:
                        return {"success": True, "data": resp.json()}
                return {"success": False, "error": f"Auth failed after sync: {resp.text}"}
            else:
                return {"success": False, "error": resp.text}
        except Exception as e:
            logger.error(f"Modify Super Entry Exception: {e}")
            return {"success": False, "error": str(e)}

    def cancel_super_order(self, order_id: str, leg_name: str = 'ENTRY_LEG') -> Dict[str, Any]:
        """Cancels a leg of a Super Order."""
        if self.auth.dry_run:
            logger.info(f"$$$ [BROKER] MOCK CANCEL SUPER ORDER {order_id} ({leg_name}) $$$")
            return {"success": True}

        if not self.auth.access_token:
            return {"success": False, "error": "Missing Token"}

        url = f"https://api.dhan.co/v2/super/orders/{order_id}/{leg_name}"
        headers = {
            'Content-Type': 'application/json',
            'access-token': self.auth.access_token
        }

        try:
            resp = requests.delete(url, headers=headers, timeout=(5, 10))
            if resp.status_code in (200, 202):
                return {"success": True, "data": resp.json() if resp.text else {}}
            elif resp.status_code == 401:
                logger.warning("Cancel Super Order: 401 Unauthorized. Syncing token...")
                if self.auth.sync_token_from_redis():
                    headers['access-token'] = self.auth.access_token
                    resp = requests.delete(url, headers=headers, timeout=(5, 10))
                    if resp.status_code in (200, 202):
                        return {"success": True, "data": resp.json() if resp.text else {}}
                return {"success": False, "error": f"Auth failed after sync: {resp.text}"}
            else:
                return {"success": False, "error": resp.text}
        except Exception as e:
            logger.error(f"Cancel Super Order Exception: {e}")
            return {"success": False, "error": str(e)}
