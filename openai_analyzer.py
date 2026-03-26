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
1. The user-defined price level zones (Upper Target Price levels = UTP, Lower Target Price levels = LTP, Base = TP0)
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

## Core Concepts
The configured price levels (TP0, UTP1, UTP2, LTP1, LTP2, etc.) act as dynamic trading channels. Every channel has a "High" and a "Low" boundary.
1. **Resistance Rule:** When the price is moving UP, the **Low** level of any channel acts as strict resistance.
2. **Support Rule:** When the price is falling DOWN, the **High** side of any channel acts as strict support.

## Strict Entry Conditions (Gatekeeping Rules)

### For BULLISH Signals (BUY / CALL Positions)
The model must ONLY output BUY_CALL if the current spot price satisfies the following support/breakout condition:
- The price is **NEAR AND ABOVE** the **High** level of an identified channel (e.g., TP0 High, UTP1 High, UTP2 High, LTP1 High, LTP2 High). 
- *Rationale: The High level is acting as a newly established support base, or the price has cleanly broken out above it.*
- If a BUY signal is generated while the price is struggling right at or below a channel's **Low** (Resistance), the signal MUST be HOLD.

### For BEARISH Signals (SELL / PUT Positions)
The model must ONLY output BUY_PUT if the current spot price satisfies the following resistance/breakdown condition:
- The price is **NEAR AND BELOW** the **Low** level of an identified channel (e.g., TP0 Low, UTP1 Low, UTP2 Low, LTP1 Low, LTP2 Low).
- *Rationale: The Low level is acting as overhead resistance, or the price is breaking down below it.*
- If a SELL signal is generated while the price is resting right at or above a channel's **High** (Support), the signal MUST be HOLD.

## AI Evaluation Checklist
When evaluating the incoming webhook payload, follow these steps strictly:
1. Identify if the signal is BULLISH (CALL) or BEARISH (PUT).
2. Look at the Spot Price provided in the signal.
3. Compare the Spot Price to the closest channel's High and Low levels provided in the Price Levels section.
4. Check if the Spot Price confirms the logic (e.g., For a CALL, is the price >= Channel High? For a PUT, is the price <= Channel Low?).
5. Output the respective BUY_ action only if the exact criteria are met. Otherwise, output HOLD."""


def _format_levels(levels: dict) -> str:
    """Format the levels dict into a human-readable string for the prompt."""
    if not levels:
        return "No price levels configured. Apply signal as-is."

    lines = []

    utp_levels = {k: v for k, v in levels.items() if k.startswith('UTP')}
    tp0 = levels.get('TP0')
    ltp_levels = {k: v for k, v in levels.items() if k.startswith('LTP')}

    if utp_levels:
        lines.append("### Upper Resistance/Target Levels (UTP)")
        for name, vals in sorted(utp_levels.items()):
            lo = vals.get('low', '—')
            hi = vals.get('high', '—')
            lines.append(f"  {name}: Low={lo}, High={hi}")

    if tp0:
        lines.append("### Base Pivot Level (TP0)")
        lines.append(f"  TP0: Low={tp0.get('low', '—')}, High={tp0.get('high', '—')}")

    if ltp_levels:
        lines.append("### Lower Support Levels (LTP)")
        for name, vals in sorted(ltp_levels.items()):
            lo = vals.get('low', '—')
            hi = vals.get('high', '—')
            lines.append(f"  {name}: Low={lo}, High={hi}")

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
        context_text = user_context.strip() if user_context and user_context.strip() else DEFAULT_USER_CONTEXT

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
