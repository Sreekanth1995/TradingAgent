# Phase 10 Code Review: MCP API Enhancements
**Date**: 2026-04-14
**Reviewed Files**:
- `mcp_server.py`
- `server.py`
- `ranking_engine.py`

## Overview
The user requested a code review specifically targeting the MCP tool definitions for order placement:
1. `place_manual_order` does not accurately reflect that it actually handles underlying conditional index levels (GTT attachment). Renaming to `place_conditional_order` is requested.
2. `place_super_order` currently relies on `side` ('CALL' or 'PUT') and delegating exact option selection to the engine's ITM automatic resolver. The agent needs precision to supply the direct `option` symbol.

## Severity Classification
- **[High] Architecture / Data flow**: The backend `ranking_engine._execute_signal()` explicitly overrides and assumes ITM contract calculation (`itm_ce`, `itm_pe`), preventing any explicit option symbol from passing through natively.
- **[Medium] Code Quality (Dead Code)**: Found a duplicated `except Exception as e:` block at `server.py` line ~846 causing unreachable code syntax shadowing.
- **[Low] Naming Mismatch**: The MCP tool `place_manual_order` should correctly be identified as `place_conditional_order`.

## Findings Details

### 1. Renaming `place_manual_order`
- **Current state**: In `mcp_server.py`, the tool is named `place_manual_order` but operates heavily on `sl_index` and `target_index` rules through `/ui-signal`.
- **Recommendation**: Rename to `place_conditional_order` to match the functional domain logic. The backend `/ui-signal` logic remains compatible as-is, since it inherently understands how to handle `sl_index`.

### 2. Direct Option Parameter for Super Orders
- **Current state**: `place_super_order` receives `side: str` ('CALL' or 'PUT'). `server.py`'s `/super-order` translates this into an engine signal. The `engine._execute_signal` method completely dumps any potential custom symbol in favor of `broker.get_itm_contract(..., spot_price)`.
- **Recommendation**: 
  - Change `mcp_server.py: place_super_order` to accept `option: str`.
  - Pass the exact symbol through `/super-order` -> `engine.process_signal` under `leg_data['option_symbol']`.
  - Update `ranking_engine.py: _execute_signal` to check if `leg_data['option_symbol']` is provided. If so, bypass `get_itm_contract` and lookup the exact symbol in the broker's map to construct the item.

### 3. Syntax Ghosting in `server.py`
- **Current state**: `server.py` has a redundant, shadowed exception block inside `/super-order`:
  ```python
      except Exception as e:
          logger.error(f"Super Order Error: {e}")
          return jsonify({"status": "error", "message": str(e)}), 500
      except Exception as e:
          logger.error(f"Set Conditional Orders Error: {e}")
  ```
- **Recommendation**: Remove the second `except` block.
