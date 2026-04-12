# Roadmap: TradingAgent

## Milestone 0.1.0: Core Strategy Baseline

### Phase 1: Baseline Strategy & Native Super Orders [COMPLETED]
Goal: Establish the core strategy with market entry and smart "Maker" exit logic.
- [x] Implement `NativeSuperOrder` placement with MARKET entry.
- [x] Implement 55% Target / 20% SL / 10% Trailing Jump logic.
- [x] Integrate Redis for position persistence.
- [x] Set up basic signal handling for 5m timeframe.
**Requirements**: [REQ-01, REQ-02, REQ-03, REQ-05]
**Canonical refs**: [HLD.md](file:///Users/sreekanthmekala/Desktop/TradingAgent/HLD.md), [README.md](file:///Users/sreekanthmekala/Desktop/TradingAgent/README.md)

### Phase 2: Directional Exits & Advanced Logic [COMPLETED]
Goal: Refine exit logic and add multi-timeframe signal support.
- [x] Implement `LONG_EXIT` and `SHORT_EXIT` specific logic.
- [x] Implement dynamic trailing stop loss adjustments for 1m timeframe.
**Requirements**: [REQ-04, REQ-06]

## Milestone 0.2.0: Dashboard & Monitoring

### Phase 3: Web Dashboard & Control Panel [COMPLETED]
Goal: Visual monitoring and manual overrides.
- [x] Build Flask dashboard with position status.
- [x] Add "Emergency Exit" control.
- [x] Integrated Range Tracker API & UI.
**Depends on**: 1, 2

### Phase 4: Positions Container
Goal: Display real-time summary of currently opened positions including PnL and strike details on the dashboard.
- [ ] Implement backend endpoint `/get-positions` or enhance `/get-state`.
- [ ] Build a "Live Positions" container with real-time PnL tracking.
- [ ] Add visual indicators for PnL (Profit/Loss color coding).
**Depends on**: 3
