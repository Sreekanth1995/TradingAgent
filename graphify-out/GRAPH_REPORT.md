# Graph Report - TradingAgent  (2026-10-22)

## Corpus Check
- 102 files · ~67,527 words
- Verdict: corpus is large enough that graph structure adds value.
- Unclassified: 7 file(s) not represented in the graph (top: (none) 5, .example 1, .pine 1)

## Summary
- 1179 nodes · 2231 edges · 107 communities (38 shown, 69 thin omitted)
- Extraction: 89% EXTRACTED · 11% INFERRED · 0% AMBIGUOUS · INFERRED: 238 edges (avg confidence: 0.9)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `35ef1042`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- SuperOrderEngine
- FeelingState
- derive_entry_trigger
- test_conditional_entry.py
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
- __init__.py
- trade_feed.py
- TestLtpSpec
- test_phase4_positions.py
- Tech Stack
- ._get_state
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
- Phase 20: Groww Broker & Multi-Account Support - Context
- Python Dependency Manifest
- Antigravity Trader Terminal Dashboard
- TestRoutes
- ConditionalOrderEngine
- InstrumentServiceInterface
- Any
- TradingAgent Project Overview
- .monitor_positions
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
- feeling_gate
- deploy_vultr.sh
- pre-commit-check.sh
- run_test_loop.sh
- Hardcoded Index Mapping
- Coding and Logging Standards
- MCP Server
- No-Network DhanClient Test Harness
- test_feeling_gate.py
- validate_sl_target
- .get_pending_protection
- test_money_safety_9a.py
- write_text
- test_dhan_client_facade_delegation
- load_scrip_background
- Key Changes
- scrip_status
- Plan: Phase 18 - Kill Switch Super Order Leg Cancellation
- Summary: Phase 13 - Modular Broker Facade & Dedicated Services
- Plan: Phase 17 - Zero-Downtime Atomic Scrip Reload & Lot Map Guard
- Summary: Phase 18 - Kill Switch Super Order Leg Cancellation
- Plan: Phase 13 - Modular Broker Facade & Dedicated Services
- test_dhan_client_offline_initialization
- broker_mock.py

## God Nodes (most connected - your core abstractions)
1. `DhanClient` - 91 edges
2. `MockDhanClient` - 58 edges
3. `ConditionalOrderEngine` - 43 edges
4. `SuperOrderEngine` - 40 edges
5. `DhanOrderService` - 35 edges
6. `FeelingState` - 28 edges
7. `DhanInstrumentService` - 26 edges
8. `_call()` - 23 edges
9. `OrderServiceInterface` - 22 edges
10. `DhanMarketDataService` - 21 edges

## Surprising Connections (you probably didn't know these)
- `Executive Summary` --references--> `DhanClient`  [INFERRED]
  .planning/phases/13-modular-broker-facade/13-SUMMARY.md → broker/client.py
- `Tasks` --references--> `DhanClient`  [INFERRED]
  .planning/phases/17-zero-downtime-scrip-reload/17-PLAN.md → broker/client.py
- `Key Changes` --references--> `DhanSafetyService`  [INFERRED]
  .planning/phases/18-kill-switch-super-order-legs/18-SUMMARY.md → broker/safety_service.py
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

## Communities (107 total, 69 thin omitted)

### Community 0 - "SuperOrderEngine"
Cohesion: 0.07
Nodes (7): TestDirectSignalStrategy, SuperOrderEngine, TestOppositeSignalExit, test_level_cross_does_not_open_position_when_current_side_none(), TestPercentageCalculations, TestSmartExitFix, TestSuperOrderModify

### Community 1 - "FeelingState"
Cohesion: 0.11
Nodes (4): FeelingState, TestEngineGuard, TestLifecycle, TestPersistence

### Community 2 - "derive_entry_trigger"
Cohesion: 0.20
Nodes (4): derive_entry_trigger(), round_to_tick(), TestDeriveEntryTrigger, TestRoundToTick

### Community 3 - "test_conditional_entry.py"
Cohesion: 0.12
Nodes (10): arm_call(), make_engine(), test_postback_rejected_clears_pending_state(), test_reconciliation_sweep_arms_bracket_when_postback_dropped(), TestArmConditionalEntry, TestConditionalFill, TestFlush, TestModifyPendingAndSetLevels (+2 more)

### Community 4 - "mcp_server.py"
Cohesion: 0.08
Nodes (21): _call(), cancel_conditional_order(), cancel_super_order(), exit_conditional_order(), exit_super_order(), get_activity_logs(), get_feeling(), get_last_signal() (+13 more)

