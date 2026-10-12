# Plan: Phase 18 - Kill Switch Super Order Leg Cancellation

## Goal
Harden emergency `kill_switch()` to cancel all Super Order bracket legs (`TARGET_LEG`, `STOP_LOSS_LEG`), standard pending orders, and GTT rules BEFORE liquidating open positions, eliminating the risk of orphaned trigger legs firing as naked shorts.

## Tasks
- [x] In `broker/safety_service.py`:
  - Update `DhanSafetyService.__init__` to accept optional `conditional_order_service`.
  - Reorder `kill_switch()` execution:
    1. Query `get_super_orders()` and cancel all active bracket legs via `cancel_super_order(order_id, leg_name)`.
    2. Query `get_all_orders()` and cancel any remaining pending/transit orders (routing super order legs to `cancel_super_order` and standard orders to `cancel_order`).
    3. Cancel active GTT rules if `conditional_order_service` is present.
    4. Liquidate open positions via market orders.
  - Record detailed cancellation metrics (`cancelled_super_legs`, `cancelled_orders`, `squaredoff`, `errors`).
- [x] In `broker/client.py`:
  - Pass `conditional_order_service` into `DhanSafetyService` instantiation.
- [x] In `tests/test_modular_broker.py`:
  - Add test verifying `kill_switch()` cancels Super Order legs via `cancel_super_order` and cancels standard orders before flattening positions.
- [x] Run test suite (`pytest tests/`) to ensure 100% pass rate.
