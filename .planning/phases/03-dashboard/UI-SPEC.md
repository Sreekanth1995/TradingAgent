# UI-SPEC: Trading Agent Dashboard (Phase 1)

## 1. Objective
To provide a high-performance, visually stunning, and intuitive dashboard for monitoring the Trading Agent's status and performing manual overrides.

## 2. Visual Identity
- **Design Language**: Glassmorphism (Frosted glass effects, subtle borders, high blur).
- **Typography**:
    - Headings: `Outfit` (700 weight)
    - Body: `Inter` (400/600 weight)
- **Color Palette**:
    - `Background`: Deep Charcoal/Navy (`#0a0a0c` to `#1e293b` gradient).
    - `Primary Accent`: Cyan (`#00f2fe`) - Used for "Live" status and primary indicators.
    - `Success`: Emerald (`#4ade80`) - Used for positive PnL and successful auth.
    - `Danger`: Rose/Red (`#ef4444`) - Used for "Emergency Exit" and errors.
    - `Glass`: `rgba(255, 255, 255, 0.05)` with `backdrop-filter: blur(20px)`.

## 3. Layout Structure
- **Global Header**: Title "Trading Agent" (Left) and **"Connect Dhan"** button (Top-Right).
- **Navigation Tabs**: (Simplified or Removed in favor of a unified dashboard view).
- **Main View (NIFTY Hub)**:
    - **Position Status Card**: Real-time summary at the top.
    - **Trade Controls**:
        - **CALL Sector**: [ BUY CALL ] [ EXIT CALL ]
        - **PUT Sector**: [ BUY PUT ] [ EXIT PUT ]
        - All buttons use glassmorphism with specific color accents.
    - **Emergency Hub**: Giant red "EXIT ALL POSITIONS" button at the bottom.

## 4. Components & Behavior
### 4.1 Connection Hub (Top-Right)
- Action: "Connect Dhan" button. Glows Cyan when connected, Dimmed when disconnected.

### 4.2 NIFTY Trade Center
- **BUY CALL / BUY PUT**: Trigger entries for the respective side.
- **EXIT CALL / EXIT PUT**: Trigger immediate square-off for the specific side.
- **Active Position Indicator**: If a side is active, a **Green Blinking Bubble** appears on top of the corresponding BUY button.

### 4.3 Emergency Control
- **"EXIT ALL POSITIONS"**: Big red button that triggers `manual_exit_all`.

### 4.3 Data Flow
- Dashboard polls `/get-state` every 5 seconds (or uses WebSockets if implemented later).
- Fields required from `/get-state`:
    - `side` (string)
    - `quantity` (int)
    - `symbol` (string)
    - `is_scalping` (bool)

## 5. Design Assets
![Dashboard Mockup](file:///Users/sreekanthmekala/.gemini/antigravity/brain/13d57a9f-f881-48ed-a89d-7057572e5137/trading_agent_dashboard_mockup_1774377125236.png)
