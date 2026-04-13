# State: TradingAgent

**Milestone**: 0.1.0
**Active Phase**: Phase 8: Improve Dashboard UI and Position Management

## Roadmap Progress
- [x] Phase 1 - 7: Completed
- [/] Phase 8: Improve Dashboard UI and Position Management (Active)

## Active Phase Progress
- [ ] Implement backend state mapping for UI sectors
- [ ] Overhaul index.html with P&L display and button disabling
- [ ] Add Modify GTT logic
- [ ] Remove legacy positions list

## Recent Decisions
- **D-01**: Use Redis as primary state store for reliability. [2026-03-24]
- **D-02**: Prefer Native Super Orders over simulated brackets to reduce latency. [2026-03-24]
- **D-03**: Use MARKET entry for Super Orders for immediate fulfillment. [2026-03-24]
- **D-04**: Use 55% Target / 20% SL baseline for NIFTY options. [2026-03-24]
- **D-05**: Smart Exit uses fixed +5/-5 offsets for modification. [2026-03-24]

## Blockers
- None.
