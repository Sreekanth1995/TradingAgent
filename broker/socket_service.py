"""Dhan Real-Time Order Update WebSocket Service."""

import time
import json
import logging
import threading
from typing import Callable, Dict, Any, Optional
from dhanhq.orderupdate import OrderSocket

logger = logging.getLogger("broker.socket")


class DhanSocketService:
    def __init__(self, auth_service):
        self.auth = auth_service
        self.active_ws = None
        self._listener_thread: Optional[threading.Thread] = None

    def start_order_update_listener(self, on_update: Callable[[str, str, Any], None]) -> None:
        """Start Dhan Live Order Update WebSocket in a background daemon thread."""
        if not self.auth.client_id or not self.auth.access_token or self.auth.dry_run:
            logger.warning("Order update listener skipped (no credentials or dry-run mode).")
            return

        parent = self

        class _AppSocket(OrderSocket):
            def __init__(self_, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self_._on_update = on_update

            async def connect_order_update(self_):
                import websockets
                import ssl
                import certifi

                try:
                    ssl_context = ssl.create_default_context(cafile=certifi.where())
                    logger.info("Connecting to Dhan WS with secure SSL context...")
                    async with websockets.connect(
                        self_.order_feed_wss,
                        ssl=ssl_context,
                        open_timeout=10,
                        ping_interval=20,
                        ping_timeout=20
                    ) as websocket:
                        parent.active_ws = websocket
                        auth_message = {
                            "LoginReq": {
                                "MsgCode": 42,
                                "ClientId": str(self_.client_id),
                                "Token": str(self_.access_token)
                            },
                            "UserType": "SELF"
                        }

                        await websocket.send(json.dumps(auth_message))
                        logger.info("Sent subscribe message to Dhan WS.")

                        async for message in websocket:
                            if not message:
                                continue
                            if isinstance(message, bytes):
                                try:
                                    message = message.decode('utf-8')
                                except Exception as decode_err:
                                    logger.warning(f"Failed to decode bytes message: {decode_err}")
                                    continue
                            for part in message.strip().split('\n'):
                                part = part.strip()
                                if not part:
                                    continue
                                try:
                                    data = json.loads(part)
                                    await self_.handle_order_update(data)
                                except json.JSONDecodeError as je:
                                    logger.warning(f"Failed to decode message part: {part!r} | Error: {je}")
                except Exception as ws_err:
                    logger.warning(f"Dhan WS secure connection failed: {ws_err}. Attempting unverified fallback...")
                    ssl_context = ssl.create_default_context()
                    ssl_context.check_hostname = False
                    ssl_context.verify_mode = ssl.CERT_NONE
                    async with websockets.connect(
                        self_.order_feed_wss,
                        ssl=ssl_context,
                        open_timeout=10,
                        ping_interval=20,
                        ping_timeout=20
                    ) as websocket:
                        parent.active_ws = websocket
                        auth_message = {
                            "LoginReq": {
                                "MsgCode": 42,
                                "ClientId": str(self_.client_id),
                                "Token": str(self_.access_token)
                            },
                            "UserType": "SELF"
                        }

                        await websocket.send(json.dumps(auth_message))
                        logger.info("Sent subscribe message to Dhan WS (UNVERIFIED SSL).")

                        async for message in websocket:
                            if not message:
                                continue
                            if isinstance(message, bytes):
                                try:
                                    message = message.decode('utf-8')
                                except Exception as decode_err:
                                    logger.warning(f"Failed to decode bytes message: {decode_err}")
                                    continue
                            for part in message.strip().split('\n'):
                                part = part.strip()
                                if not part:
                                    continue
                                try:
                                    data = json.loads(part)
                                    await self_.handle_order_update(data)
                                except json.JSONDecodeError as je:
                                    logger.warning(f"Failed to decode message part: {part!r} | Error: {je}")
                finally:
                    parent.active_ws = None

            async def handle_order_update(self_, order_update):
                try:
                    if not isinstance(order_update, dict):
                        return
                    if order_update.get('Type') == 'order_alert':
                        data = order_update.get('Data', {})
                        order_id = str(data.get('orderNo', ''))
                        status = data.get('status', '')
                        avg_price = data.get('averageTradedPrice') or data.get('tradedPrice')
                        if order_id:
                            self_._on_update(order_id, status, avg_price)
                except Exception as e:
                    logger.error(f"Order update handler error: {e}")

        def _run():
            import asyncio as _asyncio
            backoff = 5
            while True:
                try:
                    sock = _AppSocket(parent.auth.client_id, parent.auth.access_token)
                    loop = _asyncio.new_event_loop()
                    _asyncio.set_event_loop(loop)
                    loop.run_until_complete(sock.connect_order_update())
                except Exception as e:
                    logger.warning(f"Order update WS disconnected: {e}. Reconnecting in {backoff}s…")
                    time.sleep(backoff)
                    backoff = min(backoff * 2, 120)
                else:
                    logger.warning(f"Order update WS connection closed. Reconnecting in {backoff}s…")
                    time.sleep(backoff)
                    backoff = min(backoff * 2, 120)

        t = threading.Thread(target=_run, daemon=True, name="dhan-order-ws")
        t.start()
        self._listener_thread = t
        logger.info("✅ Dhan Live Order Update listener started.")
