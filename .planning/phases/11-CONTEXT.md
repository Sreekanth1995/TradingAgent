# Phase 11: AI-in-the-Loop Architecture (Final Decisions)

Current Situation: `/webhook` receives a signal and immediately executes a trade using static or engine-calculated parameters.
Target Situation: `/webhook` receives a signal, enrichment (ITM/LTP) is performed, an SSE event is emitted, and an AI (Claude via MCP) interprets the signal to decide on the trade execution.

## Decisions

### 1. SSE Consumer
The SSE stream will be consumed by Claude (connected via an MCP bridge). This allows the AI to receive real-time signals and trigger execution tools.

### 2. Signal Enrichment
The `/webhook` endpoint **MUST** resolve the **ITM Option Contract** and **Index LTP** before emitting the SSE event. This ensures that the AI receives a "Ready-to-Trade" context without needing to reach back into the server for basic instrument data.

### 3. Webhook Synchronicity
The `/webhook` endpoint will return a **"200 Received"** response immediately after the SSE event is emitted. This prevents TradingView webhook timeouts.

### 4. Fallback Mechanism (Conservative)
If the AI (via MCP) does not place an order within a timeframe after a signal is emitted, the system will **DO NOTHING**. There is no automatic fallback to static logic once AI-in-the-loop is active.

### 5. Execution Path
The AI will call existing MCP tools (like `place_super_order` or `place_conditional_order`) after analyzing the signal. No new "Decision" endpoint is required at this stage.

## Technical Implementation Details

- **Event Type**: `signal`
- **Payload**: JSON containing `underlying`, `transaction_type`, `itm_ce`, `itm_pe`, `spot_index`, and `timeframe`.
- **Infrastructure**: Thread-safe `Queue` in Flask to manage SSE event distribution.
