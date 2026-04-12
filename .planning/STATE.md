# State: TradingAgent

**Milestone**: 0.1.0
**Active- Phase 1: Baseline Strategy (Completed)
- Phase 2: Directional Exits & Advanced Logic (Completed)
- Phase 3: Web Dashboard (Completed)
- Phase 4: Positions Container (Active)
Ready for Phase 4 implementation.

## Active Phase Progress
- [ ] Implement backend endpoint `/get-positions` or enhance `/get-state`. [TODO]
- [ ] Build a "Live Positions" container with real-time PnL tracking. [TODO]
- [ ] Add visual indicators for PnL (Profit/Loss color coding). [TODO]

## Recent Decisions
- **D-01**: Use Redis as primary state store for reliability. [2026-03-24]
- **D-02**: Prefer Native Super Orders over simulated brackets to reduce latency. [2026-03-24]
- **D-03**: Use MARKET entry for Super Orders for immediate fulfillment. [2026-03-24]
- **D-04**: Use 55% Target / 20% SL baseline for NIFTY options. [2026-03-24]
- **D-05**: Smart Exit uses fixed +5/-5 offsets for modification. [2026-03-24]

## Blockers
- None.
