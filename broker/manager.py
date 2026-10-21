"""MultiBrokerManager - Multi-Tenant / Multi-Broker Dispatcher.

Orchestrates order placement, risk checks, and state across multiple broker accounts (Dhan, Groww, FlatTrade).
Guarantees:
1. Thread-pool parallel dispatch for minimal execution latency.
2. Isolated fail-safe execution (an outage on one broker never impedes others).
3. Independent per-account lot multipliers.
4. Account-scoped Redis state tracking.
"""

import os
import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional, Dict, Any, List, Set

logger = logging.getLogger("broker.manager")


class MultiBrokerManager:
    def __init__(
        self,
        redis_client=None,
        brokers: Optional[Dict[str, Any]] = None,
        default_broker: str = "dhan",
    ):
        self.redis_client = redis_client
        self.brokers: Dict[str, Any] = brokers or {}
        self.default_broker = default_broker

        # Active status toggle per broker
        self.enabled_brokers: Set[str] = set()

        # Independent per-account lot multipliers
        self.lot_multipliers: Dict[str, int] = {
            "dhan": int(os.getenv("DHAN_LOT_MULTIPLIER", 1)),
            "groww": int(os.getenv("GROWW_LOT_MULTIPLIER", 1)),
            "flattrade": int(os.getenv("FLAT_LOT_MULTIPLIER", 1)),
        }

        # Initialize enabled brokers from registered clients
        for name in self.brokers:
            self.enabled_brokers.add(name)

        # Restore toggles & multipliers from Redis if present
        self._load_config_from_redis()

    def _load_config_from_redis(self) -> None:
        if not self.redis_client:
            return
        try:
            stored_cfg = self.redis_client.get("config:multi_broker")
            if stored_cfg:
                cfg = json.loads(stored_cfg)
                if "enabled_brokers" in cfg:
                    self.enabled_brokers = set(cfg["enabled_brokers"]).intersection(self.brokers.keys())
                if "lot_multipliers" in cfg:
                    self.lot_multipliers.update(cfg["lot_multipliers"])
                logger.info("MultiBrokerManager: Restored config from Redis")
        except Exception as e:
            logger.warning(f"MultiBrokerManager: Failed to load config from Redis: {e}")

    def _save_config_to_redis(self) -> None:
        if not self.redis_client:
            return
        try:
            cfg = {
                "enabled_brokers": list(self.enabled_brokers),
                "lot_multipliers": self.lot_multipliers,
            }
            self.redis_client.set("config:multi_broker", json.dumps(cfg))
        except Exception as e:
            logger.warning(f"MultiBrokerManager: Failed to save config to Redis: {e}")

    def register_broker(self, name: str, client: Any, enabled: bool = True) -> None:
        """Register a broker client adapter."""
        self.brokers[name] = client
        if enabled:
            self.enabled_brokers.add(name)
        if name not in self.lot_multipliers:
            self.lot_multipliers[name] = 1
        self._save_config_to_redis()
        logger.info(f"MultiBrokerManager: Registered broker '{name}' (enabled={enabled})")

    def toggle_broker(self, name: str, enabled: bool) -> bool:
        """Enable or disable a broker in the dispatch list."""
        if name not in self.brokers:
            return False
        if enabled:
            self.enabled_brokers.add(name)
        else:
            self.enabled_brokers.discard(name)
        self._save_config_to_redis()
        logger.info(f"MultiBrokerManager: Broker '{name}' enabled={enabled}")
        return True

    def set_lot_multiplier(self, name: str, multiplier: int) -> bool:
        """Update lot multiplier for a broker account."""
        if multiplier < 1:
            multiplier = 1
        self.lot_multipliers[name] = multiplier
        self._save_config_to_redis()
        logger.info(f"MultiBrokerManager: Broker '{name}' lot multiplier set to {multiplier}")
        return True

    def _get_target_brokers(self, accounts: Optional[List[str]] = None) -> List[str]:
        """Resolves target brokers based on accounts tag and enabled status."""
        if accounts:
            targets = [a.lower() for a in accounts if a.lower() in self.brokers and a.lower() in self.enabled_brokers]
            return targets if targets else list(self.enabled_brokers)
        return list(self.enabled_brokers)

    def _update_account_state(self, broker_name: str, symbol: str, res: Dict[str, Any], leg_data: Dict[str, Any]) -> None:
        """Record account-scoped position state in Redis."""
        if not self.redis_client:
            return
        try:
            key = f"state:{broker_name}:{symbol}"
            state = {
                "broker": broker_name,
                "symbol": symbol,
                "order_id": res.get("order_id"),
                "status": res.get("status"),
                "transactionType": leg_data.get("transactionType", "BUY"),
                "quantity": leg_data.get("quantity"),
            }
            self.redis_client.set(key, json.dumps(state), ex=86400)
        except Exception as e:
            logger.warning(f"Failed to record state for {broker_name}:{symbol} in Redis: {e}")

    def place_super_order(
        self,
        symbol: str,
        leg_data: Dict[str, Any],
        accounts: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """Parallel dispatch of super/bracket orders across target broker accounts."""
        targets = self._get_target_brokers(accounts)
        if not targets:
            logger.error("MultiBrokerManager: No active enabled brokers found to place super order")
            return {"status": "error", "message": "No active enabled brokers"}

        results = {}
        base_qty = int(leg_data.get("quantity", 1))

        def _dispatch_single(broker_name: str):
            client = self.brokers[broker_name]
            multiplier = self.lot_multipliers.get(broker_name, 1)
            broker_leg = dict(leg_data)
            broker_leg["quantity"] = base_qty * multiplier
            try:
                res = client.place_super_order(symbol, broker_leg)
                self._update_account_state(broker_name, symbol, res, broker_leg)
                return broker_name, res
            except Exception as e:
                logger.error(f"MultiBrokerManager: Error placing order on {broker_name}: {e}")
                return broker_name, {"status": "error", "message": str(e), "broker": broker_name}

        with ThreadPoolExecutor(max_workers=max(len(targets), 1)) as executor:
            future_to_broker = {executor.submit(_dispatch_single, b): b for b in targets}
            for future in as_completed(future_to_broker):
                b_name, res = future.result()
                results[b_name] = res

        def _is_success(r):
            if not isinstance(r, dict):
                return False
            if r.get("status") == "success":
                return True
            if r.get("order_id") or r.get("orderId") or r.get("noren_order_id") or r.get("groww_order_id"):
                return True
            if r.get("success") is True or r.get("orderStatus") in ("SUCCESS", "FILLED", "OPEN", "COMPLETE"):
                return True
            return False

        has_success = any(_is_success(r) for r in results.values())
        primary_broker = self.default_broker if self.default_broker in results else (targets[0] if targets else "none")
        primary_res = results.get(primary_broker, {})

        return {
            "status": "success" if has_success else "error",
            "order_id": primary_res.get("order_id") or primary_res.get("orderId"),
            "primary_broker": primary_broker,
            "results": results,
        }

    def place_order(
        self,
        symbol: str,
        leg_data: Dict[str, Any],
        accounts: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """Parallel dispatch of regular orders across target broker accounts."""
        targets = self._get_target_brokers(accounts)
        if not targets:
            return {"status": "error", "message": "No active enabled brokers"}

        results = {}
        base_qty = int(leg_data.get("quantity", 1))

        def _dispatch_single(broker_name: str):
            client = self.brokers[broker_name]
            multiplier = self.lot_multipliers.get(broker_name, 1)
            broker_leg = dict(leg_data)
            broker_leg["quantity"] = base_qty * multiplier
            try:
                res = client.place_order(symbol, broker_leg)
                self._update_account_state(broker_name, symbol, res, broker_leg)
                return broker_name, res
            except Exception as e:
                return broker_name, {"status": "error", "message": str(e), "broker": broker_name}

        with ThreadPoolExecutor(max_workers=max(len(targets), 1)) as executor:
            future_to_broker = {executor.submit(_dispatch_single, b): b for b in targets}
            for future in as_completed(future_to_broker):
                b_name, res = future.result()
                results[b_name] = res

        has_success = any(
            isinstance(r, dict) and (
                r.get("status") == "success" or
                r.get("order_id") or
                r.get("orderId") or
                r.get("success") is True or
                r.get("orderStatus") in ("SUCCESS", "FILLED", "OPEN", "COMPLETE")
            )
            for r in results.values()
        )
        primary_broker = self.default_broker if self.default_broker in results else (targets[0] if targets else "none")
        return {
            "status": "success" if has_success else "error",
            "order_id": results.get(primary_broker, {}).get("order_id") or results.get(primary_broker, {}).get("orderId"),
            "results": results,
        }

    def modify_order(self, order_id: str, order_type: str, leg_data: Dict[str, Any]) -> Dict[str, Any]:
        """Modify order across all brokers that recognize this order_id or all brokers."""
        results = {}
        for b_name in self.enabled_brokers:
            client = self.brokers[b_name]
            try:
                res = client.modify_order(order_id, order_type, leg_data)
                results[b_name] = res
            except Exception as e:
                results[b_name] = {"status": "error", "message": str(e)}
        return {"status": "success", "results": results}

    def cancel_order(self, order_id: str) -> Dict[str, Any]:
        """Cancel order across active brokers."""
        results = {}
        for b_name in self.enabled_brokers:
            client = self.brokers[b_name]
            try:
                res = client.cancel_order(order_id)
                results[b_name] = res
            except Exception as e:
                results[b_name] = {"status": "error", "message": str(e)}
        return {"status": "success", "results": results}

    def get_positions(self) -> List[Dict[str, Any]]:
        """Fetch and aggregate positions from all active brokers."""
        all_positions = []
        for b_name in self.enabled_brokers:
            client = self.brokers[b_name]
            try:
                positions = client.get_positions()
                for p in positions:
                    if "broker" not in p:
                        p["broker"] = b_name
                    all_positions.append(p)
            except Exception as e:
                logger.error(f"Failed to fetch positions from {b_name}: {e}")
        return all_positions

    def get_limits(self) -> Dict[str, Any]:
        """Fetch margin limits from all active brokers and compute aggregate total."""
        broker_limits = {}
        total_available = 0.0
        total_used = 0.0
        for b_name in self.enabled_brokers:
            client = self.brokers[b_name]
            try:
                limits = client.get_limits()
                avail = float(limits.get("available_margin", 0.0))
                used = float(limits.get("used_margin", 0.0))
                broker_limits[b_name] = limits
                total_available += avail
                total_used += used
            except Exception as e:
                logger.error(f"Failed to fetch limits from {b_name}: {e}")
                broker_limits[b_name] = {"error": str(e), "available_margin": 0.0, "used_margin": 0.0}

        return {
            "total_available": total_available,
            "total_used": total_used,
            "brokers": broker_limits,
        }

    def get_fund_limits(self) -> Dict[str, Any]:
        return self.get_limits()

    def kill_switch(self, target_broker: Optional[str] = None) -> Dict[str, Any]:
        """Emergency kill switch: flatten positions for specific broker or all brokers."""
        results = {}
        targets = [target_broker.lower()] if target_broker and target_broker.lower() != "all" else list(self.brokers.keys())

        for b_name in targets:
            if b_name in self.brokers:
                client = self.brokers[b_name]
                try:
                    res = client.kill_switch()
                    results[b_name] = res
                except Exception as e:
                    results[b_name] = {"status": "error", "message": str(e)}

        return {"status": "success", "target": target_broker or "all", "results": results}

    # --- Compatibility & Delegations for SuperOrderEngine / Callers ---

    def get_ltp(self, security_id: str, exchange_segment: str = "NSE_FNO") -> float:
        """Fetch LTP from default broker (Dhan)."""
        primary = self.brokers.get(self.default_broker)
        if primary and hasattr(primary, "get_ltp"):
            return primary.get_ltp(security_id, exchange_segment)
        return 0.0

    def modify_super_sl_leg(self, order_id: str, stop_loss_price: float, trailing_jump: float = 1.0) -> Dict[str, Any]:
        """Modify SL leg across active brokers."""
        results = {}
        for b_name in self.enabled_brokers:
            client = self.brokers[b_name]
            if hasattr(client, "modify_super_sl_leg"):
                try:
                    results[b_name] = client.modify_super_sl_leg(order_id, stop_loss_price, trailing_jump)
                except Exception as e:
                    results[b_name] = {"status": "error", "message": str(e)}
            elif hasattr(client, "modify_order"):
                try:
                    results[b_name] = client.modify_order(order_id, "SL", {"stop_loss_price": stop_loss_price})
                except Exception as e:
                    results[b_name] = {"status": "error", "message": str(e)}
        return {"status": "success", "results": results}

    def modify_super_target_leg(self, order_id: str, target_price: float) -> Dict[str, Any]:
        """Modify target leg across active brokers."""
        results = {}
        for b_name in self.enabled_brokers:
            client = self.brokers[b_name]
            if hasattr(client, "modify_super_target_leg"):
                try:
                    results[b_name] = client.modify_super_target_leg(order_id, target_price)
                except Exception as e:
                    results[b_name] = {"status": "error", "message": str(e)}
            elif hasattr(client, "modify_order"):
                try:
                    results[b_name] = client.modify_order(order_id, "TARGET", {"target_price": target_price})
                except Exception as e:
                    results[b_name] = {"status": "error", "message": str(e)}
        return {"status": "success", "results": results}

    def modify_super_entry_leg(self, order_id: str, price: float, quantity: Optional[int] = None) -> Dict[str, Any]:
        """Modify entry leg across active brokers."""
        results = {}
        for b_name in self.enabled_brokers:
            client = self.brokers[b_name]
            if hasattr(client, "modify_super_entry_leg"):
                try:
                    results[b_name] = client.modify_super_entry_leg(order_id, price, quantity)
                except Exception as e:
                    results[b_name] = {"status": "error", "message": str(e)}
        return {"status": "success", "results": results}

    def cancel_super_order(self, order_id: str, leg_name: str = 'ENTRY_LEG') -> Dict[str, Any]:
        """Cancel super order / legs across active brokers."""
        results = {}
        for b_name in self.enabled_brokers:
            client = self.brokers[b_name]
            if hasattr(client, "cancel_super_order"):
                try:
                    results[b_name] = client.cancel_super_order(order_id, leg_name)
                except Exception as e:
                    results[b_name] = {"status": "error", "message": str(e)}
            elif hasattr(client, "cancel_order"):
                try:
                    results[b_name] = client.cancel_order(order_id)
                except Exception as e:
                    results[b_name] = {"status": "error", "message": str(e)}
        return {"status": "success", "results": results}

    @property
    def scrip_map(self) -> Dict[str, Any]:
        primary = self.brokers.get(self.default_broker)
        return getattr(primary, "scrip_map", {})

    @property
    def lot_map(self) -> Dict[str, int]:
        primary = self.brokers.get(self.default_broker)
        return getattr(primary, "lot_map", {})

    @property
    def exact_symbol_map(self) -> Dict[str, str]:
        primary = self.brokers.get(self.default_broker)
        return getattr(primary, "exact_symbol_map", {})

    def get_security_info_by_symbol(self, exact_symbol: str) -> Optional[Dict[str, Any]]:
        primary = self.brokers.get(self.default_broker)
        if primary and hasattr(primary, "get_security_info_by_symbol"):
            return primary.get_security_info_by_symbol(exact_symbol)
        return None

    def get_account_statuses(self) -> List[Dict[str, Any]]:
        """Returns comprehensive account statuses for the Admin Dashboard."""
        statuses = []
        for b_name, client in self.brokers.items():
            auth_info = {}
            if hasattr(client, "get_auth_status"):
                auth_info = client.get_auth_status()
            elif hasattr(client, "auth_service") and hasattr(client.auth_service, "get_auth_status"):
                auth_info = client.auth_service.get_auth_status()

            statuses.append({
                "broker": b_name,
                "display_name": b_name.upper(),
                "enabled": b_name in self.enabled_brokers,
                "lot_multiplier": self.lot_multipliers.get(b_name, 1),
                "is_active": auth_info.get("is_active", True),
                "ucc": auth_info.get("ucc", "N/A"),
                "masked_token": auth_info.get("masked_token"),
                "dry_run": getattr(client, "dry_run", False),
            })
        return statuses

    def calculate_lots_by_margin(self, security_id: str, transaction_type: str = "BUY", ltp: float = 0) -> int:
        primary = self.brokers.get(self.default_broker)
        if primary and hasattr(primary, "calculate_lots_by_margin"):
            return primary.calculate_lots_by_margin(security_id, transaction_type, ltp)
        return 1

