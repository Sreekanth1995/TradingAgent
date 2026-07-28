# State: TradingAgent

**Milestone**: 0.2.0
**Active Phase**: Milestone Complete (Awaiting next version requirements)

## Roadmap Progress
- [x] Phase 1 - 12: Completed
- [ ] Next: Milestone 0.3.0 (Planning)

## Recent Decisions
- **D-01**: Use Redis as primary state store for reliability. [2026-03-24]
- **D-02**: Prefer Native Super Orders over simulated brackets to reduce latency. [2026-03-24]
- **D-03**: Use MARKET entry for Super Orders for immediate fulfillment. [2026-03-24]
- **D-04**: Use 55% Target / 20% SL baseline for NIFTY options. [2026-03-24]
- **D-05**: Smart Exit uses fixed +5/-5 offsets for modification. [2026-03-24]
- **D-06**: Phase 9 strictly narrowed to LTP Exposure Strategy via dedicated tool. [2026-04-14]
- **D-07**: Phase 10 implements Intraday-focused margin and fund balance tracking. [2026-04-14]
- **D-08**: Phase 11 implements AI-in-the-Loop SSE streaming logic. [2026-07-28]
- **D-09**: Milestone 0.2.0 focuses on strategy expansion. [2026-07-28]

## Blockers
- None.
