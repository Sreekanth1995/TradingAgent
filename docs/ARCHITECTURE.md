# TradingAgent System Architecture

This document describes the existing implementation of the TradingAgent project as of the latest deployments. The system is a hybrid algorithmic and manual trading interface connected natively to the Dhan brokerage via API v2.

---

## 1. High-Level Architecture
The system follows a fundamentally decoupled, state-driven architecture, designed to act on both automated webhook signals (e.g., from TradingView) and manual UI inputs.

At its core, the project is divided into three primary execution layers:
1. **The Web/UI Layer (`server.py`, `index.html`)**: A Flask-based web server that provides a real-time dashboard visualizing active PnL, trend levels, and current order boundaries.
2. **The Execution Engines**: Segregated business logic dealing with placing trades and managing risk boundaries.
3. **The Broker Layer (`broker_dhan.py`)**: The adapter that directly interfaces with the Dhan API for placing orders, fetching LTP, and validating margins.

---

## 2. Order Execution Engines
The system safely segregates order structures into distinct managers to prevent logical entanglement during fast-moving markets.

### Conditional Order Engine (`conditional_order_engine.py`)
Handles **Index-Based logic** (NIFTY/BANKNIFTY Spot levels) and Naked Options Entries.
- **Dynamic Entry**: Routes manual UI signals (like `/ui-signal`) to trigger Market/"Naked" Buy/Sell entries. 
- **Conditional Index-Touch Entry**: When the `/conditional-order` endpoint is called with an `entry_index` value, the BUY is armed as a broker-native conditional alert and fires only when the index touches `entry_index`. State enters `PENDING_CALL` / `PENDING_PUT`; SL/Target arm on the entry fill, linked by an `ENTRY:{underlying}:{uuid}` correlation id (userNote) because the alert-fired order receives a fresh broker `orderId`. `cancel_pending_entry()` handles the cancel-vs-fill race (cancel failure leaves `PENDING_*` state intact so an in-flight fill postback can still arm the bracket). `flush_pending_entries()` is called by the monitor loop at/after 15:30 IST so a stale alert can't fire against a now-wrong pre-computed strike on a later session.
- **Deferred Boundary Placement**: Delays placing protective Stop Loss or Target bounds until the Dhan broker confirms the parent entry is firmly *TRADED* via webhooks (`handle_postback()`).
- **GTT Protection**: Protective bounds managed by this engine are placed as remote GTT (Good-Till-Triggered) OCO (One-Cancels-Other) structures linked explicitly to underlying index prices. Entry, SL, and Target legs all use `OPTIONS_PRODUCT_TYPE` from `constants.py` (currently `INTRADAY`) so the exit SELL nets the live long instead of opening a new short.

### Super Order Engine (`super_order_engine.py`)
Handles **Premium-Based logic** (Option Contract Pricing).
- **Native Bracket Orders**: Submits trades using Dhan's native Super Order bracket topology, placing the entry, target, and trailing stop-loss as a singular atomic transaction directly onto the broker.
- **Smart Exit logic**: When a reversal signal arrives, it automatically modifies open trailing SL/Target legs to aggressive near-LTP prices to "smartly" close out the position before pivoting to a new entry.

---

## 3. Dashboard and UI Management
The live dashboard (`templates/index.html`) is a completely dynamic, React-like JS frontend operating without full-page reloads.

- **Unified State Merging**: The backend `_get_active_positions()` fetches internal states from both the `conditional` and `super` engines. It intelligently merges them to dictate whether a Call/Put sector is "ACTIVE" or not.
- **Dynamic Context Rendering**: The UI automatically updates its panel headers depending on the routing type:
  - `"Index Conditional GTT"`: Shown when index bounds are active.
  - `"Super Order Bracket"`: Shown when native premium bounds are active.
  - `"Order Protections (PENDING)"`: Displayed while the system waits to confirm trade entries before opening protections.
- **Safety Interlocks**: Disables explicit Buy/Sell triggers aggressively if a valid open side (`CALL` or `PUT`) is already mapped in either engine state, preventing fatal duplicate orders.

---

