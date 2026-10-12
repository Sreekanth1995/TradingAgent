# Graph Report - TradingAgent  (2026-10-12)

## Corpus Check
- 95 files · ~63,616 words
- Verdict: corpus is large enough that graph structure adds value.
- Unclassified: 6 file(s) not represented in the graph (top: (none) 4, .example 1, .pine 1)

## Summary
- 1120 nodes · 2138 edges · 110 communities (34 shown, 76 thin omitted)
- Extraction: 90% EXTRACTED · 10% INFERRED · 0% AMBIGUOUS · INFERRED: 212 edges (avg confidence: 0.9)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `8d371bc0`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- SuperOrderEngine
- FeelingState
- derive_entry_trigger
- ConditionalOrderEngine
- mcp_server.py
- Milestone 0.1.0: Live Trading Foundation
- route
- server.py
- conditional_order
- DhanClient
- DhanOrderService
- _add_activity_log
- logging
- test_modular_broker.py
- __init__.py
- trade_feed.py
- TestLtpSpec
- pytest
- Tech Stack
- TestContraPending
- test_feeling_gate.py
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
- os
- Python Dependency Manifest
- Antigravity Trader Terminal Dashboard
- TestRoutes
- write_text
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
- Key Changes
- .get_ltp
- DhanConditionalOrderService
- deploy_vultr.sh
- pre-commit-check.sh
- run_test_loop.sh
- Hardcoded Index Mapping
- Coding and Logging Standards
- MCP Server
- No-Network DhanClient Test Harness
- test_money_safety_9a.py
- .exit_super_order
- DhanMarketDataService
- TestSlackWebhookGating
- instrument_service.py
- test_dhan_client_facade_delegation
- Plan: Phase 13 - Modular Broker Facade & Dedicated Services
- ConditionalOrderServiceInterface
- set_feeling_route
- scrip_status
- Summary: Phase 13 - Modular Broker Facade & Dedicated Services
- set_conditional_index_orders
- test_dhan_client_offline_initialization

## God Nodes (most connected - your core abstractions)
1. `DhanClient` - 88 edges
2. `MockDhanClient` - 57 edges
3. `ConditionalOrderEngine` - 40 edges
4. `SuperOrderEngine` - 39 edges
5. `DhanOrderService` - 34 edges
6. `FeelingState` - 28 edges
7. `_call()` - 23 edges
8. `DhanInstrumentService` - 22 edges
9. `OrderServiceInterface` - 21 edges
10. `DhanMarketDataService` - 20 edges

## Surprising Connections (you probably didn't know these)
- `Executive Summary` --references--> `DhanClient`  [INFERRED]
  .planning/phases/13-modular-broker-facade/13-SUMMARY.md → broker/client.py
- `Tasks` --references--> `DhanAuthService`  [INFERRED]
  .planning/phases/13-modular-broker-facade/13-PLAN.md → broker/auth_service.py
- `Key Changes` --references--> `DhanAuthService`  [INFERRED]
  .planning/phases/13-modular-broker-facade/13-SUMMARY.md → broker/auth_service.py
- `Plan: Phase 13 - Modular Broker Facade & Dedicated Services` --references--> `DhanClient`  [INFERRED]
  .planning/phases/13-modular-broker-facade/13-PLAN.md → broker/client.py
- `Tasks` --references--> `DhanClient`  [INFERRED]
  .planning/phases/13-modular-broker-facade/13-PLAN.md → broker/client.py

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **Native Super Order Signal-to-Execution Pipeline** — planning_codebase_architecture_tradingview_hub, planning_codebase_architecture_flask_server, planning_codebase_architecture_super_order_engine, planning_codebase_architecture_broker_layer, planning_codebase_integrations_dhan_api_v2 [EXTRACTED 1.00]
- **Phase 4 Review, Fix, and Verification Loop** — planning_phases_04_positions_container_context, planning_phases_04_positions_container_review, planning_phases_04_positions_container_review_fix, planning_phases_04_positions_container_verification [EXTRACTED 1.00]
- **Position State Persistence and Storage Resilience** — planning_requirements_req_03_stateful_position_tracking, planning_codebase_integrations_redis_store, planning_codebase_concerns_dhan_token_persistence, planning_codebase_architecture_super_order_engine [INFERRED 0.85]
- **AI-in-the-Loop Real-Time Execution Pipeline** — planning_phases_11_context_ai_in_the_loop, planning_phases_11_context_sse_consumer, docs_mcp_setup_trading_agent_bridge, planning_phases_10_mcp_enhancements_10_review_naming_mismatch [INFERRED 0.95]
- **Fail-Closed Operator Alarm Architecture** — docs_architecture_alarm_pipeline, docs_architecture_broker_disagreement, templates_index_refreshactivitylogs, readme_alarm_pipeline [INFERRED 0.95]
- **State-Aware UI Position Management Loop** — templates_index_refreshstate, templates_index_updateui, templates_index_senduiaction, planning_phases_08_ui_management_08_context_state_aware_dashboard [INFERRED 0.95]

