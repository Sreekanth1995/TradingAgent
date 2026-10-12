# Graph Report - TradingAgent  (2026-10-13)

## Corpus Check
- 101 files · ~66,511 words
- Verdict: corpus is large enough that graph structure adds value.
- Unclassified: 6 file(s) not represented in the graph (top: (none) 4, .example 1, .pine 1)

## Summary
- 1161 nodes · 2209 edges · 111 communities (38 shown, 73 thin omitted)
- Extraction: 89% EXTRACTED · 11% INFERRED · 0% AMBIGUOUS · INFERRED: 233 edges (avg confidence: 0.9)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `20125de7`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- .process_signal
- FeelingState
- derive_entry_trigger
- ConditionalOrderEngine
- mcp_server.py
- Milestone 0.1.0: Live Trading Foundation
- route
- server.py
- instrument_resolver.py
- DhanClient
- DhanOrderService
- _add_activity_log
- broker_mock.py
- test_modular_broker.py
- __init__.py
- trade_feed.py
- TestLtpSpec
- test_phase4_positions.py
- Tech Stack
- TestContraPending
- read_json
- MockDhanClient
- TestSecurityIdFailClosed
- NIFTY Options Trading Bot Strategy
- TradingAgent MCP Bridge
- exit_conditional_order
- Architecture Overview
- TestRouteGate
- DhanInstrumentService
- .get_itm_contract
- updateUI
- SuperOrderEngine
- Python Dependency Manifest
- Antigravity Trader Terminal Dashboard
- TestRoutes
- auto_login_dhan.py
- InstrumentServiceInterface
- Any
- TradingAgent Project Overview
- BacktestEngine
- DhanAuthService
- events
- TestUnreadableRoutes
- Alarm Pipeline
- Pre-Commit Verification Checklist
- Third Strategy Renko Q-Trend Confluence
- vps_setup_remote.sh
- setter
- .get_ltp
- DhanConditionalOrderService
- deploy_vultr.sh
- pre-commit-check.sh
- run_test_loop.sh
- Hardcoded Index Mapping
- Coding and Logging Standards
- MCP Server
- No-Network DhanClient Test Harness
- test_feeling_gate.py
- validate_sl_target
- DhanMarketDataService
- TestSlackWebhookGating
- _compute_zone
- test_dhan_client_facade_delegation
- load_scrip_background
- TestSuperOrderModify
- set_feeling_route
- test_gtt_orders.py
- DhanSafetyService
- Summary: Phase 13 - Modular Broker Facade & Dedicated Services
- Plan: Phase 17 - Zero-Downtime Atomic Scrip Reload & Lot Map Guard
- Summary: Phase 18 - Kill Switch Super Order Leg Cancellation
- TestSSEInvisibility
- TestCorrelationIdUniqueness
- TestWebhookSecretFailClosed
- TestHttpTimeouts
- Plan: Phase 13 - Modular Broker Facade & Dedicated Services
- test_dhan_client_offline_initialization
- test_expiry_selection_only_today_available

## God Nodes (most connected - your core abstractions)
1. `DhanClient` - 91 edges
2. `MockDhanClient` - 58 edges
3. `ConditionalOrderEngine` - 43 edges
4. `SuperOrderEngine` - 39 edges
5. `DhanOrderService` - 35 edges
6. `FeelingState` - 28 edges
7. `DhanInstrumentService` - 26 edges
8. `_call()` - 23 edges
9. `OrderServiceInterface` - 21 edges
10. `DhanMarketDataService` - 21 edges

## Surprising Connections (you probably didn't know these)
- `Executive Summary` --references--> `DhanClient`  [INFERRED]
  .planning/phases/13-modular-broker-facade/13-SUMMARY.md → broker/client.py
- `Tasks` --references--> `DhanClient`  [INFERRED]
  .planning/phases/17-zero-downtime-scrip-reload/17-PLAN.md → broker/client.py
- `Key Changes` --references--> `DhanSafetyService`  [INFERRED]
  .planning/phases/18-kill-switch-super-order-legs/18-SUMMARY.md → broker/safety_service.py
- `Tasks` --references--> `DhanAuthService`  [INFERRED]
  .planning/phases/13-modular-broker-facade/13-PLAN.md → broker/auth_service.py
