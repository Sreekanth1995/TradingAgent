# Phase 4 Verification: Positions Container

## Acceptance Criteria
- [ ] Dashboard displays "Live Positions" cards for active trades.
- [ ] PnL and LTP update every 5 seconds without page reload.
- [ ] PnL color-codes (Green for Profit, Red for Loss).
- [ ] LTP shows `---` if the broker API returns no price.
- [ ] "No active positions" message appears when side is NONE for all indices.

## Test Cases

### 1. Backend Position Aggregation
- **Unit**: Mock `engine._get_state` to return a CALL position for NIFTY.
- **Expect**: `_get_active_positions()` returns an array with one entry.

### 2. LTP Error Handling
- **Unit**: Mock `broker.get_ltp` to return `None`.
- **Expect**: Position data includes `ltp: '---'` and `pnl_abs: '---'`.

### 3. Frontend Rendering
- **E2E**: Launch dashboard in mock mode with one active trade.
- **Expect**: `.position-card` exists and contains the correct symbol and side badge.
