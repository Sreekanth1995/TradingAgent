# Summary: Phase 17 - Zero-Downtime Atomic Scrip Reload & Lot Map Guard

## Executive Summary
Addressed critical P0 issues where `/reload-scrip` blanked active instrument and lot maps during parsing, and where `place_order` / `place_super_order` silently defaulted to 1-unit lot sizes on unknown instruments.

## Key Changes
1. **Thread-Safe Atomic Staging (`broker/instrument_service.py`)**:
   - Added `self._reload_lock = threading.Lock()` to serialize concurrent reload attempts.
   - Re-download and CSV parsing now populate local staging dictionaries (`temp_scrip_map`, `temp_lot_map`, `temp_exact_symbol_map`, `temp_expiry_indices`).
   - Upon parse validation (`count > 0`), an atomic pointer swap rebinds active dictionaries. If any failure occurs during download or parse, existing mappings remain completely intact and active.
   - Added `reload_scrip_master(force_download=True)` to `DhanInstrumentService` and exposed it on `DhanClient`.
2. **Server Route Hardening (`server.py`)**:
   - `/reload-scrip` route no longer performs destructive in-place clearing (`broker.scrip_map = {}`, `broker.lot_map = {}`). It delegates directly to `broker.reload_scrip_master(force_download=True)`.
3. **Fail-Closed Lot Guard (`broker/order_service.py`)**:
   - Updated `place_order` and `place_super_order` to fail-closed (`return {"success": False, "error": ...}`) when `scrip_loaded=True` and `security_id` is missing or 0 in `lot_map`.
   - Prevented 1-unit order placements that could create asymmetric naked exposure.
4. **Verification**:
   - Added unit tests in `tests/test_modular_broker.py` testing zero-downtime map preservation on error and fail-closed lot guard behavior.
   - All **119 unit tests passing**.