- `Key Changes` --references--> `DhanAuthService`  [INFERRED]
  .planning/phases/13-modular-broker-facade/13-SUMMARY.md → broker/auth_service.py

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **Native Super Order Signal-to-Execution Pipeline** — planning_codebase_architecture_tradingview_hub, planning_codebase_architecture_flask_server, planning_codebase_architecture_super_order_engine, planning_codebase_architecture_broker_layer, planning_codebase_integrations_dhan_api_v2 [EXTRACTED 1.00]
- **Phase 4 Review, Fix, and Verification Loop** — planning_phases_04_positions_container_context, planning_phases_04_positions_container_review, planning_phases_04_positions_container_review_fix, planning_phases_04_positions_container_verification [EXTRACTED 1.00]
- **Position State Persistence and Storage Resilience** — planning_requirements_req_03_stateful_position_tracking, planning_codebase_integrations_redis_store, planning_codebase_concerns_dhan_token_persistence, planning_codebase_architecture_super_order_engine [INFERRED 0.85]
- **AI-in-the-Loop Real-Time Execution Pipeline** — planning_phases_11_context_ai_in_the_loop, planning_phases_11_context_sse_consumer, docs_mcp_setup_trading_agent_bridge, planning_phases_10_mcp_enhancements_10_review_naming_mismatch [INFERRED 0.95]
- **Fail-Closed Operator Alarm Architecture** — docs_architecture_alarm_pipeline, docs_architecture_broker_disagreement, templates_index_refreshactivitylogs, readme_alarm_pipeline [INFERRED 0.95]
- **State-Aware UI Position Management Loop** — templates_index_refreshstate, templates_index_updateui, templates_index_senduiaction, planning_phases_08_ui_management_08_context_state_aware_dashboard [INFERRED 0.95]

## Communities (111 total, 73 thin omitted)

### Community 0 - ".process_signal"
Cohesion: 0.10
Nodes (3): TestDirectSignalStrategy, TestOppositeSignalExit, test_level_cross_does_not_open_position_when_current_side_none()

### Community 1 - "FeelingState"
Cohesion: 0.06
Nodes (7): feeling_gate(), FeelingState, server_app(), TestDecision, TestEngineGuard, TestLifecycle, TestPersistence

### Community 2 - "derive_entry_trigger"
Cohesion: 0.20
Nodes (4): derive_entry_trigger(), round_to_tick(), TestDeriveEntryTrigger, TestRoundToTick

### Community 3 - "ConditionalOrderEngine"
Cohesion: 0.05
Nodes (20): ConditionalOrderEngine, Goal, Plan: Phase 19 - Approach C Autonomous Reconciliation Safety Net, Tasks, Executive Summary, Key Changes, Summary: Phase 19 - Approach C Autonomous Reconciliation Safety Net, TestConditionalOrderEngine (+12 more)

### Community 4 - "mcp_server.py"
Cohesion: 0.08
Nodes (21): _call(), cancel_conditional_order(), cancel_super_order(), exit_conditional_order(), exit_super_order(), get_activity_logs(), get_feeling(), get_last_signal() (+13 more)

### Community 5 - "Milestone 0.1.0: Live Trading Foundation"
Cohesion: 0.06
Nodes (44): Broker Layer (broker_dhan.py), Flask Server (server.py), Super Order Engine, System Architecture Flow, TradingView Webhook Hub, Redis / Dhan Token Persistence Limitation, Hardcoded Scalping Thresholds, Dhan API v2 (+36 more)

### Community 6 - "route"
Cohesion: 0.05
Nodes (20): auth_callback(), auth_initiate(), auth_renew(), dashboard(), dhan_postback(), fund_limit(), get_activity_logs(), get_broker_orders() (+12 more)

### Community 7 - "server.py"
Cohesion: 0.08
Nodes (17): _clear_exit_order_meta(), _ErrorBufferHandler, _find_level_key_by_value(), get_context(), _get_exit_order_meta(), get_feeling_route(), get_last_signal(), _get_level_value_by_key() (+9 more)

### Community 8 - "instrument_resolver.py"
Cohesion: 0.15
Nodes (10): calculate_quantity_from_margin(), resolve_call_itm(), resolve_index_spot(), resolve_put_itm(), get_itm(), get_margin(), level_hit(), _set_pending_trade() (+2 more)

### Community 11 - "_add_activity_log"
Cohesion: 0.13
Nodes (8): _add_activity_log(), cancel_conditional_orders(), conditional_order(), _feeling_block_for_entry(), _get_pending_trade(), manual_exit(), _post_to_slack_async(), skip_trade()

### Community 12 - "broker_mock.py"
Cohesion: 0.14
Nodes (4): parse_csv(), MockBroker, simulate(), test_no_untimed_requests_in_broker_package()

