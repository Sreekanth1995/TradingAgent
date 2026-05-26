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
