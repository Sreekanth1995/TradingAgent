# Phase 7: Advanced Conditional Orders - Context

## Decisions

### 1. Hybrid Implementation
We will maintain and distinguish between two types of automated protection:
- **Premium-based Super Orders**: Targets specific Option Premium prices (e.g., Entry 160, SL 140, TGT 240).
- **Index-based Conditional Orders (GTT)**: Targets underlying Index levels (e.g., NIFTY 23450).

### 2. Mandatory Parameters
- **Stop Loss (SL)** and **Target** are now **MANDATORY** for all entry signals (BUY CALL / BUY PUT).
- If these parameters are missing from a TradingView signal or manual request, the trade will be rejected (Fail-Safe).
- This applies to both the Dashboard UI and MCP tools.

### 3. Order Expiry
- All **Index-based Conditional Orders (GTT)** will be configured to expire at the end of the current trading day.

### 4. Technical Specifications
- **Separate Endpoints**:
    - `/super-order`: Dedicated to premium-based bracket orders.
    - `/conditional-index-order`: Dedicated to index-level-based GTT triggers.
- **Quantity Support**: Both endpoints must accept an explicit `quantity` parameter (representing lots).
- **UI Integration**: The Live Positions container on the dashboard must reflect the current "Index Level" triggers if they are set/updated.
- **Error Feedback**: API responses must include descriptive error messages to allow Claude (via MCP) to intelligently retry on failure.

### 5. Editing Capabilities
- Users (and AI) must be able to **edit** active SL/Target levels for open positions. For GTTs, this will involve updating existing alerts on Dhan.

## Canonical Refs
- [broker_dhan.py](file:///Users/sreekanthmekala/Desktop/TradingAgent/broker_dhan.py) (Base implementation for GTT/Super Orders)
- [server.py](file:///Users/sreekanthmekala/Desktop/TradingAgent/server.py) (Endpoint definitions and session state)
- DhanHQ API: Forever Orders (GTT) & Super Orders logic.
