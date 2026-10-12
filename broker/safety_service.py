"""Dhan Emergency Safeguards and Operator Alarm Service."""

import logging
from typing import Dict, Any, Optional, Callable
from broker.common import ExchangeSegment, TransactionType, OrderType, ProductType

logger = logging.getLogger("broker.safety")


class DhanSafetyService:
    def __init__(self, order_service, auth_service=None, activity_log_fn: Optional[Callable[[str, str], None]] = None):
        self.order_service = order_service
        self.auth = auth_service
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
        Step 1 — square off every net-open position with a market order.
        Step 2 — cancel every TRANSIT / PENDING / PART_TRADED order.
        """
        CANCELLABLE = {"TRANSIT", "PENDING", "PART_TRADED"}
        results = {"squaredoff": [], "cancelled": [], "errors": []}

        # Step 1: Square off positions
        try:
            positions = self.order_service.get_positions()
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

        # Step 2: Cancel all open/pending orders
        try:
            orders = self.order_service.get_all_orders()
            for order in orders:
                if order.get('orderStatus') not in CANCELLABLE:
                    continue
                order_id = order.get('orderId')
                symbol = order.get('tradingSymbol', order_id)
                logger.warning(f"Kill Switch: Cancelling order {order_id} ({symbol})")
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

        logger.warning(
            f"Kill Switch complete — squared_off={len(results['squaredoff'])}, "
            f"cancelled={len(results['cancelled'])}, errors={len(results['errors'])}"
        )
        return results
