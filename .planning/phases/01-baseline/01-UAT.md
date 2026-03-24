# UAT: Baseline Strategy & Native Super Orders

**Phase**: 01-baseline
**Date**: 2026-03-24
**Status**: PASSED

## Test Cases

### TC-01: Market Price Entry
- **Goal**: Ensure entry orders use MARKET type for immediate fill.
- **Verification**: `test_native_super_order_uses_market_entry` in `test_super_order_smart_exit_refined.py`.
- **Result**: [PASS] Payload contains `orderType: MARKET`.

### TC-02: Strategy Percentages (55/20/10)
- **Goal**: Verify Target at 55%, SL at 20%, and Trailing at 10%.
- **Verification**: `test_open_position_percentage_math` in `test_percentage_calculations.py`.
- **Result**: [PASS] Calculated prices match expected baseline (e.g., 100 LTP -> 155 Target).

### TC-03: Smart Reversal Exit (+5/-5 pts)
- **Goal**: Verify that reversal signals trigger immediate leg modification with fixed offsets.
- **Verification**: `test_smart_exit_super_order_fixed_offset` in `test_percentage_calculations.py`.
- **Result**: [PASS] `modify_super_target_leg` called with `LTP + 5`.

### TC-04: Method Alignment
- **Goal**: Ensure `RankingEngine` calls the correct `broker_dhan` methods.
- **Verification**: All unit tests passing with new method names.
- **Result**: [PASS] Consolidated method interface.

## Conclusion
Phase 1 core logic is robust and verified against the defined strategy. No regression found in existing instrument mapping or state management.
