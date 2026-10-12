"""Dhan Emergency Safeguards and Operator Alarm Service."""

import logging
from typing import Dict, Any, Optional, Callable
from broker.common import ExchangeSegment, TransactionType, OrderType, ProductType

logger = logging.getLogger("broker.safety")


class DhanSafetyService:
    def __init__(
        self,
        order_service,
        auth_service=None,
        conditional_order_service=None,
        activity_log_fn: Optional[Callable[[str, str], None]] = None,
    ):
        self.order_service = order_service
        self.auth = auth_service
        self.conditional_order_service = conditional_order_service
        self.activity_log_fn = activity_log_fn

    def alarm(self, msg: str, prefix: str = "🚨 ") -> None:
        """Surface a disagreement or alert to the operator dashboard and Slack webhook."""
        if self.activity_log_fn:
            try:
                self.activity_log_fn(msg, prefix)
                return
            except Exception as e:
                logger.warning(f"_alarm activity_log_fn failed: {e}")
        logger.warning(f"{prefix}{msg}")

    def kill_switch(self) -> Dict[str, Any]:
        """Emergency kill switch.
        Execution sequence strictly adheres to fail-closed safety:
        Step 1 — Cancel all Super Order bracket legs (TARGET_LEG, STOP_LOSS_LEG) via cancel_super_order.
        Step 2 — Cancel all pending / transit orders (routing any remaining super legs properly).
        Step 3 — Cancel any active conditional (GTT) alert rules.
        Step 4 — Square off every net-open position with a MARKET order.
        """
        CANCELLABLE = {"TRANSIT", "PENDING", "PART_TRADED", "TRIGGER_PENDING"}
        results = {
            "cancelled_super_legs": [],
            "cancelled": [],
            "cancelled_conditional": [],
            "squaredoff": [],
            "errors": []
        }

        # Step 1: Explicitly cancel Super Order bracket legs first to prevent orphaned triggers
        try:
            if hasattr(self.order_service, 'get_super_orders'):
                super_orders = self.order_service.get_super_orders() or []
                for so in super_orders:
                    so_id = so.get('orderId')
                    leg_name = so.get('legName', 'STOP_LOSS_LEG')
                    symbol = so.get('tradingSymbol', so_id)
                    logger.warning(f"Kill Switch: Cancelling Super Order leg {so_id} ({leg_name} - {symbol})")
                    resp = self.order_service.cancel_super_order(so_id, leg_name)
                    if resp.get('success'):
                        results["cancelled_super_legs"].append({"order_id": so_id, "leg_name": leg_name, "symbol": symbol})
                    else:
                        err = f"Cancel Super Order leg failed for {so_id} ({leg_name}): {resp.get('error')}"
                        logger.error(err)
                        results["errors"].append(err)
        except Exception as e:
            err = f"Super order cancellation sweep failed: {e}"
            logger.error(f"Kill Switch: {err}")
            results["errors"].append(err)

        # Step 2: Cancel all open/pending orders from general book
        try:
            orders = self.order_service.get_all_orders() or []
            for order in orders:
                if order.get('orderStatus') not in CANCELLABLE:
                    continue
                order_id = order.get('orderId')
                symbol = order.get('tradingSymbol', order_id)
                # If order is tagged as super order or has legName, route to cancel_super_order
                if order.get('is_super_order') or order.get('legName') or order.get('productType') == 'BO':
                    leg_name = order.get('legName', 'STOP_LOSS_LEG')
                    logger.warning(f"Kill Switch: Cancelling Super Order leg {order_id} ({leg_name}) from general book")
                    resp = self.order_service.cancel_super_order(order_id, leg_name)
                else:
                    logger.warning(f"Kill Switch: Cancelling standard order {order_id} ({symbol})")
                    resp = self.order_service.cancel_order(order_id)

                if resp.get('success'):
                    results["cancelled"].append({"order_id": order_id, "symbol": symbol})
                else:
                    err = f"Cancel failed for {order_id}: {resp.get('error')}"
                    logger.error(err)
                    results["errors"].append(err)
        except Exception as e:
            err = f"Order cancel sweep failed: {e}"
            logger.error(f"Kill Switch: {err}")
            results["errors"].append(err)

        # Step 3: Cancel active conditional (GTT) alerts if available
        try:
            if self.conditional_order_service and hasattr(self.conditional_order_service, 'get_conditional_orders'):
                gtt_orders = self.conditional_order_service.get_conditional_orders() or []
                for gtt in gtt_orders:
                    alert_id = gtt.get('alertId') or gtt.get('id')
                    if alert_id:
                        logger.warning(f"Kill Switch: Cancelling GTT alert rule {alert_id}")
                        resp = self.conditional_order_service.cancel_conditional_order(alert_id)
                        if resp.get('success'):
                            results["cancelled_conditional"].append({"alert_id": alert_id})
                        else:
                            err = f"Cancel GTT alert failed for {alert_id}: {resp.get('error')}"
                            results["errors"].append(err)
        except Exception as e:
            err = f"Conditional order cancel sweep failed: {e}"
            logger.error(f"Kill Switch: {err}")
            results["errors"].append(err)

        # Step 4: Square off net open positions with market orders
        try:
            positions = self.order_service.get_positions() or []
            for pos in positions:
                net_qty = int(pos.get('netQty', 0))
                if net_qty == 0:
                    continue

                sec_id = pos.get('securityId')
                exchange_seg = pos.get('exchangeSegment', ExchangeSegment.NSE_FNO)
                product_type = pos.get('productType', ProductType.INTRADAY)
                symbol = pos.get('tradingSymbol', sec_id)
                txn_type = TransactionType.SELL if net_qty > 0 else TransactionType.BUY
                qty = abs(net_qty)

                logger.warning(f"Kill Switch: Squaring off {txn_type} {qty} × {symbol}")

                if self.auth and self.auth.dhan and not self.auth.dry_run:
                    try:
                        resp = self.auth.dhan.place_order(
                            security_id=sec_id,
                            exchange_segment=exchange_seg,
                            transaction_type=txn_type,
                            quantity=qty,
                            order_type=OrderType.MARKET,
                            product_type=product_type,
                            price=0.0
                        )
                        if resp.get('status') == 'success':
                            results["squaredoff"].append({"symbol": symbol, "qty": qty, "side": txn_type})
                        else:
                            err = f"Squareoff failed for {symbol}: {resp.get('remarks', resp)}"
                            logger.error(err)
                            results["errors"].append(err)
                    except Exception as e:
                        err = f"Exception squaring off {symbol}: {e}"
                        logger.error(err)
                        results["errors"].append(err)
                else:
                    results["squaredoff"].append({"symbol": symbol, "qty": qty, "side": txn_type, "mock": True})
        except Exception as e:
            err = f"Position fetch failed: {e}"
            logger.error(f"Kill Switch: {err}")
            results["errors"].append(err)

        msg = (
            f"Kill Switch complete — super_legs={len(results['cancelled_super_legs'])}, "
            f"cancelled={len(results['cancelled'])}, gtt={len(results['cancelled_conditional'])}, "
            f"squared_off={len(results['squaredoff'])}, errors={len(results['errors'])}"
        )
        if results["errors"]:
            logger.error(f"🚨 {msg}")
            self.alarm(msg, "🚨 ")
        else:
            logger.warning(f"🛡️ {msg}")

        return results