## 4. MCP Server Integration (`mcp_server.py`)
A Model Context Protocol (MCP) server runs alongside the main system to provide Claude/AI integration tools. It equips the AI with secure execution authority.
**Capabilities exposed to AI:**
- Reading margin limits and funds (`get_margin_calculator`, `get_fund_limits`).
- Cancelling and Setting GTT conditional bounds programmatically (`set_conditional_bounds`, `cancel_conditional_bounds`).
- Checking unified aggregated trade status (`get_trading_status`), exposing boundary parameters such as `idx_target_level`, `idx_sl_level`, `tgt_price`, and `sl_price`.
- Placing conditional (index-triggered) orders. `place_conditional_order` accepts an optional `entry_index` parameter: omit it for an immediate market entry, or pass an index level to defer the BUY until the index touches that level (operator direction auto-derived from spot).

### Per-Underlying Feeling Gate (`feeling_gate.py`, `atomic_json.py`)
A route-and-engine trade gate that hard-blocks contra-bias **entries** for NIFTY / BANKNIFTY / FINNIFTY. Exits and cancels bypass the gate by design.
- **Surfaces**: HTTP `POST /set-feeling`, `POST /get-feeling`, the MCP tools `set_feeling` / `get_feeling`, and a `feelings_store ∈ {ok,unreadable}` field on `/health`.
- **Decision function**: `feeling_gate(side, feeling)` is pure — 8 cases (`Bullish×{CALL,PUT}`, `Bearish×{CALL,PUT}`, `Inside×{CALL,PUT}`, `None×{CALL,PUT}`).
- **State storage**: `FeelingState` wraps `feelings.json` next to `server.py`. Writes go through `atomic_json.write_json` (tmp file + `os.replace`) so a mid-write crash leaves either the prior or the new version, never a torn JSON. A `threading.Lock` serializes concurrent setters.
- **Fail-closed reads**: `atomic_json.read_json` returns one of `{ok, missing, corrupt, denied}`. Missing means "fresh install → allow all"; corrupt/denied flips the store into `unreadable` and every entry returns `skipped_by_feeling_unreadable` until the operator deletes the file (no restart required because `_load()` reads fresh on every call).
- **Single-read decision**: `FeelingState.decide_for_entry(underlying, side)` folds the unreadable preflight and the per-underlying lookup into ONE atomic disk read — closes a TOCTOU window where the store could go corrupt between two separate reads and silently fail OPEN.
- **Defense in depth**: the route layer is the primary gate (`server._feeling_block_for_entry` runs before spot resolution and dedup, in `/webhook`, `/conditional-order`, and `/super-order`). Both engines re-check using `decide_for_entry()` so a new caller that bypasses the route still fail-closes. Invalid side fails CLOSED — a typo never silently disables the guard.
- **Pending-entry warnings**: setting a feeling that contradicts an armed `PENDING_CALL` / `PENDING_PUT` returns `warnings[]` but does NOT auto-cancel; the operator decides whether to call `cancel_conditional_order`.

### Shared constants (`constants.py`)
Index identifiers (`INDEX_NAME_TO_ID`, `INDEX_ID_TO_NAME`, helpers `index_id_for` / `index_name_for` / `is_index_id`), the index exchange segment (`IDX_SEGMENT = "IDX_I"`), and the options product type (`OPTIONS_PRODUCT_TYPE = "INTRADAY"`) are centralized in `constants.py`. The product type MUST stay identical across entry, SL/Target GTT, and manual-exit legs — otherwise the exit SELL opens a new short instead of netting the long.

---

## 5. State Management & Reliability
- **Memory Tiering**: The system defaults to **Redis** on `localhost:6379` for robust sub-millisecond atomic state persistance between restarts. If Redis is unavailable, it gracefully downgrades to isolated Python dictionary **In-Memory** caching. 
- **Webhook Postbacks**: It relies gracefully on pushed HTTP Postbacks from Dhan into `/webhook` and `/dhan-postback` endpoints rather than intensely polling Dhan limits aggressively. The execution engines use these postbacks to sync `TRADED` status updates seamlessly into the state cache (e.g., locking in the `entry_price`).

---

## 6. Deployment Environment
- **Platform**: Vultr VPS (Ubuntu 22.04 LTS).
- **Service Management**: Hosted natively using `gunicorn` on port 80 behind Systemd.
- **Deployment Process**: Utilizes automated rsyncing via `deploy_vultr.sh`, which automatically filters out local metadata caches (`.git`, test files), migrates system files, seamlessly installs Python requirements securely inside the virtual environment (`venv`), and reboots Gunicorn with zero downtime.
