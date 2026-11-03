# Graph Report - TradingAgent  (2026-11-03)

## Corpus Check
- 126 files · ~94,518 words
- Verdict: corpus is large enough that graph structure adds value.
- Unclassified: 7 file(s) not represented in the graph (top: (none) 5, .example 1, .pine 1)

## Summary
- 1508 nodes · 2934 edges · 142 communities (53 shown, 89 thin omitted)
- Extraction: 89% EXTRACTED · 11% INFERRED · 0% AMBIGUOUS · INFERRED: 335 edges (avg confidence: 0.9)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `dd5ca127`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- SuperOrderEngine
- FeelingState
- derive_entry_trigger
- ._get_state
- mcp_server.py
- Milestone 0.1.0: Live Trading Foundation
- route
- server.py
- conditional_order
- DhanClient
- DhanOrderService
- _add_activity_log
- json
- test_modular_broker.py
- broker/__init__.py
- trade_feed.py
- TestLtpSpec
- test_phase4_positions.py
- Tech Stack
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
- Phase 20: Groww Broker & Multi-Account Support - Context
- Python Dependency Manifest
- Antigravity Trader Terminal Dashboard
- TestRoutes
- TestSlackWebhookGating
- InstrumentServiceInterface
- Any
- TradingAgent Project Overview
- Phase 21: FlatTrade Broker Integration - Context
- DhanAuthService
- events
- test_conditional_entry.py
- Alarm Pipeline
- Pre-Commit Verification Checklist
- Third Strategy Renko Q-Trend Confluence
- vps_setup_remote.sh
- setter
- DhanMarketDataService
- DhanConditionalOrderService
- MultiBrokerManager
- ConditionalOrderServiceInterface
- deploy_vultr.sh
- pre-commit-check.sh
- run_test_loop.sh
- Hardcoded Index Mapping
- Coding and Logging Standards
- MCP Server
- No-Network DhanClient Test Harness
- TestSSEInvisibility
- test_money_safety_9a.py
- write_text
- test_dhan_client_facade_delegation
- load_scrip_background
- Key Changes
- DhanSafetyService
- Summary: Phase 13 - Modular Broker Facade & Dedicated Services
- Plan: Phase 17 - Zero-Downtime Atomic Scrip Reload & Lot Map Guard
- requests
- Plan: Phase 13 - Modular Broker Facade & Dedicated Services
- test_dhan_client_offline_initialization
- test_multi_broker.py
- GrowwAuthService
- GrowwOrderService
- DummyRedis
- FlatTradeClient
- GrowwClient
- FlatTradeOrderService
- MockFlatTradeClient
- MockGrowwClient
- ConditionalOrderEngine
- .get_itm_contract
- .place_super_order
- simulate_trading.py
- GrowwInstrumentService
- 2. Component Redesigns & Upgrades
- Design System Master File: Antigravity Trader
- TestUnreadableRoutes
- .get_account_statuses
- Implementation Decisions
- Tasks
- validate_sl_target
- test_gtt_orders.py
- Key Changes
- BacktestEngine
- Goal
- set_feeling_route
- Plan: Phase 21 - Plan 02: Multi-Broker Admin Dashboard UI & Global Control
- DummyRedis
- test_expiry_selection_only_today_available
- Plan: Phase 21 - Plan 01: FlatTrade Broker Client & Dedicated Services

## God Nodes (most connected - your core abstractions)
1. `DhanClient` - 95 edges
2. `MockDhanClient` - 64 edges
3. `MultiBrokerManager` - 43 edges
4. `ConditionalOrderEngine` - 43 edges
5. `SuperOrderEngine` - 40 edges
6. `DhanOrderService` - 35 edges
7. `FlatTradeClient` - 30 edges
8. `GrowwClient` - 29 edges
9. `FeelingState` - 28 edges
10. `DhanInstrumentService` - 26 edges

## Surprising Connections (you probably didn't know these)
- `Executive Summary` --references--> `DhanClient`  [INFERRED]
  .planning/phases/13-modular-broker-facade/13-SUMMARY.md → broker/client.py
- `Tasks` --references--> `DhanClient`  [INFERRED]
  .planning/phases/17-zero-downtime-scrip-reload/17-PLAN.md → broker/client.py
- `Goal` --references--> `MultiBrokerManager`  [INFERRED]
  .planning/phases/20-groww-multi-account/20-02-PLAN.md → broker/manager.py
