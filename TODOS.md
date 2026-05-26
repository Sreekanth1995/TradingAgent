# TODOS

## Completed in PR #9a (alarm-pipe foundation, 2026-05-27)
- **Broker: refuse to invent a security_id when strike not in scrip map** —
  `_get_security_id` now returns `None` on a `scrip_map` miss instead of the
  dummy `"1333"`. Fires a `🚨 SCRIP MISS` alarm via the new activity-log
  callback. (broker_dhan.py)
- **Operational: surface 🚨 alarms to a destination a human actually checks** —
  `_add_activity_log` posts any `🚨`-prefixed message to `SLACK_WEBHOOK_URL`
  (bounded 2-worker pool, 50-slot semaphore, drop-oldest under storm). The
  dashboard polls `/activity-logs` every 5 s and renders a sticky red banner
  whenever the most recent 20 entries contain a `🚨` line. (server.py,
  templates/index.html)
- **Conditional entry: confirm activity_log_fn actually surfaces alarms to a
  human** — superseded by the Slack + dashboard banner work above.
- **Broker: add HTTP timeouts to all requests calls** — every `requests.{get,
  post,put,delete}` in `broker_dhan.py` now passes `timeout=(5, 10)`. No more
  TCP black-hole hangs that would freeze gunicorn worker threads.
- **Security: WEBHOOK_SECRET still has public default in server.py** —
  `SECRET` is fail-closed at boot. Missing or whitespace-only env var raises
  `RuntimeError` on import, mirroring the `mcp_server.py` fix from commit
  d2f0adb.

Also shipped (not previously tracked in TODOS):
- **BrokerDisagreement helper** — canonical fail-closed return shape for any
  broker/engine disagreement (`{success: False, status: "broker_disagreement",
  reason, alarm_msg, error, ...fields}`). Used by every fail-closed contract
  added in this PR and feeds the dashboard alarm taxonomy.
- **DhanClient.activity_log_fn callback** — broker-layer alarm sink wired
  through to `_add_activity_log` so broker-internal fail-closed paths reach
  the same dashboard + Slack pipe.
- **correlationId is now `b{ms-base36}{uuid6}` (~15 chars)** — old `b_{int(time.time())}`
  collided under 9:15 IST opening bursts (3 underlyings × CALL/PUT in the same
  second). PR #9b idempotency relies on uniqueness.

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

## Conditional entry: handle REJECTED/CANCELLED postback for ENTRY: userNote
- **Priority:** P0
- **What:** `handle_postback` only branches on `orderStatus in ("TRADED", "PART_TRADED")` for the
  conditional-fill (ENTRY:) path. If the alert fires but the BUY order is rejected by the
  exchange (circuit limit, insufficient margin at fire-time, etc.), the postback comes with
  `orderStatus=REJECTED` or `CANCELLED` and `userNote=ENTRY:...` and falls through entirely.
- **Why:** PENDING_* state lingers forever, `pending_protection` lives until TTL (~24h). Next
  day the operator tries to place a new entry and is rejected at server.py:1326 with "already
  has open/pending position" — **wedged and cannot trade that underlying until they manually
  wipe state.**
- **How:** in `handle_postback`, when `order_status in ('REJECTED','CANCELLED')` AND `user_note`
  starts with `ENTRY:`, call something equivalent to `cancel_pending_entry(underlying)` to wipe
  the PENDING state and consume `pending_protection`. Surface a loud activity-log alarm.
- **Found by:** /ship adversarial review on 2026-05-26.

## Conditional entry: validate lot_size at fill time, refuse to arm if zero
- **Priority:** P0
- **What:** `_handle_conditional_fill` calls `lot_size = self.broker.lot_map.get(opt_sec_id) or 0`
  then `_extract_filled_lots(data, lot_size, requested_lots)` falls back to `requested_lots` when
  lot_size is 0. If the scrip master reloaded between arm and fill (clearing/changing lot_map),
  the bracket can be armed for more lots than were actually filled.
- **Why:** Bracket SELL larger than the live holding creates a naked short on the difference
  when the SL/Target fires. Probability low (scrip reload during fill window) but
  consequence is real money.
