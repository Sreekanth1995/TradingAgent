# Code Structure

## Root Directory (core app — deployed as-is)
- `server.py`: Flask entry point, all HTTP endpoints, SSE bridge.
- `super_order_engine.py`: Native Super Order lifecycle (place/modify/cancel/exit).
- `conditional_order_engine.py`: GTT/index-level conditional order engine.
- `broker_dhan.py`: Dhan API adapter (auth, orders, positions, kill switch).
- `broker_mock.py`: In-memory mock broker for local testing.
- `instrument_resolver.py`: ITM option resolution from scrip master.
- `mcp_server.py`: MCP server exposing tools to Claude AI.
- `Procfile`: gunicorn entry point (`server:app`).
- `requirements.txt`: Python dependencies.
- `env.example`: Template for `.env` secrets.
- `README.md`: Project overview.

## Key Directories
- `templates/`: Dashboard HTML (`index.html`).
- `tests/`: All pytest test files. `conftest.py` adds root to `sys.path`.
- `simulations/`: Offline simulation and backtest scripts (no broker calls).
- `scripts/`: Deployment and utility shell scripts (`deploy_vultr.sh`, `vps_setup_remote.sh`, etc.).
- `pine/`: TradingView Pine Script source files.
- `docs/`: Project documentation (`HLD.md`, `ARCHITECTURE.md`, `MCP_SETUP.md`, `PRE_COMMIT.md`).
- `.planning/`: GSD workflow state and phase documentation.
