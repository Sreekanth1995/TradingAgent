# Phase 12: Third Strategy Implementation (Renko + Q-Trend + Bastion Levels)

This phase implements a new 3rd strategy in the `OptionsTrading` client loop, running dynamically when the `Renko Candles Overlay` indicator is present on the TradingView chart.

## Decisions

### 1. Strategy Differentiator
*   The strategy activates automatically when `Renko Candles Overlay` is detected in `inputs.active_studies`.

### 2. Signal Generation (Confluence Rules)
*   **Trigger**: Q-Trend generates a Buy/Sell signal:
    *   **CALL**: `Buy signal == 1.0` or `Strong Buy signal == 1.0` in `last_completed_values` of `Q-Trend`.
    *   **PUT**: `Sell signal == 1.0` or `Strong Sell signal == 1.0` in `last_completed_values` of `Q-Trend`.
*   **Trend Filter**: The trigger must align with the trend of the `Renko Candles Overlay` indicator:
    *   For a **CALL** trade, `Trend is UP == 1` in `last_completed_values` of `Renko Candles Overlay`.
    *   For a **PUT** trade, `Trend is DOWN == 1` in `last_completed_values` of `Renko Candles Overlay`.

### 3. Exit and Entry Levels (Bastion Support/Resistance)
*   **Entry**: Place a Limit pullback entry order:
    *   **CALL**: Limit entry placed at BASTION Support (`support + 3.0`).
    *   **PUT**: Limit entry placed at BASTION Resistance (`resistance - 3.0`).
*   **Target**:
    *   **CALL**: BASTION Resistance (`resistance`).
    *   **PUT**: BASTION Support (`support`).
*   **Stop Loss (SL)**:
    *   **CALL**: BASTION Support (`support - 5.0`).
    *   **PUT**: BASTION Resistance (`resistance + 5.0`).

### 4. Timeframe and Time Gates
*   Runs on the same **5-minute** timeframe.
*   Entry window is **09:30 to 14:30 IST**.
*   EOD Auto-Exit fires at **15:10 IST**.

## Technical Implementation Details
*   All calculations (including Headroom and dynamic Stop Loss / Target offsets) will follow the existing Bastion strategy patterns in `fast/decide.py`.