- `Goal` --references--> `ConditionalOrderEngine`  [INFERRED]
  .planning/phases/19-approach-c-reconciliation/19-PLAN.md → conditional_order_engine.py
- `Executive Summary` --references--> `ConditionalOrderEngine`  [INFERRED]
  .planning/phases/19-approach-c-reconciliation/19-SUMMARY.md → conditional_order_engine.py

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **Native Super Order Signal-to-Execution Pipeline** — planning_codebase_architecture_tradingview_hub, planning_codebase_architecture_flask_server, planning_codebase_architecture_super_order_engine, planning_codebase_architecture_broker_layer, planning_codebase_integrations_dhan_api_v2 [EXTRACTED 1.00]
- **Phase 4 Review, Fix, and Verification Loop** — planning_phases_04_positions_container_context, planning_phases_04_positions_container_review, planning_phases_04_positions_container_review_fix, planning_phases_04_positions_container_verification [EXTRACTED 1.00]
- **Position State Persistence and Storage Resilience** — planning_requirements_req_03_stateful_position_tracking, planning_codebase_integrations_redis_store, planning_codebase_concerns_dhan_token_persistence, planning_codebase_architecture_super_order_engine [INFERRED 0.85]
- **AI-in-the-Loop Real-Time Execution Pipeline** — planning_phases_11_context_ai_in_the_loop, planning_phases_11_context_sse_consumer, docs_mcp_setup_trading_agent_bridge, planning_phases_10_mcp_enhancements_10_review_naming_mismatch [INFERRED 0.95]
- **Fail-Closed Operator Alarm Architecture** — docs_architecture_alarm_pipeline, docs_architecture_broker_disagreement, templates_index_refreshactivitylogs, readme_alarm_pipeline [INFERRED 0.95]
- **State-Aware UI Position Management Loop** — templates_index_refreshstate, templates_index_updateui, templates_index_senduiaction, planning_phases_08_ui_management_08_context_state_aware_dashboard [INFERRED 0.95]

## Communities (142 total, 89 thin omitted)

### Community 0 - "SuperOrderEngine"
Cohesion: 0.06
Nodes (7): TestDirectSignalStrategy, SuperOrderEngine, TestOppositeSignalExit, test_level_cross_does_not_open_position_when_current_side_none(), TestPercentageCalculations, TestSmartExitFix, TestSuperOrderModify

### Community 1 - "FeelingState"
Cohesion: 0.06
Nodes (9): _do_write(), _do_write(), feeling_gate(), FeelingState, server_app(), TestDecision, TestEngineGuard, TestLifecycle (+1 more)

### Community 2 - "derive_entry_trigger"
Cohesion: 0.16
Nodes (5): calculate_quantity_from_margin(), derive_entry_trigger(), round_to_tick(), TestDeriveEntryTrigger, TestRoundToTick

### Community 4 - "mcp_server.py"
Cohesion: 0.08
Nodes (22): _call(), cancel_conditional_order(), cancel_super_order(), exit_conditional_order(), exit_super_order(), get_activity_logs(), get_feeling(), get_last_signal() (+14 more)

### Community 5 - "Milestone 0.1.0: Live Trading Foundation"
Cohesion: 0.06
Nodes (44): Broker Layer (broker_dhan.py), Flask Server (server.py), Super Order Engine, System Architecture Flow, TradingView Webhook Hub, Redis / Dhan Token Persistence Limitation, Hardcoded Scalping Thresholds, Dhan API v2 (+36 more)

### Community 6 - "route"
Cohesion: 0.04
Nodes (22): admin_dashboard(), auth_initiate(), auth_renew(), dashboard(), dhan_postback(), fund_limit(), get_accounts(), get_activity_logs() (+14 more)

### Community 7 - "server.py"
Cohesion: 0.07
Nodes (19): auth_callback(), _clear_exit_order_meta(), _ErrorBufferHandler, _find_level_key_by_value(), get_context(), _get_exit_order_meta(), get_feeling_route(), get_gtt_orders() (+11 more)

### Community 8 - "conditional_order"
Cohesion: 0.13
Nodes (13): resolve_call_itm(), resolve_index_spot(), resolve_put_itm(), conditional_order(), _feeling_block_for_entry(), get_itm(), get_margin(), _get_pending_trade() (+5 more)

