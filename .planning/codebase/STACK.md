# Tech Stack

## Backend
- **Language**: Python 3.10+
- **Framework**: Flask (Web Server & Webhook API)
- **Timezone**: `pytz` (Asia/Kolkata)
- **State Management**: Redis (via `redis-py`), fallback to In-Memory dictionary.
- **Broker Integration**: Dhan API v2 (official library partially used, custom HTTP wrappers).

## Frontend
- **Structure**: Semantic HTML5.
- **Logic**: Vanilla JavaScript (ES6+).
- **Styling**: Vanilla CSS (Modern CSS variables, Flexbox/Grid, Backdrop-filter).
- **Fonts**: Google Fonts (Inter, Outfit).

## DevOps
- **Deployment**: Railway.app (via `Procfile`).
- **Secret Management**: Python `python-dotenv`.
- **Environment**: macOS (Development), Linux (Production).
