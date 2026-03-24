# Architecture

## System Flow
1. **TradingView Hub**: Sends JSON webhooks to `/webhook`.
2. **Flask Server**: Validates secret and routes to `RankingEngine`.
3. **RankingEngine**: 
    - Deduplicates signals.
    - Resolves ITM Option contracts based on Index LTP.
    - Implements **Native Super Orders** (Market Entry + SL + Target) for immediate execution.
    - Handles **Trailing Stop Loss** (5% scalping, 10% normal).
4. **Broker Layer**: Communicates with Dhan API for order placement and status polling.

## Component Responsibilities
- `server.py`: Request handling, security, UI serving.
- `ranking_engine.py`: Core strategy logic, state persistence, position management.
- `broker_dhan.py`: API authentication (OAuth/Consent), order execution, scrip master parsing.
