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
