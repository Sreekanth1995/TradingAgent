# Code Structure

## Root Directory
- `server.py`: Entry point for the web application.
- `super_order_engine.py`: Trading strategy implementation.
- `broker_dhan.py`: Dhan API bridge.
- `README.md`: Project overview and setup.
- `HLD.md`: High-level design document.
- `Procfile`: gunicorn entry point (used by systemd on Vultr).
- `requirements.txt`: Python dependencies.

## Key Directories
- `templates/`: HTML templates (e.g., `index.html`).
- `.planning/`: GSD workflow state and phase documentation.
- `scripts/`: Initialization and utility scripts (e.g., `init_scripts.py`).
- `.env`: Environment variables (API keys, secrets).
