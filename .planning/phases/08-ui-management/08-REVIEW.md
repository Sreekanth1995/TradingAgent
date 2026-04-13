---
padded_phase: "08"
phase_name: "Dashboard UI & Position Management Overhaul"
status: "issues_found"
files_reviewed: 3
critical: 1
warning: 1
info: 2
total: 4
---

# Code Review: Phase 08

## Summary
Phase 08 successfully integrated P&L displays and enforced SL/Target indices for new BUY orders. However, critical connectivity issues and incomplete state-locking for GTT controls were identified.

## Findings

### ### CR-01: Backend Route Mismatch (Critical)
**File**: [index.html](file:///Users/sreekanthmekala/Desktop/TradingAgent/templates/index.html:L1642)
**Description**: The frontend attempts to POST to `/set-conditional-orders`, but this route does not exist in `server.py`. The actual endpoint is `/conditional-index-order`.
**Impact**: Users cannot apply or modify GTT orders from the dashboard.

### ### WR-01: Incomplete State-Locked Controls (Warning)
**File**: [index.html](file:///Users/sreekanthmekala/Desktop/TradingAgent/templates/index.html:L1300)
**Description**: While BUY/EXIT buttons are state-locked, the "Apply GTT" buttons remain enabled even when no position is active.
**Impact**: Confusing UI state; allows invalid requests to be sent to the server.

### ### IN-01: Hardcoded Trade Quantity (Info)
**File**: [index.html](file:///Users/sreekanthmekala/Desktop/TradingAgent/templates/index.html:L1417)
**Description**: `sendUIAction` uses a hardcoded `quantity: 1` for all UI-driven trades.
**Impact**: Limits flexibility for users who may want to scale positions.

### ### IN-02: Logic Duplication in server.py (Info)
**File**: [server.py](file:///Users/sreekanthmekala/Desktop/TradingAgent/server.py:L809)
**Description**: There is a duplicated block of code starting at line 809 that appears to be a copy of `_set_conditional_index_orders_internal` following a return statement.
**Impact**: Increased maintenance overhead and potential for confusion.

## Next Steps
1. Align frontend and backend GTT routes.
2. Add `btn-set-call/put` to the `updateUI` state-locking logic.
3. Clean up dead code in `server.py`.