- **How:** treat `lot_size == 0` as fail-closed: log a loud alarm, do NOT arm the bracket,
  store the unprotected position in state with a `protection_failed` flag, and require
  manual reconciliation. Better than arming oversized.
- **Found by:** /ship adversarial review on 2026-05-26.

## Postback: move secret from URL query to HMAC-signed header
- **Priority:** P1
- **What:** `/dhan-postback` validates the secret via `?secret=` query string
  (`server.py:1499-1502`). Query-string secrets are logged by reverse proxies, nginx, CDN
  access logs, and any HTTP traffic mirror.
- **Why:** A leaked secret lets an attacker post forged postbacks with a sniffed
  `userNote=ENTRY:...` correlation id, consuming legitimate `pending_protection` before the
  real fill arrives → naked position. Forged postbacks could also wipe engine state.
- **How:** move the secret to a request header (`X-Webhook-Secret`) or, better, HMAC-sign the
  request body and verify the signature. Confirm Dhan supports either; if not, document the
  log-redaction posture explicitly.
- **Found by:** /ship adversarial review on 2026-05-26.

## Exit: super_order_engine.exit_super_order clears state even when broker SELL fails
- **Priority:** P0
- **What:** `super_order_engine.py:210-220` calls `broker.place_order(SELL)`, ignores the
  return value, cancels all three bracket legs, calls `_clear_state(underlying)`, returns
  `{"success": True}` unconditionally.
- **Why:** Operator hits "Exit". Broker SELL fails (auth blip, 5xx, network). Bracket legs
  cancelled anyway → no protection. State cleared → polling monitor skips → dashboard
  shows no position. Long position remains live in the broker, unguarded, potentially
  overnight = full premium decay.
