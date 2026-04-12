---
status: needs_fix
depth: standard
files_reviewed_list:
  - server.py
  - templates/index.html
---

# Code Review: Phase 4 (Positions Container)

Summary of the code review for the multi-position dashboard implementation.

## Critical Findings
*No critical issues found.*

## Warning Findings
### `server.py`
* **LTP Error Handling**: If `broker.get_ltp()` fails (returns None), the PnL is calculated as 0.0. This could be misleading to the user.
    * **Impact**: UI might flicker between 0 and real PnL if API connection is unstable.
    * **Recommendation**: If LTP is missing, don't update the local `ltp` variable if we have a previous one, or flag as "unavailable".

## Info Findings
### `server.py`
* **Unused Variable**: The `index_ids` dictionary inside `_get_active_positions` is defined but never used since we fetch `security_id` directly from index state.
* **Calculation Precision**: `round(pnl_abs, 2)` is used. Ensure this matches the currency precision requirements (usually it does).

### `templates/index.html`
* **UI Polling**: Polling is at 5s. This is frequent enough, but monitor for network lag on the VPS.
* **GTT Scoping**: The GTT labels (`stat-CALL`, `stat-PUT`) are still strictly NIFTY-linked. This matches the current design but is a technical debt for multi-index GTT management.
