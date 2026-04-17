# Code Review: Phase 11 — AI-in-the-loop Infrastructure

## Summary
The phase successfully implemented the Server-Sent Events (SSE) infrastructure and refactored the webhook to emit enriched signals. However, several critical security and stability issues were introduced that must be addressed before production use.

## Findings

### 🔴 Critical
#### [Denial of Service] Webhook blocks if queue is full
- **File**: [server.py](file:///Users/sreekanthmekala/Desktop/TradingAgent/server.py#L318)
- **Problem**: `signal_queue.put(leg_data)` is a blocking call because the queue has `maxsize=10`. If no consumer is listening to `/events` and 10 signals arrive, the 11th signal will cause the Flask request to hang indefinitely.
- **Impact**: The entire TradingView webhook integration stops working if the AI listener is offline.
- **Recommendation**: Use `signal_queue.put_nowait(leg_data)` and wrapped in a `try...except queue.Full` block to log an error instead of hanging.

#### [Security] SSE Endpoint is Public
- **File**: [server.py](file:///Users/sreekanthmekala/Desktop/TradingAgent/server.py#L204)
- **Problem**: The `/events` endpoint does not check for the `WEBHOOK_SECRET`. 
- **Impact**: Any unauthorized third party can connect to `http://IP/events` and receive real-time trading signals, including sensitive instrument IDs and spot prices.
- **Recommendation**: Add a check for `request.args.get('secret') == SECRET`.

#### [Security] Last Signal Endpoint is Public
- **File**: [server.py](file:///Users/sreekanthmekala/Desktop/TradingAgent/server.py#L211)
- **Problem**: The `/last-signal` endpoint does not check for the `WEBHOOK_SECRET`.
- **Impact**: Unauthorized retrieval of the last trading context.
- **Recommendation**: Add a check for `request.args.get('secret') == SECRET`.

### 🟡 Moderate
#### [Architectural] Multiple Listener Race Condition
- **File**: [server.py](file:///Users/sreekanthmekala/Desktop/TradingAgent/server.py#L201)
- **Problem**: `signal_queue.get()` removes the item from the queue. If two clients connect to `/events`, they will compete for events. Client A might get signal 1, and Client B might get signal 2.
- **Impact**: Inconsistent notifications if debugging or running multiple AI bridges.
- **Recommendation**: For a single-user system, this is acceptable but should be documented. For multi-user, use a list of subscriber queues and push to all of them.

### 🟢 Minor
#### [Quality] Inconsistent Indentation
- **File**: [server.py](file:///Users/sreekanthmekala/Desktop/TradingAgent/server.py#L182-195)
- **Problem**: The `health()` function has slightly inconsistent indentation in the `status` dictionary definition after recent edits.

## Next Steps
- [ ] Implement security secret checks on `/events` and `/last-signal`.
- [ ] Fix blocking `put()` in the webhook logic.
- [ ] (Optional) Refactor SSE to support multiple concurrent listeners.
