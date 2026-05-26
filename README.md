# NIFTY Options Trading Bot Strategy

This document outlines the **Direct Signal Strategy** implemented for the NIFTY Options Trading Bot. The system leverages Dhan's Native Super Order (Bracket Order) API with "Smart" entry and exit logic to capture spread and reduce slippage.

## 1. Core Logic
-   **Underlying**: NIFTY 50 Index.
-   **Signal Source**: Webhook Alerts (TradingView).
-   **Instrument**: In-The-Money (ITM) Call/Put Option (Next Expiry).
-   **Execution Mode**: **Native Super Order** (Bracket Order via Dhan API v2).

## 2. Smart Entry Strategy
When a **BUY (Call)** or **SELL (Put)** signal is received:
1.  **LTP Fetch**: The bot fetches the real-time Last Traded Price (LTP) of the selected Option.
2.  **ITM Selection**:
    -   **Call (Buy)**: ATM Strike - 50 points.
    -   **Put (Sell)**: ATM Strike + 50 points.
*   **Entry Strategy**: Market Order for immediate execution.
*   **Target Profit**: **55%** (Limit leg via Native Super Order).
*   **Stop Loss**: **20%** (Trigger/Limit leg via Native Super Order).
*   **Trailing Stop Loss**: **10%** (Automatic via Native Super Order).
*   **Smart Exit**: In case of trend reversal, entry legs are cancelled, and exit legs are modified to `LTP + 5` (Target) or `LTP - 5` (SL) to capture "Maker" fills.

### 3. Smart Exit (Reversal Handling)
If a signal reverses (e.g., LONG -> SHORT) while a position is active:
1.  Cancel any unfilled Entry Legs.
2.  Modify the active Exit Legs (Target/SL) to work the EXIT at `LTP + 5` or `LTP - 5`.

## 4. Reversal Entry
-   Immediately after handling the exit Modification/Cancellation, the bot triggers the **Smart Entry** logic for the **New Position** (e.g., Short/Put).
-   This results in a temporary "Hedged" state where the old position works its limit exit while the new position seeks its limit entry.

## 4b. Per-Underlying Market-Feeling Trade Gate
The bot accepts an explicit directional bias per underlying (NIFTY / BANKNIFTY / FINNIFTY) that hard-blocks contra-bias **entries** at both the HTTP route and the engine. Exits are never blocked.

| feeling   | CALL entry | PUT entry |
|-----------|------------|-----------|
| `Bullish` | allow      | block     |
| `Bearish` | block      | allow     |
| `Inside`  | block      | block     |
| `null`    | allow      | allow     |

-   **Surfaces**:
    -   `POST /set-feeling` and `POST /get-feeling` (payload `{secret, underlying, value}`; `value` accepts `Bullish` / `Bearish` / `Inside` / `null` to clear).
    -   MCP tools `set_feeling(underlying, value)` and `get_feeling(underlying=None)` (see `docs/MCP_SETUP.md`).
    -   `/health` exposes `feelings_store ∈ {"ok","unreadable"}`.
-   **Storage**: `feelings.json` next to `server.py`, written atomically (`atomic_json.write_json` → `os.replace`). A torn write from a crash is impossible; the file is either the previous version or the new one.
-   **Fail-closed reads**: a corrupt or permission-denied `feelings.json` puts the store into `unreadable`. While unreadable, every entry returns HTTP 200 `status=skipped_by_feeling_unreadable` with `recovery: "delete feelings.json (no restart needed)"`. Missing file is NOT unreadable — it's the fresh-install default (`allow all`).
-   **Blocked entries** return HTTP 200 with `status=skipped_by_feeling`, a `reason`, and write a `SKIPPED` row into `trade_feed` plus an activity-log line. They do NOT update `last_signal_storage` or stream over SSE, so vetoed signals stay invisible to Claude (AI mode).
-   **Pending warnings**: setting a feeling that contradicts an armed-but-unfilled conditional entry (`PENDING_CALL` / `PENDING_PUT`) returns a `warnings[]` entry. Auto-cancel is deliberately NOT performed; the operator chooses whether to call `cancel_conditional_order`.
-   **Defense in depth**: both engines (`super_order_engine`, `conditional_order_engine`) re-run the gate using `FeelingState.decide_for_entry()` — a single atomic read, no TOCTOU window between the unreadable preflight and the per-underlying lookup. Invalid side fails CLOSED.

