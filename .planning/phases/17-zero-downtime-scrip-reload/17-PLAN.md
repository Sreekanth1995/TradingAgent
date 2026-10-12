# Plan: Phase 17 - Zero-Downtime Atomic Scrip Reload & Lot Map Guard

## Goal
Eliminate race conditions where scrip maps (`scrip_map`, `lot_map`) are emptied in-place during `/reload-scrip`, and prevent silent fallbacks to 1-unit lot sizes when placing orders.

## Tasks
- [x] In `broker/instrument_service.py`:
  - Add `self._reload_lock = threading.Lock()`
  - Update `_load_scrip_master(force_download: bool = False)` to parse into local dictionaries and atomically swap references only upon successful parse.
  - Implement `reload_scrip_master(force_download: bool = True) -> int` wrapped in `_reload_lock`.
- [x] In `broker/client.py` and `broker_dhan.py`:
  - Expose `reload_scrip_master(force_download=True)` on `DhanClient` delegating to `instrument_service`.
- [x] In `server.py`:
  - Refactor `/reload-scrip` to call `broker.reload_scrip_master(force_download=True)` without manually emptying `broker.scrip_map = {}` or `broker.lot_map = {}`.
- [x] In `broker/order_service.py`:
  - Add fail-closed validation on missing/zero `lot_size` in `place_order` and `place_super_order` when `scrip_loaded=True`, preventing 1-unit fallbacks.
- [x] In `tests/test_modular_broker.py` or new test:
  - Add unit tests for atomic swap, concurrent reload lock protection, and fail-closed lot size guard.
- [x] Run test suite (`pytest tests/`) and ensure 100% pass rate.
