# Design System Master File: Antigravity Trader

> **STATUS:** Global Source of Truth for Antigravity Algorithmic Trading Cockpit & Admin Hub.
> When building specific views, check `design-system/antigravity-trader/pages/[page-name].md` for view-specific overrides.

---

**Project:** Antigravity Trader  
**Domain:** Fintech / High-Frequency Derivatives Trading & Prop Desk Execution  
**Architecture:** Real-time Single Page Application (Tailwind CSS, Vanilla JS, Server-Sent Events / WebSockets)  
**Target Resolution:** 1440px+ Desktop Primary, Responsive Down to 1024px and 375px Mobile Viewport  

---

## 1. Visual Foundation & Color Tokens

Optimized for 8+ hour continuous screen time, eye-strain mitigation (OLED midnight baseline), and instant signal comprehension during volatile market movements.

| Semantic Role | Hex | Tailwind Utility | CSS Variable | WCAG Contrast |
|---|---|---|---|---|
| **Background (OLED Canvas)** | `#030712` | `bg-slate-950` | `--bg-canvas` | - |
| **Card / Surface Base** | `#0b1120` | `bg-slate-900/80` | `--bg-surface` | - |
| **Card Elevated / Popover** | `#151e32` | `bg-slate-800/90` | `--bg-surface-elevated` | - |
| **Border Default** | `#1e293b` | `border-slate-800` | `--border-default` | 3.5:1 |
| **Border Active / Highlight** | `#334155` | `border-slate-700` | `--border-active` | 4.8:1 |
| **Brand Primary (Cyber Violet)** | `#A855F7` | `text-purple-500` / `bg-purple-600` | `--color-primary` | 6.5:1 |
| **Bullish / Long / Profit (Electric Mint)** | `#00F5A0` | `text-emerald-400` / `bg-emerald-500` | `--color-bull` | 9.8:1 |
| **Bearish / Short / Loss (Neon Crimson)**| `#FF4B55` | `text-rose-500` / `bg-rose-600` | `--color-bear` | 5.2:1 |
| **Neutral / Inside Range (Solar Amber)** | `#F59E0B` | `text-amber-400` / `bg-amber-500` | `--color-neutral`| 7.1:1 |
| **Text Primary (High Emphasis)** | `#F8FAFC` | `text-slate-50` | `--text-primary` | 15.8:1 (AAA) |
| **Text Secondary (Medium Emphasis)** | `#94A3B8` | `text-slate-400` | `--text-secondary` | 7.0:1 (AAA) |
| **Text Muted (Low Emphasis)** | `#64748B` | `text-slate-500` | `--text-muted` | 4.6:1 (AA) |

> [!IMPORTANT]
> **Anti-Pattern Rule**: Never use opacity below 60% on dark backgrounds for numerical trading metrics (e.g., avoid `text-on-surface-variant/40`). Critical numbers must always be readable in split-second decisions.

---

## 2. Typography & Tabular Number Rules

Trading data requires fixed column widths to eliminate horizontal jitter when prices stream in real-time.

- **Primary UI Font**: `Space Grotesk` / `Outfit` for structural headers, section titles, and action badges.
- **Data & Tabular Font**: `Fira Code` or `JetBrains Mono` with `font-feature-settings: "tnum" 1, "zero" 1`.
- **Numeric Display Rule**: All currency values (₹), percentages (%), strike prices, SL/Target levels, and latency counters must strictly utilize `font-mono tabular-nums`.

```html
<!-- Example Tabular Metric -->
<div class="font-mono text-xs font-semibold tabular-nums tracking-tight text-emerald-400">
  +₹14,250.00 <span class="text-[10px] text-emerald-500/80">(+8.42%)</span>
</div>
```

---

## 3. High-Performance Glassmorphism & Elevation

```css
/* Core Terminal Glass Panel */
.terminal-panel {
  background: rgba(11, 17, 32, 0.75);
  backdrop-filter: blur(16px);
  -webkit-backdrop-filter: blur(16px);
  border: 1px solid rgba(255, 255, 255, 0.08);
  box-shadow: 0 4px 20px -2px rgba(0, 0, 0, 0.5), inset 0 1px 0 0 rgba(255, 255, 255, 0.05);
  border-radius: 12px;
}

/* Bullish Neon Glow Accent */
.glow-bull {
  box-shadow: 0 0 20px -5px rgba(0, 245, 160, 0.25);
  border-color: rgba(0, 245, 160, 0.35);
}

/* Bearish Neon Glow Accent */
.glow-bear {
  box-shadow: 0 0 20px -5px rgba(255, 75, 85, 0.25);
  border-color: rgba(255, 75, 85, 0.35);
}
```

---

## 4. UI/UX Pre-Delivery Checklist

- [x] **No Emojis as UI Icons**: Replace `🟢`, `↻` with SVGs / Material Symbols.
- [x] **Cursor Pointer**: All interactive cards, pills, tabs, and toggles have `cursor-pointer`.
- [x] **Micro-Feedback**: Hover states transition within 150-200ms (`transition-all duration-150`).
- [x] **Tabular Numeric Stability**: All price feeds and timers use `tabular-nums`.
- [x] **Fail-Safe Safety Interlocks**: Destructive actions (Kill All, Cancel All Brackets) require 2-step verification or slide-to-confirm.
- [x] **Responsive Grid**: 1440px 3-column cockpit, collapsing cleanly into 2-column at 1024px and single-column tabbed cockpit on mobile.
