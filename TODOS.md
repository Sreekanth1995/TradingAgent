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

## Conditional entry: confirm activity_log_fn actually surfaces alarms to a human
- **Priority:** P1
- **What:** The "naked position" / "cancel failed" / "armed entry orphan" alarms all fire via
  `self._activity_log_fn(msg, prefix)`. In server.py:127 this is wired to `_add_activity_log`,
  which appends to an in-memory deque + a Redis list.
- **Why:** If nothing reads that deque/list (no dashboard banner, no Slack push, no email),
  the "loud" alarm is silent. The whole money-protecting alarm machinery only works if a human
  actually sees it.
- **How:** trace `_add_activity_log` consumers. Verify there is a UI panel, push notification,
  or external integration that surfaces alarm-tier messages within minutes. If not, add one
  (Slack webhook gated on the `🚨` prefix is cheap and sufficient).
- **Found by:** /ship adversarial review on 2026-05-26.