## 4a. Conditional Index-Touch Entry (per-underlying)
The `/conditional-order` endpoint (and the `place_conditional_order` MCP tool) accepts an optional `entry_index` field. When present, the bot does NOT buy immediately; it arms a broker-native conditional BUY that fires only when the underlying index touches `entry_index`.
-   **Trigger direction is auto-derived**: entry above spot fires on the way up (`ABOVE`), below spot on the way down (`BELOW`).
-   **Strike is pre-computed from the entry level**, not current spot, so the contract still ends up ITM at fire time.
-   **SL/Target are validated against the entry level** and arm later, on the entry fill (linked by an `ENTRY:{underlying}:{uuid}` correlation id because the alert-fired order gets a brand-new broker `orderId`).
-   **State**: armed-but-unfilled entries live in `PENDING_CALL` / `PENDING_PUT`. An opposite signal cancels the armed entry; a same-direction signal is rejected.
-   **EOD flush**: the monitor loop calls `flush_pending_entries()` at/after 15:30 IST so a stale alert can't fire on a later day against a now-wrong pre-computed strike.

## 5. Fail-Safe & Fallbacks
-   **Fallback Execution**: If Native Super Order placement fails (e.g., API issue), the system falls back to a **Simulated Bracket** (Market Entry + separate Exit Orders).
-   **Position Verification**: Before modifying/closing, the bot verifies `net_qty` via Dhan API to ensure valid state.
-   **LTP Safety**: If LTP cannot be fetched, Smart Logic is upgraded to Standard Execution (Market Orders) to ensure trade completion.

## 6. Configuration
-   **Target Points**: 30
-   **SL Points**: 20
-   **Trailing Jump**: 10
-   **Smart Entry Edge**: -5 (from LTP)
-   **Smart Exit Edge**: +5 (from LTP)
-   **Smart SL Trail**: -10 (from LTP)

## 7. Low Level Design & Architecture

### A. Component Logic (`super_order_engine.py`)
The system operates as a **State Machine** driven by incoming signals:
1.  **Input**: Webhook Signal (`BUY` / `SELL`, Symbol `NIFTY`).
2.  **State Check**: Reads current state (`CALL`, `PUT`, or `NONE`) from Storage.
3.  **Decision Engine**:
    -   **Same Signal**: Ignored (Deduplication).
    -   **New Signal**: Trigger Entry (`_open_position`).
    -   **Reversal**: Trigger Exit (`_close_position`) -> Trigger Entry.

### B. Data Storage (Redis)
State persistence is critical to survive restarts/crashes.
-   **Primary Store**: Redis (Key-Value).
-   **Keys**:
    -   `dhan_access_token`: Cached Auth Token.
    -   `strategy_state:{Underlying}`: JSON object containing:
        -   `side`: 'CALL' / 'PUT'
        -   `entry_id`: Parent Order ID
        -   `quantity`: Position Size
-   **Fallback**: In-Memory Dictionary (Non-persistent).

### C. Order Flow Details

#### 1. Entry Flow (Smart Limit)
1.  **Signal Received**.
2.  **Broker**: `get_itm_contract` (Spot -> ATM +/- 50).
3.  **Broker**: `get_ltp` (Live Price).
4.  **Action**: `place_super_order` (API v2).
    -   Type: LIMIT
    -   Price: `LTP - 5`
    -   Payload includes `targetPrice` and `stopLossPrice`.
5.  **State Update**: Store `entry_id` in Redis.

#### 2. Reversal Flow
1.  **Signal Received** (e.g., Short Signal while Long).
2.  **Cleanup (Unfilled)**:
    -   Check for pending **BUY** orders (Stale Entry).
    -   **CANCEL** immediately if found.
3.  **Smart Exit (Filled)**:
    -   Fetch pending **SELL** orders (Target/SL).
    -   **Modify Target**: Set to `LTP + 5` (Limit).
    -   **Modify SL**: Set to `LTP - 10` (Limit).
    -   *Position is effectively left to close itself.*
4.  **New Entry**:
    -   Execute **Entry Flow** for the new direction (Put).

