# TODOS

## Conditional entry: Approach C reconciliation safety net
- **What:** A periodic reconciliation sweep that detects filled-but-unprotected conditional
  positions and either arms the bracket idempotently, raises a loud alarm, or force-exits.
- **Why:** v1 of the conditional index-touch entry ships single-postback (see design doc,
  Issue 2 / premise 8). If Dhan drops the entry-fill postback, the bracket never arms, no
  alarm fires, and the bot holds an unprotected long it does not know exists. Full-premium
  blast radius.
- **Pros:** Eliminates the scariest silent failure mode; redundant fill detection.
- **Cons:** More code; needs broker order/position polling; arming must stay idempotent so the
  sweep and the postback never double-arm.
- **Context:** Deferred Approach C from the design doc. The conditional path currently has no
  redundant fill detector: the WS listener `_handle_live_order_update` routes only through
  `super_order_engine` (server.py:168), and the only conditional fill path is the single HTTP
  `/dhan-postback` → `handle_postback` (server.py:1465). Reuse the existing 2s polling monitor
  (`ConditionalOrderEngine.monitor_positions`, conditional_order_engine.py:299) as the host.
- **Depends on / blocked by:** v1 conditional index-touch entry shipped.

## Tests: no-network DhanClient constructor for tests
- **What:** A way to construct `DhanClient` in tests without spawning the background
  scrip-master download thread (network).
- **Why:** `DhanClient.__init__` (broker_dhan.py:81-91) always starts a daemon thread that
  downloads the scrip CSV. `tests/test_smart_exit_fix.py::test_broker_pending_orders_flexible_keys`
  and `tests/test_ltp_spec.py` construct a real `DhanClient()`, so the suite makes (or attempts)
  live network calls. Flaky offline, slow, and a latent way to hit the broker from a test run.
- **How:** add a `load_scrip=True` flag (or env guard) to `__init__` so tests can skip the
  thread; update those two tests to use it.
- **Found by:** /qa on 2026-05-26.

## Sims: update backtest to current process_signal signature
- **What:** `simulations/simulate_trading.py:150` calls
  `process_signal(underlying, transaction_type, int(timeframe), leg, now_override=dt_obj)` —
  the OLD signature. Current is `process_signal(underlying, itm, signal_type, mode, leg_data)`.
- **Why:** the backtest/simulation harness is broken against the current engine. Not run by
  pytest, so it failed silently.
- **How:** rewrite the sim's call to resolve an ITM and use the current signature, or point the
  sim at a thin adapter.
- **Found by:** /qa on 2026-05-26.
