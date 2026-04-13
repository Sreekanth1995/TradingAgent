# Phase 4 Context: Positions Container

## Goal
Implement a dynamic "Live Positions" dashboard container that replaces the static Position Radar with a real-time list of active trades across NIFTY, BANKNIFTY, and FINNIFTY.

## Technical Architecture
- **Backend**: `server.py` aggregates positions from all major indices.
- **Frontend**: `index.html` uses Glassmorphism-styled cards to display live PnL and LTP.
- **State**: Positions are derived from the broker (Mock or Dhan) and synced via `SuperOrderEngine`.

## Implementation Details
- `_get_active_positions()`: Helper in `server.py` to fetch, calculate, and format position data.
- `MockDhanClient`: Provides jittery price simulation for local dashboard testing.
- `updateUI()`: JavaScript logic to render dynamic cards from the `active_positions` array.
