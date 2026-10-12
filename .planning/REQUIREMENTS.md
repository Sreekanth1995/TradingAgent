# Requirements: TradingAgent

## REQ-01: Market Price Entry
-   **Description**: Entry should be placed at current market price for immediate fill.
-   **Acceptance**: Order placed is a MARKET order or LIMIT order at LTP.

## REQ-02: Native Super Order Integration
-   **Description**: Use Dhan API v2 `place_super_order` (Bracket Order).
-   **Acceptance**: Single API call creates Entry, Target, and Stop Loss legs.

## REQ-03: Stateful Position Tracking
-   **Description**: Use Redis to store `trading_side`, `entry_id`, and `active_contract`.
-   **Acceptance**: System resumes correct state after restart.

## REQ-04: Smart Reversal Exit
-   **Description**: On signal reversal, modify existing Target/SL legs to "work" the exit instead of market closure. Target = `LTP + 5`, SL = `LTP - 5`.
-   **Acceptance**: Leg modification calls successful; price offsets applied as +5/-5.

## REQ-05: Dynamic Instrument Selection
-   **Description**: Map NIFTY Spot to nearest ITM Call/Put based on current LTP.
-   **Acceptance**: Correct strike selected (+/- 50 for NIFTY).

## REQ-06: Dynamic Trailing Stop Loss
-   **Description**: Support different trailing stop loss offsets based on the signal timeframe (e.g., tighter trailing for 1m vs 5m).
-   **Acceptance**: Signals with `timeframe=1` use the `scalping_configs` trailing value.

## REQ-07: Broker Service Decomposition
-   **Description**: Decompose monolithic `DhanClient` into single-responsibility services (`DhanAuthService`, `DhanMarketDataService`, `DhanInstrumentService`, `DhanOrderService`, `DhanConditionalOrderService`, `DhanSafetyService`, `DhanSocketService`).
-   **Acceptance**: Each service handles a single domain with clear dependency injection; cross-service coupling is eliminated.

## REQ-08: Zero-Regression DhanClient Facade
-   **Description**: Maintain `DhanClient` as a lightweight Facade that preserves all existing method signatures and delegates to the dedicated services.
-   **Acceptance**: Callers like `server.py`, `SuperOrderEngine`, `ConditionalOrderEngine`, and MCP tools continue to work without modifying their invocation code.

## REQ-09: No-Network Offline Testability
-   **Description**: Broker services (especially instrument/scrip resolver and market data) must support constructor configuration that prevents live network requests or background thread creation during testing.
-   **Acceptance**: `pytest tests/` runs 100% offline without hitting live Dhan API endpoints or background daemon download threads.

## REQ-10: Isolated Realtime & Safety Boundaries
-   **Description**: Real-time WebSocket connection handling and emergency safety (Kill Switch, position reconciliation, Slack alarms) must be isolated into dedicated services that cannot block order execution threads.
-   **Acceptance**: WebSocket reconnects and alarm posting execute asynchronously without contending with synchronous order placement calls.

## REQ-11: Zero-Downtime Atomic Scrip Reloading
-   **Description**: Scrip reloads must build maps into local dictionaries first and atomically swap active pointers (`scrip_map`, `lot_map`, `exact_symbol_map`) only upon complete parse success. Concurrent reloads must be serialized with a lock. Order placement must fail-closed if `lot_size` is missing or 0 instead of defaulting silently to 1.
-   **Acceptance**: Incoming orders during a scrip reload never observe empty maps or get defaulted to unit quantity.

## REQ-12: Kill Switch Super Order Leg Cancellation
-   **Description**: Emergency kill switch must detect Super Order brackets and cancel their pending target and SL legs using the `/super/orders/{id}/{leg}` endpoint before liquidating open positions.
-   **Acceptance**: No orphaned Super Order bracket legs remain alive after executing a kill switch, preventing subsequent naked short triggers.

## REQ-13: Approach C Autonomous Reconciliation Safety Net
-   **Description**: Background position monitor must detect filled conditional entries whose webhook postbacks were missed or delayed, validate lot sizes, idempotently arm bracket protections, and fire high-priority alarms (`🚨`) for unprotectable positions.
-   **Acceptance**: A conditional order filled without a postback is automatically armed with SL/Target within the reconciliation polling cycle without double-arming.

