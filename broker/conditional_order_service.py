"""Dhan Conditional Trigger (GTT-style) Order Service."""

import json
import logging
import requests
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from constants import is_index_id, IDX_SEGMENT

logger = logging.getLogger("broker.conditional")


class DhanConditionalOrderService:
    def __init__(self, auth_service, market_data_service=None):
        self.auth = auth_service
        self.market_data = market_data_service

    def _round_to_tick(self, price: float, tick: float = 0.05) -> float:
        if self.market_data:
            return self.market_data.round_to_tick(price, tick)
        if not price:
            return 0.0
        return round(round(float(price) / tick) * tick, 2)

    def place_conditional_order(
        self,
        sec_id: str,
        exchange_seg: str,
        quantity: int,
        operator: str,
        comparing_value: float,
        transaction_type: str = "SELL",
        product_type: str = "MARGIN",
        trigger_sec_id: Optional[str] = None,
        user_note: Optional[str] = None
    ) -> Dict[str, Any]:
        """Places a Dhan Conditional Trigger Order (GTT-style)."""
        comparing_value = self._round_to_tick(comparing_value)

        if self.auth.dry_run:
            mock_id = f"DRY_{operator}_{comparing_value}"
            logger.info(f"[DRY RUN] Conditional Order: {transaction_type} {operator} @ {comparing_value} secId={sec_id} TriggerId={trigger_sec_id or sec_id} Note={user_note}")
            return {"success": True, "alert_id": mock_id, "error": None}

        if not self.auth.client_id or not self.auth.access_token:
            return {"success": False, "alert_id": None, "error": "Missing credentials"}

        import pytz
        IST = pytz.timezone('Asia/Kolkata')
        exp_date = (datetime.now(IST) + timedelta(days=365)).strftime('%Y-%m-%d')

        url = "https://api.dhan.co/v2/alerts/orders"
        headers = {
            'Content-Type': 'application/json',
            'access-token': self.auth.access_token,
            'client-id': str(self.auth.client_id)
        }

        actual_trigger_id = str(trigger_sec_id) if trigger_sec_id else str(sec_id)
        condition_exchange_seg = IDX_SEGMENT if is_index_id(actual_trigger_id) else exchange_seg

        dhan_operator = operator
        if operator == "ABOVE":
            dhan_operator = "GREATER_THAN"
        elif operator == "BELOW":
            dhan_operator = "LESS_THAN"

        payload = {
            "dhanClientId": str(self.auth.client_id),
            "userNote": user_note if user_note else "GTT Trigger",
            "condition": {
                "comparisonType": "PRICE_WITH_VALUE",
                "exchangeSegment": condition_exchange_seg,
                "securityId": str(actual_trigger_id),
                "operator": dhan_operator,
                "comparingValue": float(comparing_value),
                "expDate": exp_date,
                "frequency": "ONCE"
            },
            "orders": [{
                "transactionType": transaction_type,
                "exchangeSegment": exchange_seg,
                "productType": product_type,
                "orderType": "MARKET",
                "securityId": str(sec_id),
                "quantity": int(quantity),
                "validity": "DAY",
                "price": 0,
                "disclosedQuantity": 0,
                "triggerPrice": 0,
                "afterMarketOrder": False,
                "amo": False
            }]
        }

        payload_json = json.dumps(payload)
        logger.info(f"$$$ SENDING GTT ALERT PAYLOAD: {payload_json}")
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=(5, 10))
            if resp.status_code in [200, 201]:
                data = resp.json()
                alert_id = data.get('alertId') or (data.get('data') or {}).get('alertId')
                logger.info(f"Conditional order placed: alertId={alert_id}, op={operator}, val={comparing_value}, triggerSec={actual_trigger_id}")
                return {"success": True, "alert_id": alert_id, "error": None}
            else:
                logger.error(f"Conditional order failed: {resp.status_code} {resp.text}")
                return {"success": False, "alert_id": None, "error": resp.text}
        except Exception as e:
            logger.error(f"Conditional order exception: {e}")
            return {"success": False, "alert_id": None, "error": str(e)}

    def cancel_conditional_order(self, alert_id: str) -> Dict[str, Any]:
        """Cancels an active Dhan Conditional Trigger by alertId."""
        if self.auth.dry_run:
            logger.info(f"[DRY RUN] Cancel conditional order alertId={alert_id}")
            return {"success": True}

        if not self.auth.access_token:
            return {"success": False, "error": "Missing credentials"}

        url = f"https://api.dhan.co/v2/alerts/orders/{alert_id}"
        headers = {
            'Content-Type': 'application/json',
            'access-token': self.auth.access_token,
            'client-id': str(self.auth.client_id)
        }
        try:
            resp = requests.delete(url, headers=headers, timeout=(5, 10))
            if resp.status_code in [200, 204]:
                logger.info(f"Conditional order cancelled: alertId={alert_id}")
                return {"success": True}
            else:
                logger.error(f"Cancel conditional order failed: {resp.status_code} {resp.text}")
                return {"success": False, "error": resp.text}
        except Exception as e:
            logger.error(f"Cancel conditional order exception: {e}")
            return {"success": False, "error": str(e)}

    def modify_conditional_order(self, alert_id: str, quantity: int, comparing_value: float) -> Dict[str, Any]:
        """Modifies an existing Dhan Conditional Trigger Order (GTT)."""
        comparing_value = self._round_to_tick(comparing_value)

        if self.auth.dry_run:
            logger.info(f"[DRY RUN] Modifying Conditional Order {alert_id}: Qty={quantity}, Val={comparing_value}")
            return {"success": True, "alert_id": alert_id, "error": None}

        if not self.auth.access_token:
            return {"success": False, "error": "Missing access token"}

        url = f"https://api.dhan.co/v2/alerts/orders/{alert_id}"
        headers = {
            'Content-Type': 'application/json',
            'access-token': self.auth.access_token,
            'client-id': str(self.auth.client_id)
        }

        existing = self.get_conditional_order_details(alert_id)
        if not existing:
            return {"success": False, "error": "Could not fetch existing alert details for modification"}

        payload = {
            "dhanClientId": str(self.auth.client_id),
            "condition": existing.get("condition", {}),
            "orders": existing.get("orders", [])
        }

        if "condition" in payload:
            payload["condition"]["comparingValue"] = float(comparing_value)
        if "orders" in payload and len(payload["orders"]) > 0:
            payload["orders"][0]["quantity"] = int(quantity)

        try:
            resp = requests.put(url, headers=headers, json=payload, timeout=5)
            if resp.status_code == 200:
                logger.info(f"Conditional Order {alert_id} modified successfully.")
                return {"success": True, "alert_id": alert_id, "error": None}
            if resp.status_code == 401:
                logger.warning("Modify GTT: 401 Unauthorized. Syncing token...")
                if self.auth.sync_token_from_redis():
                    headers['access-token'] = self.auth.access_token
                    resp = requests.put(url, headers=headers, json=payload, timeout=5)
                    if resp.status_code == 200:
                        logger.info(f"Conditional Order {alert_id} modified successfully after token refresh.")
                        return {"success": True, "alert_id": alert_id, "error": None}
            logger.error(f"Modify Conditional Failed: {resp.status_code} {resp.text}")
            return {"success": False, "error": resp.text}
        except Exception as e:
            logger.error(f"Modify Conditional Exception: {e}")
            return {"success": False, "error": str(e)}

    def get_conditional_order_details(self, alert_id: str) -> Optional[Dict[str, Any]]:
        """Fetches details for a specific alert."""
        if self.auth.dry_run:
            return {}
        url = f"https://api.dhan.co/v2/alerts/orders/{alert_id}"
        headers = {
            'access-token': self.auth.access_token,
            'client-id': str(self.auth.client_id)
        }
        try:
            resp = requests.get(url, headers=headers, timeout=(5, 10))
            if resp.status_code == 200:
                return resp.json().get('data', {})
            if resp.status_code == 401:
                logger.warning("Get GTT Details: 401 Unauthorized. Syncing token...")
                if self.auth.sync_token_from_redis():
                    headers['access-token'] = self.auth.access_token
                    resp = requests.get(url, headers=headers, timeout=(5, 10))
                    if resp.status_code == 200:
                        return resp.json().get('data', {})
        except Exception as e:
            logger.error(f"Exception fetching conditional order details for {alert_id}: {e}")
        return None

    def get_all_gtt_orders(self) -> List[Dict[str, Any]]:
        """Fetches all conditional orders (GTT alerts) from Dhan."""
        if self.auth.dry_run:
            return []
        url = "https://api.dhan.co/v2/alerts/orders"
        headers = {
            'access-token': self.auth.access_token,
            'client-id': str(self.auth.client_id)
        }
        try:
            resp = requests.get(url, headers=headers, timeout=(5, 10))
            if resp.status_code == 200:
                res_data = resp.json()
                if isinstance(res_data, list):
                    return res_data
                elif isinstance(res_data, dict):
                    return res_data.get('data', []) or res_data or []
                return []
            if resp.status_code == 401:
                logger.warning("Get GTT: 401 Unauthorized. Syncing token...")
                if self.auth.sync_token_from_redis():
                    headers['access-token'] = self.auth.access_token
                    resp = requests.get(url, headers=headers, timeout=(5, 10))
                    if resp.status_code == 200:
                        res_data = resp.json()
                        if isinstance(res_data, list):
                            return res_data
                        elif isinstance(res_data, dict):
                            return res_data.get('data', []) or res_data or []
                        return []
            logger.error(f"Failed to fetch GTT alerts: {resp.status_code} {resp.text}")
            return []
        except Exception as e:
            logger.error(f"Exception fetching GTT alerts: {e}")
            return []
