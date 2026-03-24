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

### Phase 3: Web Dashboard & Control Panel
Goal: Visual monitoring and manual overrides.
- [ ] Build Flask dashboard with position status.
- [ ] Add "Toggle Side" and "Emergency Exit" controls.
