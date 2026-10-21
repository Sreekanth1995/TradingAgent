# Phase 20: Groww Broker & Multi-Account Support - Context

**Gathered:** 2026-10-22
**Status:** Ready for planning

<domain>
## Phase Boundary

Expand the trading terminal to accept multiple accounts across different brokers, introducing Groww alongside the existing Dhan setup. The terminal must support concurrent authentication, instrument mapping, independent account state tracking, and dual-broker order placement (parallel broadcast or account-tagged routing) without regressing or breaking any existing Dhan APIs or caller workflows.
</domain>

<decisions>
## Implementation Decisions

### Multi-Account Order Routing & Allocation
- **D-01: Parallel Broadcast with Tag Override:** Incoming signals (TradingView webhook, MCP, or dashboard manual orders) dispatch across ALL active, logged-in accounts (Dhan + Groww) simultaneously by default. An optional `accounts: ["groww"]` or `broker: "dhan"` tag in the payload allows targeting specific accounts when desired.
- **D-02: Independent Per-Account Lot Sizing:** Support individual default lot multipliers or sizing per account via environment/config (`DHAN_LOT_MULTIPLIER=1`, `GROWW_LOT_MULTIPLIER=1`) with separate margin validation per account.
- **D-03: Isolated Execution (Fail-Safe):** Broker accounts execute orders in parallel with failure isolation. If Groww encounters an error or rejects an order, Dhan execution remains unaffected (and vice versa); a high-priority alarm is dispatched and the failure is logged.
- **D-04: Account-Scoped State in Redis:** Position state (side, entry ID, active contract, quantities) is partitioned per account in Redis (e.g. `state:dhan:{underlying}` and `state:groww:{underlying}`), while the dashboard provides an aggregated multi-account view.

### Groww Order Execution Architecture
- **D-05: Native Groww OCO Smart Orders:** Place immediate MARKET entry via `groww.place_order(...)`, then immediately arm a native Groww OCO bracket (`groww.create_smart_order` with `SMART_ORDER_TYPE_OCO`) for exchange-side Target and Stop Loss legs.
- **D-06: Intraday MIS Default:** Default product type for Groww option orders is `PRODUCT_MIS` (Intraday), matching typical algo day-trading requirements.
- **D-07: Smart Exits / Reversals via OCO Leg Modification:** On signal reversal or smart exit, modify the existing Groww OCO order's target or stop-loss trigger price towards current LTP (analogous to Dhan's +5/-5 offset behavior).

### Groww Authentication & Session Management
- **D-08: Automated Headless Auth (.env + TOTP):** Store `GROWW_API_KEY` and `GROWW_TOTP_SECRET` in `.env`. On server startup and scheduled pre-market morning run, generate `access_token` headlessly via `GrowwAPI.get_access_token(api_key=api_key, totp=totp)` using `pyotp`, persisting the active token in Redis.
- **D-09: Dual-Broker Header Badges:** Render both "Dhan: Active [UCC]" and "Groww: Active [UCC]" badges with live token health and reconnect action triggers on the dashboard navigation bar.

### Instrument & Scrip Resolution
- **D-10: Canonical Exchange Trading Symbol Bridge:** Standard exchange trading symbols (e.g. `NIFTY24DEC24000CE`) act as the universal bridge. Dhan resolves to numeric `security_id` via its local scrip master, while Groww accepts `trading_symbol` directly (validated against Groww's `get_instrument_by_exchange_and_trading_symbol` / scrip cache).

### the agent's Discretion
- Implementation of `GrowwClient` and dedicated modular services (`GrowwAuthService`, `GrowwOrderService`, `GrowwInstrumentService`, `GrowwMarketDataService`) implementing `broker/interfaces.py`.
- Architecture of `MultiBrokerManager` / `BrokerRegistry` to fan out order execution cleanly without altering existing `server.py` signatures.
- Error handling, timeouts, and logging for Groww API calls adhering to rate limits (10 req/sec for Orders, 20 req/sec for Non-Trading).
</decisions>

<specifics>
## Specific Ideas

- **Strict No-Hallucination Policy:** All Groww API calls strictly use official parameters from the `growwapi` SDK and documentation:
  - `groww.place_order(trading_symbol, quantity, validity=groww.VALIDITY_DAY, exchange=groww.EXCHANGE_NSE, segment=groww.SEGMENT_FNO, product=groww.PRODUCT_MIS, order_type=groww.ORDER_TYPE_MARKET, transaction_type=groww.TRANSACTION_TYPE_BUY, price=0, order_reference_id=...)`
  - `groww.create_smart_order(smart_order_type=groww.SMART_ORDER_TYPE_OCO, reference_id=..., segment=groww.SEGMENT_FNO, trading_symbol=..., quantity=..., product_type=groww.PRODUCT_MIS, exchange=groww.EXCHANGE_NSE, duration=groww.VALIDITY_DAY, net_position_quantity=..., transaction_type=groww.TRANSACTION_TYPE_SELL, target={...}, stop_loss={...})`
  - `groww.get_positions_for_user(segment=groww.SEGMENT_FNO)`
  - `groww.get_available_margin_details()`
  - `groww.modify_order(...)` / `groww.cancel_order(...)`
- **Zero-Downtime Guarantee for Dhan:** Dhan client code remains completely untouched and functional.
</specifics>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing:**

### Official Groww API Documentation
- `https://groww.in/trade-api/docs/python-sdk` — Groww Python SDK Overview & Auth
- `https://groww.in/trade-api/docs/python-sdk/orders` — Regular order placement, modification, status, and cancellation
- `https://groww.in/trade-api/docs/python-sdk/smart-orders` — GTT & OCO bracket orders
- `https://groww.in/trade-api/docs/python-sdk/portfolio` — Positions and holdings
- `https://groww.in/trade-api/docs/python-sdk/instruments` — Instrument retrieval and scrip formats
- `https://groww.in/trade-api/docs/python-sdk/margin` — Margin details and requirements

### Internal Architecture
- `broker/interfaces.py` — Broker domain protocols (`AuthServiceInterface`, `OrderServiceInterface`, `InstrumentServiceInterface`, etc.)
- `broker/client.py` — Existing DhanClient facade implementation
- `broker/common.py` — Enums, domain models, and shared error classes
- `server.py` — Main Flask server, webhook routing, and dashboard endpoints
- `super_order_engine.py` — Bracket order and state tracking engine
</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `broker/interfaces.py`: Clean abstract protocols ready for `GrowwClient` and modular Groww services.
- `SuperOrderEngine`: Bracket execution logic can be generalized to coordinate with `MultiBrokerManager`.
- `feeling_gate.py`: Signal filtering applies before broker dispatch, automatically benefiting both brokers.

### Established Patterns
- Dependency injection with mockability: Services take constructor configs and allow offline testing without live network calls.
- Redis state caching: Key-value namespacing for positions and active orders.

### Integration Points
- `server.py` webhook handler (`def webhook()`): Multi-broker broadcast dispatcher.
- `templates/index.html`: Header badges for dual-broker connection state and account balance/margin display.
- `.env`: `GROWW_API_KEY`, `GROWW_TOTP_SECRET`, `GROWW_LOT_MULTIPLIER`.
</code_context>

<deferred>
## Deferred Ideas

- None — discussion stayed within Phase 20 scope.
</deferred>

---

*Phase: 20-groww-multi-account*