### Community 11 - "_add_activity_log"
Cohesion: 0.11
Nodes (9): _add_activity_log(), cancel_conditional_orders(), _compute_zone(), dy_signal(), get_zone(), kill_broker_route(), manual_exit(), _post_to_slack_async() (+1 more)

### Community 12 - "json"
Cohesion: 0.26
Nodes (7): client(), test_api_accounts_get(), test_api_accounts_kill(), test_api_accounts_login(), test_api_accounts_lot_multiplier(), test_api_accounts_ping(), test_api_accounts_toggle()

### Community 13 - "test_modular_broker.py"
Cohesion: 0.11
Nodes (6): AuthServiceInterface, MarketDataServiceInterface, SafetyServiceInterface, SocketServiceInterface, Key Changes, test_interfaces_implemented_by_services()

### Community 14 - "broker/__init__.py"
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

### Community 20 - "test_feeling_gate.py"
Cohesion: 0.11
Nodes (8): read_json(), ReadResult, write_json(), derive_side(), normalize_feeling(), TestRead, TestWrite, writer()

### Community 26 - "NIFTY Options Trading Bot Strategy"
Cohesion: 0.20
Nodes (5): Direct Signal Strategy, Per-Underlying Market Feeling Gate, NIFTY Options Trading Bot Strategy, updateFeeling, updateFeelingsUI

### Community 27 - "TradingAgent MCP Bridge"
Cohesion: 0.20
Nodes (6): MCP Available Tool Catalog, TradingAgent MCP Bridge, SSE Stream Consumer Decision, Unauthenticated SSE and Last-Signal Endpoints, SSE Queue Blocking DoS Vulnerability, Model Context Protocol SDK Dependency

### Community 29 - "exit_conditional_order"
Cohesion: 0.18
Nodes (7): _add_to_history(), exit_conditional_order(), exit_super_order(), get_history(), _load_history(), _save_history(), _set_exit_order_meta()

### Community 31 - "Architecture Overview"
Cohesion: 0.25
Nodes (6): Conditional Order Engine Component, Operational Hardening PR #9a, Architecture Overview, Shared Constants Architecture, Super Order Engine Component, Native GTT Leg Management

### Community 33 - "DhanInstrumentService"
Cohesion: 0.11
Nodes (3): DhanInstrumentService, load_scrip_background(), test_zero_downtime_scrip_reload_preserves_maps()

### Community 35 - "updateUI"
Cohesion: 0.29
Nodes (8): State-Aware Dashboard Specification, WR-01 Incomplete State-Locking Controls, Phase 8 UI Delivery Summary, refreshState, sendUIAction, showBracketState, showGttState, updateUI

### Community 36 - "Phase 20: Groww Broker & Multi-Account Support - Context"
Cohesion: 0.17
Nodes (11): Canonical References, Deferred Ideas, Established Patterns, Existing Code Insights, Integration Points, Internal Architecture, Official Groww API Documentation, Phase 20: Groww Broker & Multi-Account Support - Context (+3 more)

### Community 37 - "Python Dependency Manifest"
Cohesion: 0.29
Nodes (6): State Management & Memory Tiering, Web UI Layer, Python Dependency Manifest, dhanhq SDK Dependency, Flask Framework Dependency, Redis Client Dependency

### Community 38 - "Antigravity Trader Terminal Dashboard"
Cohesion: 0.29
Nodes (7): CR-01 Backend Route Mismatch, cancelConditionalOrders, Antigravity Trader Terminal Dashboard, emergencyExit, Range Tracker UI, refreshTradeFeed, setConditionalOrders

### Community 44 - "TradingAgent Project Overview"
Cohesion: 0.33
Nodes (6): Broker Middleware Layer, Operational Data Flow, Redis Persistence Architecture, TradingAgent Project Overview, Stateful Ranking Engine, Webhook Interface Architecture

### Community 45 - "Phase 21: FlatTrade Broker Integration - Context"
Cohesion: 0.12
Nodes (15): Authentication & Daily Session Management, Canonical References, Deferred Ideas, Established Patterns, Existing Code Insights, Implementation Decisions, Instrument & Scrip Resolution, Integration Points (+7 more)

### Community 47 - "events"
Cohesion: 0.40
Nodes (3): _event_stream(), events(), stream()

