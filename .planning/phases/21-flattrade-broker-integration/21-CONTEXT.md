# Phase 21: FlatTrade Broker Integration - Context

**Gathered:** 2026-10-22
**Status:** Ready for planning

<domain>
## Phase Boundary

Integrate FlatTrade API (based on NorenRestApi / Pi v2) into the terminal's multi-broker architecture, enabling concurrent authentication, contract resolution, position tracking, and zero-brokerage order routing alongside Dhan and Groww without regressing any existing broker integrations.
</domain>

<decisions>
## Implementation Decisions

### Order & Bracket Mechanics
- **D-01: Market Entry + Engine-Armed Stop Loss:** Orders on FlatTrade execute as immediate MARKET entries under Intraday MIS (`buy_or_sell='B'`, `product_type='I'`, `exchange='NFO'`, `price_type='MKT'`), followed by immediate Stop-Loss leg arming (`price_type='SL-LMT'` or `SL-MKT`) upon fill confirmation.
- **D-02: Reversals / Exits via Modify Leg to Market:** On signal reversal or smart exit, look up the active Stop-Loss order number and call `modify_order(orderno=orderno, newprice_type='MKT')` to execute an immediate market fill.
- **D-03: Independent Lot Sizing:** FlatTrade order size is independently governed by `FLAT_LOT_MULTIPLIER` (in `.env` / config) with separate margin checks via `api.get_limits()`.
- **D-04: Isolated Fail-Safe Execution:** Parallel execution with failure isolation. If FlatTrade rejects an order or suffers an API timeout, Dhan and Groww positions remain active and unaffected; a high-priority alarm is emitted and failure logged.
- **D-05: Account-Scoped State:** State is partitioned under `state:flattrade:{underlying}` in Redis, maintaining independent tracking of open positions, entry IDs, and active legs.

### Authentication & Daily Session Management
- **D-06: Automated Headless Auth (.env + TOTP):** Store `FLATTRADE_USER_ID`, `FLATTRADE_PASSWORD`, `FLATTRADE_API_KEY`, `FLATTRADE_API_SECRET`, and `FLATTRADE_TOTP_KEY` in `.env`. The system completes headless authentication, generates the SHA-256 session token (`sha256(api_key + request_code + api_secret)`), and stores the active token in Redis during startup and pre-market morning cron.
- **D-07: Triple-Broker Header Badges:** Dashboard UI header renders status badges for all three configured brokers: "Dhan: Active [UCC]", "Groww: Active [UCC]", and "FlatTrade: Active [UCC]" with real-time connectivity and reconnect action buttons.

### Instrument & Scrip Resolution
- **D-08: Canonical Symbol Bridge with API Validation:** Standard NSE exchange trading symbols (e.g. `NIFTY24DEC24000CE`) act as the universal bridge across brokers. For FlatTrade, the symbol is sent directly with `exchange='NFO'`, validated via `api.searchscrip(exchange='NFO', searchtext=...)` / `api.get_security_info()` and cached in Redis/memory.

### the agent's Discretion
- Implementation of `FlatTradeClient` implementing `broker/interfaces.py` contracts (`FlatTradeAuthService`, `FlatTradeOrderService`, `FlatTradeInstrumentService`, `FlatTradeMarketDataService`, `FlatTradeSafetyService`).
- Integration into `MultiBrokerManager` to fan out orders across Dhan, Groww, and FlatTrade in parallel threads.
- Offline mock implementation (`MockFlatTradeClient`) to maintain 100% test suite execution without network dependencies.
</decisions>

<specifics>
## Specific Ideas & HLD

- **High Level Design (HLD) Architecture:**
  - Ingress: Webhook signals pass through `feeling_gate.py` and are handed to `MultiBrokerManager`.
  - Dispatch: `MultiBrokerManager` triggers `DhanClient`, `GrowwClient`, and `FlatTradeClient` concurrently.
  - Adapter: `FlatTradeClient` wraps `NorenRestApi` methods conforming strictly to official FlatTrade specifications:
    - `api.place_order(buy_or_sell, product_type='I', exchange='NFO', tradingsymbol, quantity, price_type='MKT', price=0.0, retention='DAY')`
    - `api.modify_order(exchange='NFO', tradingsymbol, orderno, newprice_type='MKT', newquantity=...)`
    - `api.cancel_order(orderno)`
    - `api.get_positions()`
    - `api.get_limits()`
</specifics>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing:**

### Official FlatTrade API Documentation
- `https://github.com/flattrade/pythonAPI` — Official FlatTrade Python API & wrapper implementation (`NorenRestApi`)
- `https://pi.flattrade.in/` — Official Pi Connect v2 Documentation
- `https://wall.flattrade.in/` — Flattrade Wall API Key and Credential Configuration

### Internal Architecture
- `broker/interfaces.py` — Broker domain protocols
- `.planning/phases/20-groww-multi-account/20-CONTEXT.md` — Phase 20 Multi-Broker decisions
- `broker/client.py` — DhanClient facade implementation
- `server.py` — Main Flask server and webhook ingress
</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `broker/interfaces.py`: Clean abstract contracts ready for `FlatTradeClient` decomposition.
- `MultiBrokerManager`: Orchestrates parallel order placement across all active broker facades.
- `feeling_gate.py`: Shared sentiment gate applies once per signal before multi-broker fanout.

### Established Patterns
- Redis namespaced keys: `state:{broker}:{underlying}` and `tokens:{broker}:{ucc}`.
- Zero live network calls during tests via dependency-injected mock clients.

### Integration Points
- `MultiBrokerManager`: Registers `FlatTradeClient` as an active broker adapter.
- `templates/index.html`: Header badge for FlatTrade account connection and margin limit.
- `.env`: `FLATTRADE_USER_ID`, `FLATTRADE_API_KEY`, `FLATTRADE_API_SECRET`, `FLATTRADE_TOTP_KEY`, `FLAT_LOT_MULTIPLIER`.
</code_context>

<deferred>
## Deferred Ideas

- None — discussion stayed within Phase 21 scope.
</deferred>

---

*Phase: 21-flattrade-broker-integration*
