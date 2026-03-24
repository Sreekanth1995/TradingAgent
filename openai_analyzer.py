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

Your job is to analyze an incoming TradingView trading signal and decide whether it should EXECUTE or be REJECTED based on:
1. The user-defined price level zones (Upper Target Price levels = UTP, Lower Target Price levels = LTP, Base = TP0)
2. The user's custom strategy context / trading rules
3. The current spot price in the signal

## Price Level Zones
{levels_section}

## User Strategy Context
{user_context}

## Decision Rules
- If the signal direction aligns with the price zone context (e.g., bullish signal near a support LTP level), output ALLOW
- If the signal is against the user's strategy context or in a dangerous zone, output REJECT
- If no levels are configured, output ALLOW by default

You MUST respond with only valid JSON. No other text.
Response format:
{{
  "decision": "ALLOW" | "REJECT",
  "reason": "Brief explanation (max 2 sentences)",
  "confidence": 0-100
}}"""


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
            dict: { "decision": "ALLOW"|"REJECT", "reason": str, "confidence": int }
        """
        if not self.client:
            logger.info("OpenAI not configured — passing signal through.")
            return {"decision": "ALLOW", "reason": "OpenAI not configured (no API key)", "confidence": 100}

        levels_section = _format_levels(levels)
        context_text = user_context.strip() if user_context else "No specific strategy context provided."

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

            decision = result.get("decision", "ALLOW").upper()
            reason = result.get("reason", "")
            confidence = int(result.get("confidence", 80))

            if decision not in ("ALLOW", "REJECT"):
                decision = "ALLOW"

            logger.info(f"AI Decision: {decision} (confidence={confidence}%) — {reason}")
            return {"decision": decision, "reason": reason, "confidence": confidence}

        except Exception as e:
            logger.error(f"OpenAI analysis failed: {e}. Defaulting to ALLOW.")
            return {"decision": "ALLOW", "reason": f"AI analysis error: {e}", "confidence": 0}