### Community 48 - "test_conditional_entry.py"
Cohesion: 0.12
Nodes (10): arm_call(), make_engine(), test_postback_rejected_clears_pending_state(), test_reconciliation_sweep_arms_bracket_when_postback_dropped(), TestArmConditionalEntry, TestConditionalFill, TestFlush, TestModifyPendingAndSetLevels (+2 more)

### Community 50 - "Alarm Pipeline"
Cohesion: 0.50
Nodes (3): BrokerDisagreement Contract, Operator Alarm Pipeline, refreshActivityLogs

### Community 51 - "Pre-Commit Verification Checklist"
Cohesion: 0.50
Nodes (4): Pre-Commit Verification Checklist, Pre-Commit Import Check, Pre-Commit Strategy Unit Tests, Pre-Commit Syntax Check

### Community 57 - "DhanMarketDataService"
Cohesion: 0.13
Nodes (3): DhanMarketDataService, _parse_ltp_resp(), _try_direct()

### Community 58 - "DhanConditionalOrderService"
Cohesion: 0.16
Nodes (3): DhanConditionalOrderService, DhanSocketService, Tasks

### Community 91 - "test_money_safety_9a.py"
Cohesion: 0.17
Nodes (3): TestCorrelationIdUniqueness, TestHttpTimeouts, TestWebhookSecretFailClosed

### Community 92 - "write_text"
Cohesion: 0.33
Nodes (3): write_text(), _save_context(), set_context()

### Community 97 - "Key Changes"
Cohesion: 0.50
Nodes (3): Executive Summary, Key Changes, Summary: Phase 17 - Zero-Downtime Atomic Scrip Reload & Lot Map Guard

### Community 99 - "DhanSafetyService"
Cohesion: 0.14
Nodes (8): DhanSafetyService, Goal, Plan: Phase 18 - Kill Switch Super Order Leg Cancellation, Tasks, Executive Summary, Key Changes, Summary: Phase 18 - Kill Switch Super Order Leg Cancellation, test_kill_switch_cancels_super_order_legs_before_squareoff()

### Community 101 - "Plan: Phase 17 - Zero-Downtime Atomic Scrip Reload & Lot Map Guard"
Cohesion: 0.50
Nodes (3): Goal, Plan: Phase 17 - Zero-Downtime Atomic Scrip Reload & Lot Map Guard, Tasks

### Community 106 - "requests"
Cohesion: 0.15
Nodes (7): attempt_renew_token(), check_health(), main(), parse_csv(), simulate_today(), simulate_from_csv(), test_expiry_selection_dhan_client()

### Community 111 - "test_multi_broker.py"
Cohesion: 0.18
Nodes (6): DummyRedis, test_multi_broker_account_tag_override(), test_multi_broker_fail_safe_isolation(), test_multi_broker_lot_multipliers(), test_multi_broker_parallel_dispatch(), test_multi_broker_toggle_and_statuses()

### Community 112 - "GrowwAuthService"
Cohesion: 0.21
Nodes (3): GrowwAuthService, test_groww_auth_service_dry_run(), test_groww_order_service_dry_run()

### Community 117 - "FlatTradeOrderService"
Cohesion: 0.15
Nodes (6): FlatTradeAuthService, FlatTradeInstrumentService, FlatTradeOrderService, Goal, the agent's Discretion, test_flattrade_order_service_dry_run()

### Community 120 - "ConditionalOrderEngine"
Cohesion: 0.12
Nodes (3): ConditionalOrderEngine, test_reconciliation_missing_pending_protection_alarms_and_flags_failed(), TestMonitorGuard

### Community 123 - "simulate_trading.py"
Cohesion: 0.23
Nodes (3): MockBroker, simulate(), test_no_untimed_requests_in_broker_package()

### Community 125 - "2. Component Redesigns & Upgrades"
Cohesion: 0.25
Nodes (7): 1. Layout Architecture (1440px Cockpit Grid), 2. Component Redesigns & Upgrades, A. Broker Status Badges (Eliminate Emojis), B. Emergency Kill Switch Safety Lock, C. Active Bracket & GTT Slider, D. Clean Up Dead DOM, Page Design Specification: Trader Terminal (`/`)

### Community 127 - "Design System Master File: Antigravity Trader"
Cohesion: 0.33
Nodes (5): 1. Visual Foundation & Color Tokens, 2. Typography & Tabular Number Rules, 3. High-Performance Glassmorphism & Elevation, 4. UI/UX Pre-Delivery Checklist, Design System Master File: Antigravity Trader

