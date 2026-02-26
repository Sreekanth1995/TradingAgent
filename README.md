# NIFTY Options Trading Bot Strategy

This document outlines the **Direct Signal Strategy** implemented for the NIFTY Options Trading Bot. The system leverages Dhan's Native Super Order (Bracket Order) API with "Smart" entry and exit logic to capture spread and reduce slippage.

## 1. Core Logic
-   **Underlying**: NIFTY 50 Index.
-   **Signal Source**: Webhook Alerts (TradingView).
-   **Instrument**: In-The-Money (ITM) Call/Put Option (Next Expiry).
-   **Execution Mode**: **Native Super Order** (Bracket Order via Dhan API v2).

## 2. Smart Entry Strategy
When a **BUY (Call)** or **SELL (Put)** signal is received:
1.  **LTP Fetch**: The bot fetches the real-time Last Traded Price (LTP) of the selected Option.
2.  **ITM Selection**:
    -   **Call (Buy)**: ATM Strike - 50 points.
    -   **Put (Sell)**: ATM Strike + 50 points.
    -   **Entry Price**: **`LTP - 5 points`**.
    -   *Goal*: To enter as a "Maker" at a better price.
3.  **Bracket Legs** (Fixed Points):
    -   **Target**: Entry + 55% of Entry Price.
    -   **Stop Loss**: Entry - 20% of Entry Price.
    -   **Trailing Jump**: 10% of Entry Price.

## 3. Smart Exit Strategy (Reversal Handling)
When a **Reverse Signal** arrives (e.g., Switching from Long Call to Long Put):

The bot **DOES NOT** place a Market Exit Order. It attempts to "work" the exit:

1.  **Unfilled Entry Safety**: 
    -   It checks if the original Entry Limit Order is still **PENDING** (never filled).
    -   If found, it **CANCELS** it immediately to prevent stale fills.
2.  **Smart Modification (Filled Position)**:
    -   It identifies the active **Target (Sell Limit)** and **Stop Loss** legs.
    -   **Target Modification**: Updates the Limit Price to **`LTP + 5 points`**.
    -   **Stop Loss Trailing**: Updates the SL Trigger to **`LTP - 10 points`** (tightening risk).
3.  **Result**: The old position is left to close at the modified Target (or SL), avoiding Taker slippage.

## 4. Reversal Entry
-   Immediately after handling the exit Modification/Cancellation, the bot triggers the **Smart Entry** logic for the **New Position** (e.g., Short/Put).
-   This results in a temporary "Hedged" state where the old position works its limit exit while the new position seeks its limit entry.

## 5. Fail-Safe & Fallbacks
-   **Fallback Execution**: If Native Super Order placement fails (e.g., API issue), the system falls back to a **Simulated Bracket** (Market Entry + separate Exit Orders).
-   **Position Verification**: Before modifying/closing, the bot verifies `net_qty` via Dhan API to ensure valid state.
-   **LTP Safety**: If LTP cannot be fetched, Smart Logic is upgraded to Standard Execution (Market Orders) to ensure trade completion.

## 6. Configuration
-   **Target Points**: 30
-   **SL Points**: 20
-   **Trailing Jump**: 10
-   **Smart Entry Edge**: -5 (from LTP)
-   **Smart Exit Edge**: +5 (from LTP)
-   **Smart SL Trail**: -10 (from LTP)

## 7. Low Level Design & Architecture

### A. Component Logic (`ranking_engine.py`)
The system operates as a **State Machine** driven by incoming signals:
1.  **Input**: Webhook Signal (`BUY` / `SELL`, Symbol `NIFTY`).
2.  **State Check**: Reads current state (`CALL`, `PUT`, or `NONE`) from Storage.
3.  **Decision Engine**:
    -   **Same Signal**: Ignored (Deduplication).
    -   **New Signal**: Trigger Entry (`_open_position`).
    -   **Reversal**: Trigger Exit (`_close_position`) -> Trigger Entry.

### B. Data Storage (Redis)
State persistence is critical to survive restarts/crashes.
-   **Primary Store**: Redis (Key-Value).
-   **Keys**:
    -   `dhan_access_token`: Cached Auth Token.
    -   `strategy_state:{Underlying}`: JSON object containing:
        -   `side`: 'CALL' / 'PUT'
        -   `entry_id`: Parent Order ID
        -   `quantity`: Position Size
-   **Fallback**: In-Memory Dictionary (Non-persistent).

### C. Order Flow Details

#### 1. Entry Flow (Smart Limit)
1.  **Signal Received**.
2.  **Broker**: `get_itm_contract` (Spot -> ATM +/- 50).
3.  **Broker**: `get_ltp` (Live Price).
4.  **Action**: `place_super_order` (API v2).
    -   Type: LIMIT
    -   Price: `LTP - 5`
    -   Payload includes `targetPrice` and `stopLossPrice`.
5.  **State Update**: Store `entry_id` in Redis.

#### 2. Reversal Flow (Smart Exit + Clean Switch)
1.  **Signal Received** (e.g., Short Signal while Long).
2.  **Cleanup (Unfilled)**:
    -   Check for pending **BUY** orders (Stale Entry).
    -   **CANCEL** immediately if found.
3.  **Smart Exit (Filled)**:
    -   Fetch pending **SELL** orders (Target/SL).
    -   **Modify Target**: Set to `LTP + 5` (Limit).
    -   **Modify SL**: Set to `LTP - 10` (Limit).
    -   *Position is effectively left to close itself.*
4.  **New Entry**:
    -   Execute **Entry Flow** for the new direction (Put).

