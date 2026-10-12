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

