# Phase 08: Dashboard UI & Position Management Overhaul

## Overview
This phase enhances the dashboard to be fully state-aware. It simplifies the layout by removing redundant containers and providing live P&L data directly within the instrument control sectors. It also adds safety logic to prevent invalid orders and implements a "Modify GTT" flow.

## Key Goals
1. **Integrated Display**: Remove "Live Positions" section; show P&L directly in CALL/PUT cards.
2. **State-Locked Controls**: Disable BUY button if position is active; Enable EXIT only if active.
3. **Safety Enforcement**: Validation for SL/Target indices before allowing a BUY.
4. **Resilient GTT Management**: "Modify GTT" button and automatic cleanup on EXIT.

## Logic Flow
- `refreshState()` polls `/get-state`.
- `updateUI(data)` calculates the status of each sector.
- Buttons are disabled/enabled using CSS classes.
- P&L is rendered dynamically.
