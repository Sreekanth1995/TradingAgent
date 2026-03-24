# State: TradingAgent

**Milestone**: 0.1.0
**Active Phase**: Phase 2: Directional Exits & Advanced Logic
**Status**: Phase 1 VERIFIED. Ready for Phase 2 implementation.

## Active Phase Progress
- [ ] Implement `LONG_EXIT` and `SHORT_EXIT` specific logic. [TODO]
- [ ] Implement dynamic trailing stop loss adjustments for 1m timeframe. [TODO]

## Recent Decisions
- **D-01**: Use Redis as primary state store for reliability. [2026-03-24]
- **D-02**: Prefer Native Super Orders over simulated brackets to reduce latency. [2026-03-24]
- **D-03**: Use MARKET entry for Super Orders for immediate fulfillment. [2026-03-24]
- **D-04**: Use 55% Target / 20% SL baseline for NIFTY options. [2026-03-24]
- **D-05**: Smart Exit uses fixed +5/-5 offsets for modification. [2026-03-24]

## Blockers
- None.
