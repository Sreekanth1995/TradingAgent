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
Once connected, the AI can use:
- `get_trading_status`: "What is my current NIFTY position?"
- `place_manual_order`: "Buy 2 lots of NIFTY Call options"
- `update_price_levels`: "Set my TP0 range to 22400 - 22500"
- `get_performance_history`: "Show me my last 5 trades"
- `get_activity_logs`: "Why did the ranking engine reject the last signal?"

---
### ⚠️ Security Warning
The MCP server grants **full trading control** to the AI model. Ensure you trust the prompts and assistant you are using with these tools.