### Community 13 - "test_modular_broker.py"
Cohesion: 0.11
Nodes (6): AuthServiceInterface, MarketDataServiceInterface, SafetyServiceInterface, SocketServiceInterface, Key Changes, test_interfaces_implemented_by_services()

### Community 14 - "__init__.py"
Cohesion: 0.13
Nodes (9): BrokerDisagreement(), ExchangeSegment, OrderType, ProductType, TransactionType, Validity, index_id_for(), index_name_for() (+1 more)

### Community 15 - "trade_feed.py"
Cohesion: 0.19
Nodes (9): cancel_super_order(), dhan_webhook(), get_state(), get_trade_feed(), _connect(), get_recent_trades(), init_db(), insert_trade() (+1 more)

### Community 17 - "test_phase4_positions.py"
Cohesion: 0.19
Nodes (6): _get_active_positions(), client(), test_get_active_positions_empty(), test_get_active_positions_missing_ltp(), test_get_active_positions_with_data(), test_get_state_endpoint_mock()

### Community 18 - "Tech Stack"
Cohesion: 0.40
Nodes (4): Backend, DevOps, Frontend, Tech Stack

### Community 20 - "read_json"
Cohesion: 0.12
Nodes (9): read_json(), ReadResult, write_json(), _do_write(), write_text(), _do_write(), TestRead, TestWrite (+1 more)

### Community 26 - "NIFTY Options Trading Bot Strategy"
Cohesion: 0.20
Nodes (5): Direct Signal Strategy, Per-Underlying Market Feeling Gate, NIFTY Options Trading Bot Strategy, updateFeeling, updateFeelingsUI

### Community 27 - "TradingAgent MCP Bridge"
Cohesion: 0.20
Nodes (6): MCP Available Tool Catalog, TradingAgent MCP Bridge, SSE Stream Consumer Decision, Unauthenticated SSE and Last-Signal Endpoints, SSE Queue Blocking DoS Vulnerability, Model Context Protocol SDK Dependency

### Community 29 - "exit_conditional_order"
Cohesion: 0.22
Nodes (7): _add_to_history(), exit_conditional_order(), exit_super_order(), get_history(), _load_history(), _save_history(), _set_exit_order_meta()

### Community 31 - "Architecture Overview"
Cohesion: 0.25
Nodes (6): Conditional Order Engine Component, Operational Hardening PR #9a, Architecture Overview, Shared Constants Architecture, Super Order Engine Component, Native GTT Leg Management

### Community 33 - "DhanInstrumentService"
Cohesion: 0.09
Nodes (6): DhanInstrumentService, load_scrip_background(), Executive Summary, Key Changes, Summary: Phase 17 - Zero-Downtime Atomic Scrip Reload & Lot Map Guard, test_zero_downtime_scrip_reload_preserves_maps()

### Community 35 - "updateUI"
Cohesion: 0.29
Nodes (8): State-Aware Dashboard Specification, WR-01 Incomplete State-Locking Controls, Phase 8 UI Delivery Summary, refreshState, sendUIAction, showBracketState, showGttState, updateUI

### Community 36 - "SuperOrderEngine"
Cohesion: 0.20
Nodes (3): SuperOrderEngine, TestPercentageCalculations, TestSmartExitFix

### Community 37 - "Python Dependency Manifest"
Cohesion: 0.29
Nodes (6): State Management & Memory Tiering, Web UI Layer, Python Dependency Manifest, dhanhq SDK Dependency, Flask Framework Dependency, Redis Client Dependency

### Community 38 - "Antigravity Trader Terminal Dashboard"
Cohesion: 0.29
Nodes (7): CR-01 Backend Route Mismatch, cancelConditionalOrders, Antigravity Trader Terminal Dashboard, emergencyExit, Range Tracker UI, refreshTradeFeed, setConditionalOrders

### Community 41 - "auto_login_dhan.py"
Cohesion: 0.28
Nodes (3): attempt_renew_token(), check_health(), main()

### Community 44 - "TradingAgent Project Overview"
Cohesion: 0.33
Nodes (6): Broker Middleware Layer, Operational Data Flow, Redis Persistence Architecture, TradingAgent Project Overview, Stateful Ranking Engine, Webhook Interface Architecture

### Community 47 - "events"
Cohesion: 0.40
Nodes (3): _event_stream(), events(), stream()

### Community 50 - "Alarm Pipeline"
Cohesion: 0.50
Nodes (3): BrokerDisagreement Contract, Operator Alarm Pipeline, refreshActivityLogs

