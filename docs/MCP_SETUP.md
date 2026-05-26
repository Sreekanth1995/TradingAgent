# MCP Configuration: TradingAgent AI Bridge

To enable AI control (Claude Code / Antigravity), add the following configuration to your MCP settings.

### 1. Requirements
Ensure you have the dependencies installed:
```bash
pip install mcp httpx python-dotenv
```

### 2. Configuration for Claude Code
Add this to your `~/.git/claude_config.json` or your project-level config:

```json
{
  "mcpServers": {
    "trading-agent": {
      "command": "python",
      "args": ["/Users/sreekanthmekala/Desktop/TradingAgent/mcp_server.py"],
      "env": {
        "WEBHOOK_SECRET": "121995",
        "TRADING_AGENT_URL": "http://65.20.83.74",
        "PYTHONPATH": "/Users/sreekanthmekala/Desktop/TradingAgent"
      }
    }
  }
}
```

### 3. Available Tools
Once connected, the AI can use (see `mcp_server.py` for the full set):
- `get_positions`, `get_orders`: "What is my current NIFTY position?"
- `place_super_order`, `modify_super_order`, `cancel_super_order`, `exit_super_order`: native bracket-order control on the option premium.
- `place_conditional_order`, `modify_conditional_order`, `cancel_conditional_order`, `exit_conditional_order`: index-level (NIFTY/BANKNIFTY) conditional control. `place_conditional_order` accepts an optional `entry_index` — omit for an immediate market entry, or pass an index level to defer the BUY until the index touches it.
- `get_margin`, `get_zone`, `get_last_signal`, `get_performance_history`, `get_activity_logs`: read-side dashboard data.
- `skip_trade`, `reload_scrip`, `get_scrip_status`: operational controls.
- `set_feeling`, `get_feeling`: per-underlying directional bias (NIFTY / BANKNIFTY / FINNIFTY). `set_feeling(underlying, value)` accepts `value ∈ {"Bullish","Bearish","Inside",None}`; `Bullish` blocks PUT entries, `Bearish` blocks CALL entries, `Inside` blocks both, `None` clears the gate. Exits are never blocked. The response may include `warnings[]` if the new feeling contradicts an armed-but-unfilled conditional entry (auto-cancel is NOT performed — use `cancel_conditional_order` if needed). When the underlying store (`feelings.json`) is corrupt, both tools return 503 with `recovery: "delete feelings.json (no restart needed)"` and entries are blocked.

---
### ⚠️ Security Warning
The MCP server grants **full trading control** to the AI model. Ensure you trust the prompts and assistant you are using with these tools.
