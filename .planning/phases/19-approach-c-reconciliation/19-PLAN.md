# Plan: Phase 19 - Approach C Autonomous Reconciliation Safety Net

## Goal
Implement robust redundant fill detection in `ConditionalOrderEngine` for conditional orders when webhook postbacks are missed, handle REJECTED/CANCELLED entry postbacks to prevent wedged state, and enforce fail-closed lot validation at fill time.

## Tasks
- [x] In `conditional_order_engine.py`:
  - Update `handle_postback` to handle `order_status in ('REJECTED', 'CANCELLED')` for `ENTRY:` notes: clear `PENDING_*` state, consume `pending_protection`, and emit an alarm.
  - In `_handle_conditional_fill`, enforce fail-closed validation when `lot_size <= 0` or missing in `lot_map`: mark `protection_failed=True` and refuse to arm oversized brackets.
  - In `monitor_positions`, implement multi-underlying position reconciliation:
    - Efficiently fetch `broker.get_positions()` once per throttle cycle when any pending order exists.
    - Transition state to live `CALL`/`PUT` when filled on broker.
    - Verify `lot_size` before arming protection.
    - Consume `pending_protection` idempotently.
    - Alarm loudly (`🚨`) if a filled position has no pending protection record.
- [x] In `tests/test_conditional_entry.py` or new test:
  - Add test for REJECTED/CANCELLED postback clearing pending state.
  - Add test for reconciliation detecting filled pending position without postback.
  - Add test for fail-closed lot size handling at fill time.
- [x] Run complete test suite (`pytest tests/`) and ensure 100% pass rate.