### Community 129 - ".get_account_statuses"
Cohesion: 0.33
Nodes (3): Goal, Plan: Phase 20 - Plan 02: MultiBrokerManager & Dual-Broker Routing, Tasks

### Community 130 - "Implementation Decisions"
Cohesion: 0.40
Nodes (5): Groww Order Execution Architecture, Implementation Decisions, Instrument & Scrip Resolution, Multi-Account Order Routing & Allocation, the agent's Discretion

### Community 131 - "Tasks"
Cohesion: 0.50
Nodes (3): Goal, Plan: Phase 19 - Approach C Autonomous Reconciliation Safety Net, Tasks

### Community 133 - "test_gtt_orders.py"
Cohesion: 0.29
Nodes (3): client(), test_gtt_orders_success(), test_gtt_orders_unauthorized()

### Community 134 - "Key Changes"
Cohesion: 0.50
Nodes (3): Executive Summary, Key Changes, Summary: Phase 19 - Approach C Autonomous Reconciliation Safety Net

### Community 136 - "Goal"
Cohesion: 0.50
Nodes (3): Goal, Plan: Phase 20 - Plan 01: Groww Broker Client & Dedicated Services, Tasks

### Community 138 - "Plan: Phase 21 - Plan 02: Multi-Broker Admin Dashboard UI & Global Control"
Cohesion: 0.50
Nodes (3): Goal, Plan: Phase 21 - Plan 02: Multi-Broker Admin Dashboard UI & Global Control, Tasks

## Knowledge Gaps
- **43 isolated node(s):** `updateFeeling`, `Direct Signal Strategy`, `Unauthenticated SSE and Last-Signal Endpoints`, `SSE Queue Blocking DoS Vulnerability`, `Operational Hardening PR #9a` (+38 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 603 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **89 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `DhanClient` connect `DhanClient` to `SuperOrderEngine`, `.get_account_statuses`, `Goal`, `DhanOrderService`, `test_expiry_selection_only_today_available`, `test_modular_broker.py`, `broker/__init__.py`, `TestLtpSpec`, `TestSecurityIdFailClosed`, `DhanInstrumentService`, `Phase 21: FlatTrade Broker Integration - Context`, `DhanAuthService`, `setter`, `DhanMarketDataService`, `DhanConditionalOrderService`, `.get_limits`, `test_dhan_client_facade_delegation`, `load_scrip_background`, `Key Changes`, `DhanSafetyService`, `Summary: Phase 13 - Modular Broker Facade & Dedicated Services`, `Plan: Phase 17 - Zero-Downtime Atomic Scrip Reload & Lot Map Guard`, `requests`, `Plan: Phase 13 - Modular Broker Facade & Dedicated Services`, `test_dhan_client_offline_initialization`?**
  _High betweenness centrality (0.122) - this node is a cross-community bridge._
- **Are the 23 inferred relationships involving `DhanClient` (e.g. with `DhanAuthService` and `ExchangeSegment`) actually correct?**
  _`DhanClient` has 23 INFERRED edges - model-reasoned connections that need verification._
- **What connects `updateFeeling`, `Direct Signal Strategy`, `Unauthenticated SSE and Last-Signal Endpoints` to the rest of the system?**
  _43 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `SuperOrderEngine` be split into smaller, more focused modules?**
  _Cohesion score 0.06497175141242938 - nodes in this community are weakly interconnected._
- **Why does `MultiBrokerManager` connect `MultiBrokerManager` to `.get_account_statuses`, `Implementation Decisions`, `Phase 20: Groww Broker & Multi-Account Support - Context`, `server.py`, `Phase 21: FlatTrade Broker Integration - Context`, `test_multi_broker.py`, `FlatTradeOrderService`, `.place_super_order`, `.register_broker`?**
  _High betweenness centrality (0.099) - this node is a cross-community bridge._
- **Are the 5 inferred relationships involving `MockDhanClient` (e.g. with `TestArmConditionalEntry` and `TestConditionalFill`) actually correct?**
  _`MockDhanClient` has 5 INFERRED edges - model-reasoned connections that need verification._
- **Should `FeelingState` be split into smaller, more focused modules?**
  _Cohesion score 0.06359189378057302 - nodes in this community are weakly interconnected._