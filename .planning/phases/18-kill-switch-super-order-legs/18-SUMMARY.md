# Summary: Phase 18 - Kill Switch Super Order Leg Cancellation

## Executive Summary
Resolved the critical P0 safety hazard in `kill_switch()` where Super Order bracket legs (`TARGET_LEG` and `STOP_LOSS_LEG`) were bypassed or targeted via the invalid standard `/orders/{orderId}` cancel endpoint, leaving open bracket legs active at Dhan to fire as naked shorts after position flattening.

## Key Changes
1. **Safety Execution Order Re-Architecture (`broker/safety_service.py`)**:
   - Reordered `kill_switch()` steps to guarantee cancel-before-liquidate safety:
     1. **Step 1**: Query `get_super_orders()` and explicitly cancel all bracket legs (`TARGET_LEG`, `STOP_LOSS_LEG`) using `order_service.cancel_super_order(order_id, leg_name)`.
     2. **Step 2**: Query `get_all_orders()` and sweep general pending/transit orders, routing any Super Order legs to `cancel_super_order` and standard orders to `cancel_order`.
     3. **Step 3**: Cancel all active conditional (GTT) alert rules to ensure no pending trigger orders fire post-kill.
     4. **Step 4**: Liquidate net open positions using MARKET orders.
2. **Service Wiring (`broker/client.py`)**:
   - Injected `conditional_order_service` into `DhanSafetyService` during initialization for full coordinated GTT cancellation.
3. **Verification**:
   - Added unit test in `tests/test_modular_broker.py` testing the complete 4-stage cancellation and liquidation sequence.
   - All **120 unit tests passing**.
