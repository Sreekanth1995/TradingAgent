# Phase 2 Context: Directional Exits

Implementation decisions for directional exit signals.

## Decisions

### 1. Signal Triggers
- `LONG_EXIT`: Triggers the closure of an active CALL position.
- `SHORT_EXIT`: Triggers the closure of an active PUT position.
- **Standalone**: Signals will arrive as individual webhook payloads from TradingView.

### 2. Exit Execution
- **Type**: Immediate **MARKET** exit.
- **Method**: For Super Orders, this means `cancel_super_order` (full cancellation which converts to market or just cancels the legs if already filled).
- **Wait**: Actually, for Dhan Super Orders, if the entry is already filled, cancelling the Super Order cancels the Target and SL legs. To exit the position itself, we must place a Market order for the same quantity.

### 3. Validation Logic
- **Ignore Missing**: If `LONG_EXIT` arrives but `side != 'CALL'`, the engine must ignore the signal and log a warning. Same for `SHORT_EXIT` and `PUT`.

### 4. Pine Script Improvements
- Update `LongPosition.pine` to emit `LONG_EXIT` and `SHORT_EXIT` alert messages.
