# Phase 01: Baseline Strategy - Context

**Gathered:** 2026-03-24
**Status:** Ready for planning

<domain>
## Phase Boundary
Deliver the baseline trading strategy:
- Entry at market price.
- Target = 55%, SL = 20%, Trailing = 10%.
- Smart Reversal Exit: Cancel pending, modify active (Target +5, SL -5).
- No time-based scalping windows.
</domain>

<decisions>
## Implementation Decisions

### Order Execution
- **D-01**: Entry orders MUST be executed at MARKET or LIMIT at LTP to ensure immediate fill.
- **D-02**: Use Dhan Native Super Orders (Bracket Orders) for all entries.

### Exit Strategy
- **D-03**: Targets are set at 55% above entry.
- **D-04**: Stop Loss is set at 20% below entry.
- **D-05**: Trailing Jump is set at 10% of entry price.
- **D-06**: In case of a reversal signal (BUY -> SELL or vice versa), modify the active SELL legs:
    - Target: `LTP + 5`
    - Stop Loss: `LTP - 5`

### Logic Refinement
- **D-07**: Scalping mode is no longer time-restricted. All 1m/5m signals use the same baseline targets (for now) or slightly tighter ones if specified later, but the time windows are removed.

### the agent's Discretion
- Redis key structure: use `trading_side:{underlying}` and `active_contract:{underlying}`.
</decisions>

<canonical_refs>
## Canonical References
- [HLD.md](file:///Users/sreekanthmekala/Desktop/TradingAgent/HLD.md)
- [README.md](file:///Users/sreekanthmekala/Desktop/TradingAgent/README.md)
</canonical_refs>

---
*Phase: 01-baseline*
