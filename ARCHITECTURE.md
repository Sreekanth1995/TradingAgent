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
- **Deferred Boundary Placement**: Delays placing protective Stop Loss or Target bounds until the Dhan broker confirms the parent entry is firmly *TRADED* via webhooks (`handle_postback()`).
- **GTT Protection**: Protective bounds managed by this engine are placed as remote GTT (Good-Till-Triggered) OCO (One-Cancels-Other) structures linked explicitly to underlying index prices.

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

---

## 5. State Management & Reliability
- **Memory Tiering**: The system defaults to **Redis** on `localhost:6379` for robust sub-millisecond atomic state persistance between restarts. If Redis is unavailable, it gracefully downgrades to isolated Python dictionary **In-Memory** caching. 
- **Webhook Postbacks**: It relies gracefully on pushed HTTP Postbacks from Dhan into `/webhook` and `/dhan-postback` endpoints rather than intensely polling Dhan limits aggressively. The execution engines use these postbacks to sync `TRADED` status updates seamlessly into the state cache (e.g., locking in the `entry_price`).

---

## 6. Deployment Environment
- **Platform**: Vultr VPS (Ubuntu 22.04 LTS).
- **Service Management**: Hosted natively using `gunicorn` on port 80 behind Systemd.
- **Deployment Process**: Utilizes automated rsyncing via `deploy_vultr.sh`, which automatically filters out local metadata caches (`.git`, test files), migrates system files, seamlessly installs Python requirements securely inside the virtual environment (`venv`), and reboots Gunicorn with zero downtime.
