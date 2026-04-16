"""
OpenAI Signal Analyzer
─────────────────────────────────────────────────────────
Analyzes TradingView signals against user-defined price levels
and a custom strategy context prompt using GPT-4o-mini.

Flow:
  TradingView Webhook Signal
        → analyze(signal, levels, context)
        → GPT-4o-mini decision: ALLOW | REJECT
        → Only ALLOW signals reach the trading engine
"""
import os
import json
import logging
from openai import OpenAI

logger = logging.getLogger(__name__)

SYSTEM_PROMPT_TEMPLATE = """You are an expert NIFTY options trading signal validator.

Your job is to analyze an incoming TradingView trading signal and decide the best market action to take based on:
1. The user-defined price level zones
2. The user's custom strategy context / trading rules
3. The current spot price in the signal

## Price Level Zones
{levels_section}

## User Strategy Context
{user_context}

## Decision Rules
- Output specific actions: BUY_CALL, BUY_PUT, EXIT_CALL, EXIT_PUT, or HOLD.
- If the signal direction and price levels strongly align with a bullish setup, output BUY_CALL. 
- If they strongly align with a bearish setup, output BUY_PUT.
- If the market structure suggests a reversal against open positions, output EXIT_CALL or EXIT_PUT.
- If conditions are unsafe or contradictory, output HOLD.

You MUST respond with only valid JSON. No other text.
Response format:
{{
  "action": "BUY_CALL" | "BUY_PUT" | "EXIT_CALL" | "EXIT_PUT" | "HOLD",
  "reason": "Brief explanation (max 2 sentences)",
  "confidence": 0-100
}}"""

DEFAULT_USER_CONTEXT = """# CHANNEL-BASED SUPPORT & RESISTANCE STRATEGY

📌 SYSTEM ROLE
You are a level-based execution assistant for NIFTY 1-minute.
The indicator already calculates:
Channel upper level
Channel lower level
Next upper channel
Next lower channel
Buy/Sell signal
Current price
Important fact:
The gap between channels is larger than the height of a channel.
Your job is NOT to analyze trend.
Your job is NOT to interpret market structure.
Your job is ONLY to trade boundary-to-boundary gaps.
🎯 CORE RULES
1️⃣ Never trade inside a channel.
Inside channel means:
Price is between upper and lower level of the same channel.
If inside → Output: NO TRADE.
2️⃣ Only trade near boundary.
Near means:
Price is within X points of a channel boundary (define X).
3️⃣ PUT Trade Condition
Take PUT only if:
Sell signal is present
Price is near AND below lower boundary of channel
Price is not inside channel
Distance to next lower channel high is greater than minimum target threshold
Target:
→ High of next lower channel
Stop:
→ Re-entry back inside broken channel
4️⃣ CALL Trade Condition
Take CALL only if:
Buy signal is present
Price is near AND above upper boundary of channel
Price is not inside channel
Distance to next upper channel low is greater than minimum target threshold
Target:
→ Low of next upper channel
Stop:
→ Re-entry back inside broken channel
5️⃣ Ignore signals if:
Signal occurs inside channel
Price already moved 40%+ of the gap
Price hesitates and re-enters level
Only capture fresh boundary breaks."""


def _format_levels(levels: any) -> str:
    """Format the levels list/dict into neutral channel markers (e.g. channel_low_high)."""
    if not levels:
        return "No price levels configured. Apply signal as-is."

    lines = ["### Configured Trading Channels"]
    
    # 1. Normalize into a list of (low, high) tuples
    channel_list = []
    if isinstance(levels, list):
        for lvl in levels:
            try:
                channel_list.append((float(lvl.get('low', 0)), float(lvl.get('high', 0))))
            except: pass
    elif isinstance(levels, dict):
        for vals in levels.values():
            try:
                channel_list.append((float(vals.get('low', 0)), float(vals.get('high', 0))))
            except: pass
    
    # 2. Sort by low price and format neutral names
    sorted_channels = sorted(channel_list, key=lambda x: x[0])
    
    for i, (lo, hi) in enumerate(sorted_channels, 1):
        # Using the requested format: channel_low_high
        label = f"channel_{int(lo)}_{int(hi)}"
        lines.append(f"  - {label}: Low={lo}, High={hi}")
    
    return "\n".join(lines)


class OpenAIAnalyzer:
    def __init__(self):
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            logger.warning("OPENAI_API_KEY not set. Analyzer will pass all signals through.")
        self.client = OpenAI(api_key=api_key) if api_key else None
        self.model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

    def analyze(self, signal_data: dict, levels: dict, user_context: str) -> dict:
        """
        Analyze a TradingView signal against price levels and user context.

        Args:
            signal_data: The raw webhook signal payload
            levels: Dict of UTP/TP0/LTP levels { "TP0": {"low": 22800, "high": 22900}, ... }
            user_context: Free-text strategy context from the user

        Returns:
            dict: { "action": "BUY_CALL"|"BUY_PUT"|"EXIT_CALL"|"EXIT_PUT"|"HOLD"|"EXTERNAL", "reason": str, "confidence": int }
        """
        if not self.client:
            logger.info("OpenAI not configured — passing signal through for external processing.")
            return {"action": "EXTERNAL", "reason": "OpenAI not configured (no API key)", "confidence": 100}

        levels_section = _format_levels(levels)
        
        base_strategy = DEFAULT_USER_CONTEXT
        if user_context and user_context.strip():
            context_text = f"{base_strategy}\n\n### User's Custom Strategy Constraints:\n{user_context.strip()}\n"
        else:
            context_text = base_strategy

        system_prompt = SYSTEM_PROMPT_TEMPLATE.format(
            levels_section=levels_section,
            user_context=context_text
        )

        # Build a concise signal summary for the user message
        active_leg = signal_data.get('active_leg', {})
        
        signal_summary = (
            f"Incoming TradingView Signal:\n"
            f"  Underlying: {signal_data.get('underlying') or active_leg.get('symbol', 'NIFTY')}\n"
            f"  Direction: {active_leg.get('transactionType') or active_leg.get('signal_type', 'UNKNOWN')}\n"
            f"  Timeframe: {signal_data.get('timeframe', 'N/A')}m\n"
            f"  Spot Price: {active_leg.get('current_price') or signal_data.get('full_webhook_payload', {}).get('current_price', 'N/A')}\n"
            f"  Raw Webhook Payload: {json.dumps(signal_data.get('full_webhook_payload', {}), default=str)}\n"
            f"  Active Leg Context: {json.dumps(active_leg, default=str)}"
        )

        try:
            logger.info(f"Sending signal to OpenAI ({self.model}) for analysis...")
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": signal_summary}
                ],
                response_format={"type": "json_object"},
                temperature=0.1,
                max_tokens=200,
                timeout=10
            )

            raw = response.choices[0].message.content
            result = json.loads(raw)

            action = result.get("action", "HOLD").upper()
            reason = result.get("reason", "")
            confidence = int(result.get("confidence", 80))

            valid_actions = {"BUY_CALL", "BUY_PUT", "EXIT_CALL", "EXIT_PUT", "HOLD"}
            if action not in valid_actions:
                action = "HOLD"

            logger.info(f"AI Decision: {action} (confidence={confidence}%) — {reason}")
            return {"action": action, "reason": reason, "confidence": confidence}

        except Exception as e:
            logger.error(f"OpenAI analysis failed: {e}. Defaulting to EXTERNAL fallback.")
            return {"action": "EXTERNAL", "reason": f"AI analysis error: {e}", "confidence": 0}