## Communities (110 total, 76 thin omitted)

### Community 0 - "SuperOrderEngine"
Cohesion: 0.09
Nodes (6): TestDirectSignalStrategy, SuperOrderEngine, TestOppositeSignalExit, test_level_cross_does_not_open_position_when_current_side_none(), TestPercentageCalculations, TestSuperOrderModify

### Community 1 - "FeelingState"
Cohesion: 0.07
Nodes (6): feeling_gate(), FeelingState, server_app(), TestDecision, TestLifecycle, TestPersistence

### Community 2 - "derive_entry_trigger"
Cohesion: 0.20
Nodes (4): derive_entry_trigger(), round_to_tick(), TestDeriveEntryTrigger, TestRoundToTick

### Community 3 - "ConditionalOrderEngine"
Cohesion: 0.05
Nodes (14): ConditionalOrderEngine, validate_sl_target(), TestConditionalOrderEngine, arm_call(), make_engine(), TestArmConditionalEntry, TestConditionalFill, TestFlush (+6 more)

### Community 4 - "mcp_server.py"
Cohesion: 0.08
Nodes (21): _call(), cancel_conditional_order(), cancel_super_order(), exit_conditional_order(), exit_super_order(), get_activity_logs(), get_feeling(), get_last_signal() (+13 more)

### Community 5 - "Milestone 0.1.0: Live Trading Foundation"
Cohesion: 0.06
Nodes (44): Broker Layer (broker_dhan.py), Flask Server (server.py), Super Order Engine, System Architecture Flow, TradingView Webhook Hub, Redis / Dhan Token Persistence Limitation, Hardcoded Scalping Thresholds, Dhan API v2 (+36 more)

### Community 6 - "route"
Cohesion: 0.05
Nodes (19): auth_callback(), auth_initiate(), auth_renew(), dashboard(), dhan_postback(), fund_limit(), get_activity_logs(), get_broker_orders() (+11 more)

### Community 7 - "server.py"
Cohesion: 0.09
Nodes (17): _clear_exit_order_meta(), _ErrorBufferHandler, _find_level_key_by_value(), get_context(), _get_exit_order_meta(), _get_level_value_by_key(), get_levels(), _handle_live_order_update() (+9 more)

### Community 8 - "conditional_order"
Cohesion: 0.11
Nodes (15): index_id_for(), calculate_quantity_from_margin(), resolve_call_itm(), resolve_index_spot(), resolve_put_itm(), conditional_order(), _feeling_block_for_entry(), get_itm() (+7 more)

### Community 11 - "_add_activity_log"
Cohesion: 0.12
Nodes (8): _add_activity_log(), cancel_conditional_orders(), _compute_zone(), dy_signal(), get_zone(), manual_exit(), _post_to_slack_async(), range_signal()

### Community 12 - "logging"
Cohesion: 0.14
Nodes (5): parse_csv(), simulate_today(), MockBroker, simulate(), simulate_from_csv()

### Community 13 - "test_modular_broker.py"
Cohesion: 0.09
Nodes (6): AuthServiceInterface, MarketDataServiceInterface, SafetyServiceInterface, SocketServiceInterface, test_interfaces_implemented_by_services(), test_no_untimed_requests_in_broker_package()

### Community 14 - "__init__.py"
Cohesion: 0.25
Nodes (7): BrokerDisagreement(), ExchangeSegment, OrderType, ProductType, TransactionType, Validity, DhanSafetyService

### Community 15 - "trade_feed.py"
Cohesion: 0.16
Nodes (10): cancel_super_order(), dhan_webhook(), _get_active_positions(), get_state(), get_trade_feed(), _connect(), get_recent_trades(), init_db() (+2 more)

### Community 17 - "pytest"
Cohesion: 0.10
Nodes (8): client(), test_gtt_orders_success(), test_gtt_orders_unauthorized(), client(), test_get_active_positions_empty(), test_get_active_positions_missing_ltp(), test_get_active_positions_with_data(), test_get_state_endpoint_mock()

### Community 18 - "Tech Stack"
Cohesion: 0.40
Nodes (4): Backend, DevOps, Frontend, Tech Stack

### Community 20 - "test_feeling_gate.py"
Cohesion: 0.12
Nodes (7): read_json(), ReadResult, write_json(), derive_side(), TestRead, TestWrite, writer()

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

