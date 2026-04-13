# High-Level Design (HLD): TradingAgent

## 1. Project Overview
The **TradingAgent** is an automated algorithmic trading system designed to receive signals from TradingView (via webhooks) and execute intelligent trades on the Dhan platform. It features a stateful **Ranking Engine** that filters noise, handles trend-following logic, and manages position sizing through a weighted scoring system.

## 2. System Architecture
The system follows a modular architecture consisting of a listener, a logic engine, a broker abstraction layer, and a persistence store.

```mermaid
graph TD
    TV["TradingView Alerts"] -->|Webhook (JSON)| WebServer["Flask Web Server (server.py)"]
    WebServer -->|Signal Data| RE["Ranking Engine (super_order_engine.py)"]
    
    subgraph Logic & State
        RE <-->|Stateful Ranks & Side| Redis["Redis Store"]
    end
    
    RE -->|Order Requests| Broker["Broker Interface (broker_dhan.py)"]
    Broker -->|API Keys/OAuth| Dhan["Dhan API"]
    
    subgraph Testing
        Sim["Simulation Engine (simulate_trading.py)"] -->|Mock Signals| RE
        Sim -->|Mock Orders| MockBroker["Mock Broker"]
    end
```

## 3. Core Components

### 3.1 Webhook Interface (`server.py`)
- **Technology**: Flask (Python)
- **Role**: Entry point for all external signals.
- **Responsibilities**:
  - Authenticates requests via a shared secret.
  - Parses JSON payloads from TradingView.
  - Routes signal legs (CE/PE) to the Ranking Engine.
  - Provides an Admin Dashboard for monitoring and manual token updates.

### 3.2 Ranking Engine (`super_order_engine.py`)
- **Role**: The decision-making core.
- **Key Mechanics**:
  - **Sequential Trading**: Ensures only one trend (CALL or PUT) is active at a time.
  - **Rank/Score System**: Accumulates "Strength" from signals across multiple timeframes.
  - **Weighting**: assigns higher decay power to longer timeframes (e.g., 8m signal has more weight than 1m).
  - **Market Entry**: Executes at market price for immediate fill.
  - **Smart Exit**: Works the exit via limit modification (LTP +/- 5) on reversal.

### 3.3 Broker Middleware (`broker_dhan.py`)
- **Role**: Abstraction layer for order execution.
- **Responsibilities**:
  - **Instrument Discovery**: Uses `dhan_scrip_master.csv` to map spot indices (NIFTY/BANKNIFTY) to specific option contracts.
  - **OAuth Management**: Handles the Dhan 24-hour token lifecycle via browser-based login.
  - **Order Execution**: Places MARKET orders with defined quantities and product types (Intraday/Margin).

### 3.4 Persistence Store (Redis)
- **Role**: Ensures system remains stateful across restarts.
- **Stored Data**:
  - `trading_side`: Current active trend (CALL, PUT, or NONE).
  - `rank:{underlying}`: Current strength score of the active trend.
  - `active_contract:{underlying}`: Details of the currently open position.

## 4. Operational Data Flow
1. **Signal Generation**: TradingView generates an alert (e.g., "Bullish 1m").
2. **Reception**: Flask receives the webhook, verifies the secret, and passes it to the Ranking Engine.
3. **Logic Check**: 
   - If `IDLE`: Open a position if the signal is strong enough.
   - If `ACTIVE`: Increment rank (Pyramiding) or decrement rank (Decay) based on signal bias.
4. **Instrument Selection**: The Broker finds the best In-The-Money (ITM) contract based on current spot prices.
5. **Execution**: The Broker places a Buy order on Dhan and stores the position details in Redis.
6. **Exit**: When the Ranking Engine's score drops to zero, it triggers a Sell order to close the trend.

## 5. Technology Stack
- **Languages**: Python 3.10+
- **Frameworks**: Flask (API), Pytest (Testing)
- **APIs**: DhanHQ (Official Broker SDK), TradingView Webhooks
- **Database**: Redis (State Storage)
- **Deployment**: Railway / Heroku (Procfile included)

## 6. Testing & Backtesting
The project includes a robust simulation environment (`simulate_trading.py`) that allows for:
- Historical accuracy testing using CSV data.
- PnL calculation using Underlying Spot Price as a proxy.
- Timezone-accurate market hour simulation.
