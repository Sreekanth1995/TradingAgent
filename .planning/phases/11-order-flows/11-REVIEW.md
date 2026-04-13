# Phase 11 Code Review: MCP Parallel Order Flows & Interlock Analysis
**Date**: 2026-04-14
**Reviewed Files**:
- `mcp_server.py`
- `server.py`
- `super_order_engine.py`

## Observations & Findings

### 1. `update_super_order` method is missing
- **Finding**: While `broker_dhan.py` provides `modify_super_target_leg` and `modify_super_sl_leg`, there is no `update_super_order` route in `server.py` nor a corresponding tool in `mcp_server.py`. The AI cannot dynamically manage the parameters of an ongoing super order.

### 2. `place_conditional_order` routes to `/ui-signal`
- **Finding**: In Phase 10, `place_manual_order` was renamed to `place_conditional_order`. However, keeping its payload routed to `/ui-signal` means it triggers `engine.handle_signal()` -> `_execute_signal()`. This is configured as a primary entry signal, which by default executes a **Native Super Order Bracket**! If the intent of `place_conditional_order` was purely to deploy GTT Conditional Triggers, routing to `/ui-signal` fundamentally violates separation of concerns.

### 3. Parallel Tracking of Super & Conditional Orders
- **Finding**: If an AI places a Super Order (Premium SL/Target), and simultaneously places a Conditional Order (Index SL/Target GTT), both orders run alongside each other against the same underlying position. 
- **Risk**: They both place eventual `SELL` (exit) triggers.

### 4. Interlocking & Conflict Risks
- **Finding**: The major "interlocking" risk happens when one parallel flow executes before the other:
  - **Scenario A**: The Super Order Premium SL is hit. Dhan closes the position and cancels the Target leg. However, the Conditional GTT triggers (Index bounds) are still active on Dhan's server! If the index later hits the bound, the GTT will fire a rogue `SELL`, initiating a naked short position.
  - **Scenario B**: The Conditional GTT executes its market `SELL` because the Index boundary was hit. Dhan executes the trade. However, the Super Order Premium limits are still stuck in `PENDING` state on the Dhan orderbook. If the price swings back, the Super Order leg might execute another naked short.
- **Locking Risk (Threads)**: `engine.process_signal` uses `self.processing_locks`. If MCP tools push updates at the exact millisecond a webhook fires, one will drop as `SKIPPED_LOCKED`. This is generally safe but can cause ignored AI commands.

## Recommendations
1. **Expose Update Endpoint**: Build `/update-super-order` in `server.py` to route to broker leg modifier methods, and expose `update_super_order` in MCP.
2. **Decouple Conditional endpoints**: Remove `/ui-signal` routing from conditional tools. MCP should separate entries (`place_super_order`, `place_manual_entry`) from condition placement (`place_conditional_order` -> `/conditional-index-order`).
3. **State Syncing**: Implement a cleanup routine or require the AI to explicitly use a cancellation sequence to prevent rogue double-sells when parallel flows resolve.