- **How:** check `exit_resp.get('success')` BEFORE the cancels and state-wipe. On failure,
  leave bracket legs alive (they're still protecting), keep state, fire `🚨 EXIT FAILED`.
- **Found by:** /design-review on 2026-05-27.

## Kill switch: cancels bracket legs via wrong endpoint, leaves them alive
- **Priority:** P0
- **What:** `broker_dhan.py:1021-1040` `kill_switch` step 2 iterates pending orders and
  calls `self.cancel_order(order_id)` (the regular `/orders/{id}` endpoint), not
  `cancel_super_order(order_id, leg)` (the `/super/orders/{id}/{LEG}` endpoint). After
  kill_switch, market SELL flattens positions but the Super Order's TARGET_LEG +
  STOP_LOSS_LEG survive at Dhan. When premium next crosses a trigger, the orphan SELL
  fires → NAKED SHORT on an index option.
- **Why:** Operator's most dangerous button leaves the worst possible state behind. The
  position is flat but the broker thinks there's still a bracket; next trigger = naked.
- **How:** detect super-order legs (via `get_super_orders` or order-type field), call
  `cancel_super_order(...)` per leg. Verify all legs are confirmed cancelled before
  clearing engine state.
- **Found by:** /design-review on 2026-05-27.

## Immediate conditional-order: store pending_protection BEFORE placing the BUY
- **Priority:** P0
- **What:** `server.py:1466-1479` (`/conditional-order` no-`entry_index` path) calls
  `handle_signal('B')` which immediately fires a MARKET BUY, THEN calls
  `store_pending_protection(order_id, ...)`. Race window: a fast fill postback can arrive
  before the route's next line runs.
- **Why:** Dhan can process market orders in milliseconds; postback arrives first; the
  postback handler runs `get_pending_protection(order_id)` → None → no bracket armed.
  Polling monitor also fails because state lacks `idx_sl_level`/`idx_target_level`.
- **How:** mirror the safe ordering already used in `arm_conditional_entry`: pre-generate
  a correlation_id, `store_pending_protection(correlation_id, ...)` BEFORE the BUY, then
  fold order_id into the pending record on broker success.
- **Found by:** /design-review on 2026-05-27.

## Broker: place_super_order 500-retry can double-place orders
- **Priority:** P0
- **What:** `broker_dhan.py:1525-1537` retries on 500 with the SAME payload + SAME
  correlationId, without checking if the first attempt already landed. If Dhan accepts
  the order but 5xx's the response (slow DB commit, lossy backplane), the retry creates
  a SECOND order = 2× position, 2× bracket, 2× margin.
- **Why:** Doubling a real-money trade is unrecoverable. The engine only stores the
  retry's order_id, so the first one is orphaned at the broker.
- **How:** before retry, GET `/super/orders` filtered by correlationId; only retry if
  the order is NOT already present. Document correlationId-dedup behavior with Dhan
  support to confirm what the broker guarantees.
- **Found by:** /design-review on 2026-05-27.

## Broker: lot_map silent fallback to 1-unit lot in DhanClient (still present after PR #7)
- **Priority:** P0
- **What:** `broker_dhan.py:549` (`_place_order`) and `broker_dhan.py:1458` (super order)
  do `lot_size = self.lot_map.get(sec_id, 1)`. PR #7 fixed conditional-engine to fail
  closed on a lot_map miss; the broker-layer fallback persists for the super-order path.
- **Why:** If `/reload-scrip` is in flight (zeroes lot_map for 5-15s), or scrip CSV is
  partial, a super-order BUY places 1 UNIT instead of 1 LOT. Worse asymmetry on exit:
  SELL 1 unit when 25 are live → 24 units of naked long. Conditional-entry is safe;
  super-order is not.
- **How:** mirror conditional-engine contract: `lot_size = self.lot_map.get(str(sec_id));
  if not lot_size: return {"success": False, "error": "lot_size unknown"}`.
- **Found by:** /design-review on 2026-05-27.

## Scrip reload: zero-downtime atomic swap (don't blank lot_map mid-flight)
- **Priority:** P0
- **What:** `server.py:1308-1311` (`/reload-scrip`) sets `broker.lot_map = {}` then calls
  `_load_scrip_master()` which blocks 5-15 s parsing the CSV. Every concurrent caller of
  `lot_map.get(...)` during the window sees empty.
- **Why:** compounds with the lot-map silent-fallback (see prior P0). Operator hits the
  reload button at 9:14:55 IST, TV alert lands at 9:14:58 → wrong-sized order.
- **How:** build new maps into local dicts in the reload, then atomic-swap
  (`broker.lot_map = new_map`). Gate `/reload-scrip` with a `scrip_reload_lock` to refuse
  concurrent reloads.
- **Found by:** /design-review on 2026-05-27.

## Concurrency: gate state mutations with atomic upsert (TOCTOU class)
- **Priority:** P1
- **What:** `_get_state → mutate → _set_state` in both engines is non-atomic. Multiple
  threads (Flask route, monitor thread at 2s tick, WS callback, HTTP postback) race on
  the same Redis key. Last-writer-wins erases fields silently.
- **Why:** PR #8 fixed one TOCTOU for the feeling-gate read. The engines still have this
  everywhere. Worst case: monitor reads state at T=0, fires exit SELL at T+50ms; in the
  same window a GTT-fill postback clears state. Bot then SELLs against a flat position
  = naked short.
- **How:** Redis WATCH/MULTI/EXEC or Lua atomic upsert; or per-underlying `threading.RLock`
  around get-modify-set. Also add `exit_in_progress` atomic flag set BEFORE any broker
  exit call so a concurrent tick skips.
- **Found by:** /design-review on 2026-05-27.

## Concurrency: signal_memory (and friends) break under multi-worker gunicorn
- **Priority:** P1
- **What:** `server.py:38-43` `signal_memory`, plus `_pending_trades`, `_exit_order_meta`,
  `last_signal_storage`, `sse_clients`, `activity_logs`, `_error_log_buffer` are all
  module-level dicts/lists. With Redis absent (the documented fallback), each gunicorn
  worker has its own state.
- **Why:** Scaling to >1 worker silently breaks dedup, pending feed-id tracking, exit
  fill audit, SSE broadcast, alarm log. Single-worker today; latent footgun for "I scaled
  to 4 workers because traffic spiked at expiry."
- **How:** hard-require Redis at startup when gunicorn workers > 1; OR persist
  signal_memory to SQLite (trade_feed.db already present); OR consolidate into Redis
  with hard error if Redis is down.
- **Found by:** /design-review on 2026-05-27.

## SIGTERM handler: avoid mid-mutation daemon-thread kills on deploy
- **Priority:** P1
- **What:** `monitor_thread = threading.Thread(target=..., daemon=True)`. gunicorn
  graceful shutdown sends SIGTERM; daemons die abruptly. No `signal.signal(SIGTERM, ...)`
  anywhere in the codebase.
- **Why:** Deploy during active trade leaves the monitor mid-mutation. Worst case:
  monitor placed exit SELL, didn't reach `_clear_state` before SIGTERM → new process
  starts with stale state → next tick re-fires SL → second SELL on flat position.
- **How:** register `signal.signal(SIGTERM, handler)` that sets a `threading.Event()`;
  monitor checks at loop boundaries; broker calls wrapped in `try/finally`. OR write
  `exit_in_progress=order_id` BEFORE the broker call so restart can reconcile.
- **Found by:** /design-review on 2026-05-27.

## /health: surface degraded state for monitoring probes
- **Priority:** P1
- **What:** `/health` reports only `broker_initialized`, `engine_initialized`,
  `feelings_store`. Missing: `redis_alive`, `scrip_count`, `scrip_age_hours`,
  `monitor_heartbeat_age`, `ws_connected`, `last_signal_age`, `token_age_hours`. Uptime
  probes return 200 when half the bot is dead.
- **Why:** an uptime probe (UptimeRobot, Pingdom, simple cron) is the operator's only
  safety net while away from the dashboard. It needs to actually fire on degradation.
- **How:** extend the response dict with the fields above; return HTTP 503 when any
  critical sub-component (Redis down, monitor stalled, ws disconnected during market
  hours, token age > 23h) is degraded.
- **Found by:** /design-review on 2026-05-27.

## Startup: reconcile engine state against broker positions
- **Priority:** P1
- **What:** server.py boot does not query `broker.get_positions()` to verify engine state
  matches reality. If Redis was flushed or memory-mode was used between sessions, the
  bot starts with empty engine state while the broker still holds positions.
- **Why:** silent "the bot owns an unprotected position it doesn't know about" — exactly
  the Approach C blast radius, caused by restart instead of dropped postback.
- **How:** at startup, walk broker positions; for each `netQty != 0`, either reconstruct
  engine state (from sec_id → underlying mapping) or emit `🚨 UNRECONCILED POSITION`
  requiring operator action. Refuse to accept new signals until reconciled.
- **Found by:** /design-review on 2026-05-27.

## Auth: track and proactively alarm on Dhan token expiry
- **Priority:** P1
- **What:** `access_token` is opaque; `_sync_token_from_redis` only runs reactively on
  401. No `expires_at`, no scheduled refresh, no "expires in 2h" warning. Dhan tokens
  are 24h.
- **Why:** silent failure ~once every 24h until the operator manually re-auths. During
  the gap, /webhook signals queue as PENDING in trade_feed but never place.
- **How:** on `consume_consent` success, store `access_token_acquired_at` in Redis.
  Surface `token_age_hours` in `/health`. Emit `🚨 TOKEN EXPIRES SOON` when > 22h.
- **Found by:** /design-review on 2026-05-27.

## Tests: broker_dhan.py has < 5% direct coverage
- **Priority:** P1
- **What:** 1821-line module with only tangential test coverage. Untested critical paths:
  place_order 401-retry, place_super_order, modify_super_*, cancel_super_order,
  place_conditional_order, kill_switch, `_load_scrip_master`, token refresh, WS
  reconnect/backoff.
- **Why:** the real-money path with the least testing. A Dhan API contract change
  (response shape, error code) only surfaces when a production trade fails.
- **How:** once the no-network DhanClient constructor lands (per existing TODO),
  `requests_mock` / `httpx-mock` tests for the 5 hottest paths first: place_order,
  place_super_order, place_conditional_order, kill_switch, _sync_token_from_redis.
- **Found by:** /design-review on 2026-05-27.

## Audit: see full report at ~/.gstack/projects/Sreekanth1995-TradingAgent/audits/20260527-codebase-gaps-audit.md
- **Priority:** Reference
- **What:** Full 44-finding audit (CRITICAL × 13, HIGH × 19, MEDIUM × 14, LOW × 4). The
  most dangerous items are mirrored above as standalone P0/P1 TODOs. Medium/Low items
  not duplicated here — read the audit doc when working on hardening sprints.