### Community 35 - "updateUI"
Cohesion: 0.29
Nodes (8): State-Aware Dashboard Specification, WR-01 Incomplete State-Locking Controls, Phase 8 UI Delivery Summary, refreshState, sendUIAction, showBracketState, showGttState, updateUI

### Community 36 - "os"
Cohesion: 0.20
Nodes (3): attempt_renew_token(), check_health(), main()

### Community 37 - "Python Dependency Manifest"
Cohesion: 0.29
Nodes (6): State Management & Memory Tiering, Web UI Layer, Python Dependency Manifest, dhanhq SDK Dependency, Flask Framework Dependency, Redis Client Dependency

### Community 38 - "Antigravity Trader Terminal Dashboard"
Cohesion: 0.29
Nodes (7): CR-01 Backend Route Mismatch, cancelConditionalOrders, Antigravity Trader Terminal Dashboard, emergencyExit, Range Tracker UI, refreshTradeFeed, setConditionalOrders

### Community 41 - "write_text"
Cohesion: 0.33
Nodes (3): _do_write(), write_text(), _do_write()

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

### Community 88 - "test_money_safety_9a.py"
Cohesion: 0.15
Nodes (3): TestCorrelationIdUniqueness, TestHttpTimeouts, TestWebhookSecretFailClosed

### Community 90 - "DhanMarketDataService"
Cohesion: 0.20
Nodes (3): DhanMarketDataService, DhanSocketService, Tasks

### Community 95 - "Plan: Phase 13 - Modular Broker Facade & Dedicated Services"
Cohesion: 0.20
Nodes (3): load_scrip_background(), Plan: Phase 13 - Modular Broker Facade & Dedicated Services, test_expiry_selection_only_today_available()

### Community 97 - "set_feeling_route"
Cohesion: 0.33
Nodes (3): normalize_feeling(), _contra_pending_warnings(), set_feeling_route()

## Knowledge Gaps
- **43 isolated node(s):** `updateFeeling`, `Direct Signal Strategy`, `Unauthenticated SSE and Last-Signal Endpoints`, `SSE Queue Blocking DoS Vulnerability`, `Operational Hardening PR #9a` (+38 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 452 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **76 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `DhanClient` connect `DhanClient` to `DhanInstrumentService`, `scrip_status`, `DhanConditionalOrderService`, `Summary: Phase 13 - Modular Broker Facade & Dedicated Services`, `DhanOrderService`, `test_modular_broker.py`, `DhanAuthService`, `__init__.py`, `TestLtpSpec`, `test_dhan_client_offline_initialization`, `.test_broker_pending_orders_flexible_keys`, `Key Changes`, `TestSecurityIdFailClosed`, `DhanMarketDataService`, `test_dhan_client_facade_delegation`, `Plan: Phase 13 - Modular Broker Facade & Dedicated Services`?**
  _High betweenness centrality (0.108) - this node is a cross-community bridge._
- **Are the 18 inferred relationships involving `DhanClient` (e.g. with `DhanAuthService` and `ExchangeSegment`) actually correct?**
  _`DhanClient` has 18 INFERRED edges - model-reasoned connections that need verification._
- **What connects `updateFeeling`, `Direct Signal Strategy`, `Unauthenticated SSE and Last-Signal Endpoints` to the rest of the system?**
  _43 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `SuperOrderEngine` be split into smaller, more focused modules?**
  _Cohesion score 0.09390243902439024 - nodes in this community are weakly interconnected._
- **Why does `MockDhanClient` connect `MockDhanClient` to `SuperOrderEngine`, `FeelingState`, `ConditionalOrderEngine`, `server.py`, `logging`, `test_feeling_gate.py`, `.get_ltp`, `.get_itm_contract`, `.cancel_super_order`, `.get_all_gtt_orders`, `.get_completed_trades`, `.get_index_id`, `.get_index_spot_fallback`, `.get_multi_margin_calculator`, `.get_order_status`, `.get_positions`, `.margin_calculator`, `.modify_super_entry_leg`, `.modify_super_sl_leg`, `.modify_super_target_leg`, `.test_engine_skipped_entirely_when_feeling_state_is_none`?**
  _High betweenness centrality (0.107) - this node is a cross-community bridge._
- **Are the 5 inferred relationships involving `MockDhanClient` (e.g. with `TestArmConditionalEntry` and `TestConditionalFill`) actually correct?**
  _`MockDhanClient` has 5 INFERRED edges - model-reasoned connections that need verification._
- **Should `FeelingState` be split into smaller, more focused modules?**
  _Cohesion score 0.07092198581560284 - nodes in this community are weakly interconnected._