### Community 5 - "Milestone 0.1.0: Live Trading Foundation"
Cohesion: 0.06
Nodes (44): Broker Layer (broker_dhan.py), Flask Server (server.py), Super Order Engine, System Architecture Flow, TradingView Webhook Hub, Redis / Dhan Token Persistence Limitation, Hardcoded Scalping Thresholds, Dhan API v2 (+36 more)

### Community 6 - "route"
Cohesion: 0.05
Nodes (19): auth_callback(), auth_renew(), dashboard(), dhan_postback(), fund_limit(), get_broker_orders(), get_broker_positions(), get_feeling_route() (+11 more)

### Community 7 - "server.py"
Cohesion: 0.09
Nodes (17): auth_initiate(), _clear_exit_order_meta(), _ErrorBufferHandler, _find_level_key_by_value(), get_activity_logs(), get_context(), _get_exit_order_meta(), _get_level_value_by_key() (+9 more)

### Community 8 - "conditional_order"
Cohesion: 0.10
Nodes (14): index_id_for(), calculate_quantity_from_margin(), resolve_call_itm(), resolve_index_spot(), resolve_put_itm(), conditional_order(), _feeling_block_for_entry(), get_itm() (+6 more)

### Community 11 - "_add_activity_log"
Cohesion: 0.10
Nodes (10): _add_activity_log(), cancel_conditional_orders(), _compute_zone(), _contra_pending_warnings(), dy_signal(), get_zone(), manual_exit(), _post_to_slack_async() (+2 more)

### Community 12 - "json"
Cohesion: 0.09
Nodes (10): attempt_renew_token(), check_health(), main(), BacktestEngine, parse_csv(), simulate_today(), MockBroker, simulate() (+2 more)

### Community 13 - "test_modular_broker.py"
Cohesion: 0.08
Nodes (11): AuthServiceInterface, MarketDataServiceInterface, SafetyServiceInterface, SocketServiceInterface, DhanMarketDataService, DhanSafetyService, DhanSocketService, Tasks (+3 more)

### Community 14 - "__init__.py"
Cohesion: 0.15
Nodes (8): BrokerDisagreement(), ExchangeSegment, OrderType, ProductType, TransactionType, Validity, index_name_for(), is_index_id()

### Community 15 - "trade_feed.py"
Cohesion: 0.15
Nodes (11): cancel_super_order(), dhan_webhook(), _get_pending_trade(), get_state(), get_trade_feed(), skip_trade(), _connect(), get_recent_trades() (+3 more)

### Community 17 - "test_phase4_positions.py"
Cohesion: 0.19
Nodes (6): _get_active_positions(), client(), test_get_active_positions_empty(), test_get_active_positions_missing_ltp(), test_get_active_positions_with_data(), test_get_state_endpoint_mock()

### Community 18 - "Tech Stack"
Cohesion: 0.40
Nodes (4): Backend, DevOps, Frontend, Tech Stack

### Community 20 - "read_json"
Cohesion: 0.15
Nodes (6): read_json(), ReadResult, write_json(), TestRead, TestWrite, writer()

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
Cohesion: 0.12
Nodes (3): DhanInstrumentService, load_scrip_background(), test_zero_downtime_scrip_reload_preserves_maps()

### Community 35 - "updateUI"
Cohesion: 0.29
Nodes (8): State-Aware Dashboard Specification, WR-01 Incomplete State-Locking Controls, Phase 8 UI Delivery Summary, refreshState, sendUIAction, showBracketState, showGttState, updateUI

### Community 36 - "Phase 20: Groww Broker & Multi-Account Support - Context"
Cohesion: 0.12
Nodes (16): Canonical References, Deferred Ideas, Established Patterns, Existing Code Insights, Groww Order Execution Architecture, Implementation Decisions, Instrument & Scrip Resolution, Integration Points (+8 more)

### Community 37 - "Python Dependency Manifest"
Cohesion: 0.29
Nodes (6): State Management & Memory Tiering, Web UI Layer, Python Dependency Manifest, dhanhq SDK Dependency, Flask Framework Dependency, Redis Client Dependency

### Community 38 - "Antigravity Trader Terminal Dashboard"
Cohesion: 0.29
Nodes (7): CR-01 Backend Route Mismatch, cancelConditionalOrders, Antigravity Trader Terminal Dashboard, emergencyExit, Range Tracker UI, refreshTradeFeed, setConditionalOrders

### Community 44 - "TradingAgent Project Overview"
Cohesion: 0.33
Nodes (6): Broker Middleware Layer, Operational Data Flow, Redis Persistence Architecture, TradingAgent Project Overview, Stateful Ranking Engine, Webhook Interface Architecture