### Community 51 - "Pre-Commit Verification Checklist"
Cohesion: 0.50
Nodes (4): Pre-Commit Verification Checklist, Pre-Commit Import Check, Pre-Commit Strategy Unit Tests, Pre-Commit Syntax Check

### Community 88 - "test_feeling_gate.py"
Cohesion: 0.14
Nodes (4): derive_side(), normalize_feeling(), simulate_today(), simulate_from_csv()

### Community 90 - "DhanMarketDataService"
Cohesion: 0.29
Nodes (3): DhanMarketDataService, DhanSocketService, Tasks

### Community 92 - "_compute_zone"
Cohesion: 0.25
Nodes (4): _compute_zone(), dy_signal(), get_zone(), range_signal()

### Community 98 - "test_gtt_orders.py"
Cohesion: 0.29
Nodes (3): client(), test_gtt_orders_success(), test_gtt_orders_unauthorized()

### Community 99 - "DhanSafetyService"
Cohesion: 0.19
Nodes (5): DhanSafetyService, Goal, Plan: Phase 18 - Kill Switch Super Order Leg Cancellation, Tasks, test_kill_switch_cancels_super_order_legs_before_squareoff()

### Community 101 - "Plan: Phase 17 - Zero-Downtime Atomic Scrip Reload & Lot Map Guard"
Cohesion: 0.50
Nodes (3): Goal, Plan: Phase 17 - Zero-Downtime Atomic Scrip Reload & Lot Map Guard, Tasks

### Community 102 - "Summary: Phase 18 - Kill Switch Super Order Leg Cancellation"
Cohesion: 0.50
Nodes (3): Executive Summary, Key Changes, Summary: Phase 18 - Kill Switch Super Order Leg Cancellation

## Knowledge Gaps
- **43 isolated node(s):** `updateFeeling`, `Direct Signal Strategy`, `Unauthenticated SSE and Last-Signal Endpoints`, `SSE Queue Blocking DoS Vulnerability`, `Operational Hardening PR #9a` (+38 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 470 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **73 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `DhanClient` connect `DhanClient` to `DhanOrderService`, `test_modular_broker.py`, `__init__.py`, `TestLtpSpec`, `TestSecurityIdFailClosed`, `DhanInstrumentService`, `DhanAuthService`, `.test_broker_pending_orders_flexible_keys`, `setter`, `DhanConditionalOrderService`, `DhanMarketDataService`, `test_dhan_client_facade_delegation`, `load_scrip_background`, `DhanSafetyService`, `Summary: Phase 13 - Modular Broker Facade & Dedicated Services`, `Plan: Phase 17 - Zero-Downtime Atomic Scrip Reload & Lot Map Guard`, `Plan: Phase 13 - Modular Broker Facade & Dedicated Services`, `test_dhan_client_offline_initialization`, `test_expiry_selection_only_today_available`?**
  _High betweenness centrality (0.107) - this node is a cross-community bridge._
- **Are the 20 inferred relationships involving `DhanClient` (e.g. with `DhanAuthService` and `ExchangeSegment`) actually correct?**
  _`DhanClient` has 20 INFERRED edges - model-reasoned connections that need verification._
- **What connects `updateFeeling`, `Direct Signal Strategy`, `Unauthenticated SSE and Last-Signal Endpoints` to the rest of the system?**
  _43 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `.process_signal` be split into smaller, more focused modules?**
  _Cohesion score 0.0957983193277311 - nodes in this community are weakly interconnected._
- **Why does `MockDhanClient` connect `MockDhanClient` to `.process_signal`, `FeelingState`, `ConditionalOrderEngine`, `server.py`, `broker_mock.py`, `.get_ltp`, `.get_itm_contract`, `SuperOrderEngine`, `.cancel_super_order`, `.get_all_gtt_orders`, `.get_completed_trades`, `.get_index_id`, `.get_index_spot_fallback`, `.get_multi_margin_calculator`, `.get_order_status`, `.get_positions`, `.margin_calculator`, `.modify_super_entry_leg`, `.modify_super_sl_leg`, `.modify_super_target_leg`, `test_feeling_gate.py`, `._alarm`?**
  _High betweenness centrality (0.096) - this node is a cross-community bridge._
- **Are the 5 inferred relationships involving `MockDhanClient` (e.g. with `TestArmConditionalEntry` and `TestConditionalFill`) actually correct?**
  _`MockDhanClient` has 5 INFERRED edges - model-reasoned connections that need verification._
- **Should `FeelingState` be split into smaller, more focused modules?**
  _Cohesion score 0.0632996632996633 - nodes in this community are weakly interconnected._