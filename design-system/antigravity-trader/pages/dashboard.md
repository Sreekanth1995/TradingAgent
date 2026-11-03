# Page Design Specification: Trader Terminal (`/`)

> **INHERITS:** `design-system/antigravity-trader/MASTER.md`

## 1. Layout Architecture (1440px Cockpit Grid)

The terminal uses a 3-column asymmetric cockpit layout optimized for zero-scroll options execution:

```
+---------------------------------------------------------------------------------------------------+
| TOP TELEMETRY BAR: Brand • Live Latency (ms) • Broker Status Rings • Margin Meter • Kill Switch    |
+---------------------------------------------------------------------------------------------------+
| COLUMN 1: Market Pulse (25%)  | COLUMN 2: Execution Center (45%)   | COLUMN 3: Telemetry Stream (30%)|
| - Sentiment Pills (N50/BN/FN) | - Unified Active Bracket Card      | - Live Trade Feed (Real-time)   |
| - Dynamic Levels Matrix       | - Armed GTT Trigger Monitor        | - Streaming System Log Terminal |
|   (UTP / TP0 / LTP Bounds)    | - Execution & Trailing Jump Dial   | - Session Equity Sparkline      |
+---------------------------------------------------------------------------------------------------+
```

## 2. Component Redesigns & Upgrades

### A. Broker Status Badges (Eliminate Emojis)
- Replace raw text `🟢 DHAN` with micro status pods:
  - SVG pulse indicator dot (`w-1.5 h-1.5 rounded-full bg-emerald-400 ring-4 ring-emerald-500/20 animate-pulse`).
  - Monospace gateway latency (`24ms`).
  - Active session indicator.

### B. Emergency Kill Switch Safety Lock
- Eliminate the floating FAB circle that obscures feeds.
- Move to top-right cockpit dock with a **"Slide to Abort"** slider or 2-click guarded modal:
  `[ ⚡ MASTER KILL ALL (ARMED) ]` with 2-second hold-down countdown ring.

### C. Active Bracket & GTT Slider
- Replace cramped dual-card layout with a multi-stop interactive range visualizer:
  - Gradient progress track: Red (SL) -> Slate (Entry) -> Emerald (Target).
  - Floating dynamic needle with real-time index distance (`+18.5 pts to target`).
  - Trailing stop-loss step visualizer (`Jump: 20 pts`).

### D. Clean Up Dead DOM
- Remove the 150+ lines of hidden nodes (`style="display: none !important;"`) from lines 390 & 681.
- Consolidate legacy JavaScript state listeners cleanly to prevent silent runtime errors.