### Community 45 - ".monitor_positions"
Cohesion: 0.15
Nodes (7): Goal, Plan: Phase 19 - Approach C Autonomous Reconciliation Safety Net, Tasks, Executive Summary, Key Changes, Summary: Phase 19 - Approach C Autonomous Reconciliation Safety Net, TestMonitorGuard

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
Cohesion: 0.13
Nodes (5): derive_side(), normalize_feeling(), server_app(), TestContraPending, TestSSEInvisibility

### Community 91 - "test_money_safety_9a.py"
Cohesion: 0.07
Nodes (8): client(), test_gtt_orders_success(), test_gtt_orders_unauthorized(), TestCorrelationIdUniqueness, TestHttpTimeouts, TestSlackWebhookGating, fake_post(), TestWebhookSecretFailClosed

### Community 92 - "write_text"
Cohesion: 0.33
Nodes (3): _do_write(), write_text(), _do_write()

### Community 97 - "Key Changes"
Cohesion: 0.50
Nodes (3): Executive Summary, Key Changes, Summary: Phase 17 - Zero-Downtime Atomic Scrip Reload & Lot Map Guard

### Community 99 - "Plan: Phase 18 - Kill Switch Super Order Leg Cancellation"
Cohesion: 0.40
Nodes (3): Goal, Plan: Phase 18 - Kill Switch Super Order Leg Cancellation, Tasks

### Community 101 - "Plan: Phase 17 - Zero-Downtime Atomic Scrip Reload & Lot Map Guard"
Cohesion: 0.50
Nodes (3): Goal, Plan: Phase 17 - Zero-Downtime Atomic Scrip Reload & Lot Map Guard, Tasks

### Community 102 - "Summary: Phase 18 - Kill Switch Super Order Leg Cancellation"
Cohesion: 0.50
Nodes (3): Executive Summary, Key Changes, Summary: Phase 18 - Kill Switch Super Order Leg Cancellation

## Knowledge Gaps
- **43 isolated node(s):** `updateFeeling`, `Direct Signal Strategy`, `Unauthenticated SSE and Last-Signal Endpoints`, `SSE Queue Blocking DoS Vulnerability`, `Operational Hardening PR #9a` (+38 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 481 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **69 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `DhanClient` connect `DhanClient` to `DhanOrderService`, `test_modular_broker.py`, `__init__.py`, `TestLtpSpec`, `TestSecurityIdFailClosed`, `DhanInstrumentService`, `DhanAuthService`, `.test_broker_pending_orders_flexible_keys`, `setter`, `DhanConditionalOrderService`, `test_dhan_client_facade_delegation`, `load_scrip_background`, `Key Changes`, `scrip_status`, `Summary: Phase 13 - Modular Broker Facade & Dedicated Services`, `Plan: Phase 17 - Zero-Downtime Atomic Scrip Reload & Lot Map Guard`, `Plan: Phase 13 - Modular Broker Facade & Dedicated Services`, `test_dhan_client_offline_initialization`, `broker_mock.py`?**
  _High betweenness centrality (0.112) - this node is a cross-community bridge._
- **Are the 20 inferred relationships involving `DhanClient` (e.g. with `DhanAuthService` and `ExchangeSegment`) actually correct?**
  _`DhanClient` has 20 INFERRED edges - model-reasoned connections that need verification._
- **What connects `updateFeeling`, `Direct Signal Strategy`, `Unauthenticated SSE and Last-Signal Endpoints` to the rest of the system?**
  _43 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `SuperOrderEngine` be split into smaller, more focused modules?**
  _Cohesion score 0.06713286713286713 - nodes in this community are weakly interconnected._
- **Why does `MockDhanClient` connect `MockDhanClient` to `SuperOrderEngine`, `FeelingState`, `test_conditional_entry.py`, `server.py`, `.get_ltp`, `.get_itm_contract`, `.monitor_positions`, `.cancel_super_order`, `.get_completed_trades`, `.get_index_id`, `.get_index_spot_fallback`, `.get_multi_margin_calculator`, `.get_order_status`, `.margin_calculator`, `.modify_super_entry_leg`, `.modify_super_sl_leg`, `.modify_super_target_leg`, `test_feeling_gate.py`, `.get_pending_protection`, `.place_order`, `._alarm`, `broker_mock.py`?**
  _High betweenness centrality (0.091) - this node is a cross-community bridge._
- **Are the 5 inferred relationships involving `MockDhanClient` (e.g. with `TestArmConditionalEntry` and `TestConditionalFill`) actually correct?**
  _`MockDhanClient` has 5 INFERRED edges - model-reasoned connections that need verification._
- **Should `FeelingState` be split into smaller, more focused modules?**
  _Cohesion score 0.11491935483870967 - nodes in this community are weakly interconnected._