# Roadmap: TradingAgent

## Milestone 0.1.0: Live Trading Foundation

- [x] Phase 1: Baseline Strategy
- [x] Phase 2: Directional Exits & Advanced Logic
- [x] Phase 3: Web Dashboard
- [x] Phase 4: Positions Container
- [x] Phase 5: UI Performance History
- [x] Phase 6: MCP Integration
- [x] Phase 7: Advanced Conditional Orders
- [x] Phase 8: Improve Dashboard UI and Position Management
    - **Goal**: State-aware dashboard with integrated P&L and GTT cleanup.
    - **Depends on**: Phase 7
- [x] Phase 9: Targeted LTP Exposure Tool
    - **Goal**: Implement dedicated /get-ltp endpoint and MCP tool for targeted price checks.
    - **Depends on**: Phase 6
- [x] Phase 10: Implement Margin and Fund APIs
    - **Goal**: Implement Dhan margin calculation and fund limit retrieval endpoints and expose them to Claude via MCP.
    - **Depends on**: Phase 6
- [x] Phase 11: AI-in-the-Loop Architecture
    - **Goal**: Emits index LTP/ITM options via SSE, consumed by Claude via MCP to decide execution.
    - **Depends on**: Phase 6

## Milestone 0.2.0: Multi-Strategy Expansion

- [x] Phase 12: Third Strategy Implementation
    - **Goal**: Implement a 3rd strategy based on QQE, Q-Trend, and Renko Candles/Bjorgum Key Levels.
    - **Depends on**: Phase 11

### Phase 12: Third Strategy Implementation

**Goal:** Integrate QQE, Q-Trend, and Renko/Bjorgum indicators into a 3rd unified strategy.
**Requirements**: TBD
**Depends on:** Phase 11
**Plans:** 0 plans

Plans:
- [x] TBD (run /gsd-plan-phase 12 to break down)

## Milestone 0.3.0: Modular Broker Architecture (Dedicated Services Decoupling)

- [x] Phase 13: Service Contracts & Backwards-Compatible Facade
    - **Goal**: Define clean protocols/interfaces for broker operations and convert `DhanClient` into a Facade that delegates without breaking existing callers (`server.py`, `SuperOrderEngine`, etc.).
    - **Depends on**: Phase 12
- [x] Phase 14: Market Data, Instrument & Auth Service Decomposition
    - **Goal**: Extract `DhanAuthService`, `DhanMarketDataService` (with cache/fallbacks), and `DhanInstrumentService` (offline-loadable scrip master).
    - **Depends on**: Phase 13
- [x] Phase 15: Order Execution & GTT Conditional Services
    - **Goal**: Extract `DhanOrderService` (Super & standard orders) and `DhanConditionalOrderService` (GTT legs and triggers).
    - **Depends on**: Phase 14
- [x] Phase 16: Safety, Realtime Updates & Mock Harmonization
    - **Goal**: Extract `DhanSafetyService` (kill switch, reconciliation, operator alarms), `DhanSocketService`, and update `MockDhanClient` to verify zero-regression offline test runs.
    - **Depends on**: Phase 15

## Milestone 0.4.0: Critical Safety Hardening & Autonomous Reconciliation

- [x] Phase 17: Zero-Downtime Atomic Scrip Reload & Lot Map Guard
    - **Goal**: Replace in-place scrip dictionary clearing with atomic swap, serialized lock on `/reload-scrip`, and fail-closed lot size validation.
    - **Depends on**: Phase 16
- [x] Phase 18: Kill Switch Super Order Leg Cancellation
    - **Goal**: Cancel Super Order bracket legs (`TARGET_LEG`, `STOP_LOSS_LEG`) explicitly via `/super/orders/{id}/{leg}` before flattening open positions to prevent orphan naked shorts.
    - **Depends on**: Phase 17
- [x] Phase 19: Approach C Autonomous Reconciliation Safety Net
    - **Goal**: Implement redundant positions polling in `ConditionalOrderEngine` for filled-but-unprotected orders with idempotent bracket arming and fail-closed alarms.
    - **Depends on**: Phase 18

