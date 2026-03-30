"""
Trade plan reasoner - the intelligence layer of the agentic pipeline.

Called after the deterministic pipeline has assembled and verified a plan.
Receives full context and produces reasoning that a smart advisor would give
before the user is asked to confirm.

This module does NOT:
- Re-validate symbols or balances (resolver owns that)
- Check tradability (preflight owns that)
- Change the plan (pipeline owns that)

It DOES:
- Reason about whether the plan makes sense in context
- Flag risks the user should know before confirming
- Suggest alternatives when trades are blocked
- Produce a plain-English summary that replaces template output
- Degrade gracefully if the API is down
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class TradeReasoning(BaseModel):
    """Structured output of the LLM reasoning step."""

    confidence: str = "high"  # high | medium | low
    plan_summary: str = ""  # 1-2 sentence plain English summary
    step_summaries: List[str] = Field(default_factory=list)  # one per valid_action, in order
    risk_flags: List[str] = Field(default_factory=list)  # things user must know before confirming
    warnings: List[str] = Field(default_factory=list)  # non-blocking cautions
    alternatives: List[str] = Field(default_factory=list)  # suggestions when trades are blocked
    portfolio_impact: Optional[str] = None  # "Sells 91% of your portfolio ($4.69 of $5.14)"
    reasoning: str = ""  # internal reasoning trace (logged, not shown)


_SYSTEM_PROMPT = """\
You are a trade plan advisor for a live crypto trading platform.

The platform has already validated a trade plan against live Coinbase balances.
Your job is to reason about it - not re-validate, but add the judgment a smart
advisor would offer before the user confirms.

You receive JSON with:
- user_text: what the user said
- valid_actions: trades that ARE executable (verified, will execute if confirmed)
- blocked: trades that could NOT execute and why
- portfolio: live holdings from Coinbase (symbol -> available_qty, hold_qty)
- portfolio_total_usd: estimated total portfolio value

Return ONLY a JSON object with these fields:

{
  "confidence": "high" | "medium" | "low",
  "plan_summary": "string",
  "step_summaries": ["string", ...],
  "risk_flags": ["string", ...],
  "warnings": ["string", ...],
  "alternatives": ["string", ...],
  "portfolio_impact": "string or null",
  "reasoning": "string"
}

FIELD RULES:

confidence:
  "high"   = clear intent, all requested trades executable, no major risks
  "medium" = partial execution (some blocked), or notable risk flags present
  "low"    = most trades blocked, intent unclear, or critical risk present

plan_summary:
  1-2 sentences. What the plan actually does in plain English.
  Be direct and specific. Use real numbers.
  Example: "Selling your full MOODENG and MORPHO positions for ~$4.10 combined.
  This leaves BTC untouched and your portfolio at ~$1.04."
  NOT: "Your trade has been staged."

step_summaries:
  One string per valid_action, same order as input.
  Format for SELL with qty: "Step N (ready|queued): SELL {qty:.6f} {asset} @ market - est. ${usd:.2f}"
  Format for BUY with usd:  "Step N (ready|queued): BUY ${usd:.2f} of {asset} @ market"
  Step 1 is always "ready", rest are "queued".

risk_flags:
  Things the user genuinely needs to know. Be selective - only real risks.
  Examples of good flags:
    "This liquidates 91% of your portfolio - you will be almost entirely in cash"
    "BTC order is ~$0.31 - Coinbase fees (~$0.99 minimum) will exceed the proceeds"
    "Selling all 3 assets removes all crypto exposure from your account"
    "MOODENG has low liquidity - actual fill price may differ significantly"
  Examples of bad flags (do NOT include):
    "Make sure you want to do this" (not specific)
    "Markets can go up or down" (not actionable)
  Empty list [] if no real risks.

warnings:
  Non-blocking cautions. Lower severity than risk_flags.
  Example: "USD cash balance ($0.76) will remain after execution"
  Empty list [] if nothing worth noting.

alternatives:
  Only when trades are blocked. Specific, actionable suggestions.
  Example: "MOODENG is on hold - you could sell MORPHO ($2.22) or BTC ($0.31) instead"
  Empty list [] if nothing is blocked.

portfolio_impact:
  Single line summary of total USD impact and portfolio percentage.
  Example: "Sells ~$4.10 of $5.14 total portfolio (79.8%)"
  null if only 1 small trade or impact is trivial.

reasoning:
  1-2 sentences of your internal logic. This is logged for debugging.
  Example: "User wants full liquidation. BTC order is below Coinbase minimum fee threshold."

Return ONLY the JSON object. No markdown fences, no explanation, no extra text.\
"""


def _build_input(
    user_text: str,
    valid_actions: List[Dict[str, Any]],
    all_failures: List[str],
    executable_state: Any,
    total_portfolio_usd: float,
) -> str:
    """Serialize pipeline state into the JSON context sent to the LLM."""

    portfolio: Dict[str, Dict[str, float]] = {}
    try:
        balances = getattr(executable_state, "balances", {}) or {}
        for sym, bal in balances.items():
            avail = float(getattr(bal, "available_qty", 0) or 0)
            hold = float(getattr(bal, "hold_qty", 0) or 0)
            if avail > 0 or hold > 0:
                portfolio[sym] = {"available_qty": avail, "hold_qty": hold}
    except Exception:
        pass

    slim_actions = []
    for i, a in enumerate(valid_actions):
        slim_actions.append(
            {
                "step": i + 1,
                "side": a.get("side"),
                "asset": a.get("asset"),
                "base_size": a.get("base_size"),
                "amount_usd": a.get("amount_usd"),
                "amount_mode": a.get("amount_mode"),
            }
        )

    payload = {
        "user_text": user_text,
        "valid_actions": slim_actions,
        "blocked": all_failures,
        "portfolio": portfolio,
        "portfolio_total_usd": round(total_portfolio_usd, 2),
    }
    return json.dumps(payload, default=str)


def reason_about_plan(
    user_text: str,
    valid_actions: List[Dict[str, Any]],
    all_failures: List[str],
    executable_state: Any,
    total_portfolio_usd: float = 0.0,
) -> TradeReasoning:
    """
    Reason about the assembled trade plan using the LLM.

    Always returns a TradeReasoning - never raises.
    On API failure, returns minimal reasoning so the pipeline continues.
    """
    if not valid_actions and not all_failures:
        return TradeReasoning(
            confidence="low",
            plan_summary="No executable trades found.",
        )

    # Skip LLM call in pytest — avoids blocking the event loop with a sync HTTP request
    from backend.core.test_utils import is_pytest
    if is_pytest():
        steps = [
            "Step {} ({}): {} {}{}".format(
                i + 1,
                "ready" if i == 0 else "queued",
                (a.get("side") or "?").upper(),
                a.get("asset", "?"),
                f" - {a['base_size']:.6f}"
                if a.get("base_size")
                else f" - ${float(a.get('amount_usd') or 0):.2f}",
            )
            for i, a in enumerate(valid_actions)
        ]
        return TradeReasoning(
            confidence="high" if valid_actions else "low",
            plan_summary=(
                f"Ready to execute {len(valid_actions)} trade(s)."
                if valid_actions
                else "No executable trades found."
            ),
            step_summaries=steps,
        )

    context = _build_input(
        user_text,
        valid_actions,
        all_failures,
        executable_state,
        total_portfolio_usd,
    )

    try:
        from backend.core.config import get_settings
        settings = get_settings()
        if not settings.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY not configured")

        from openai import OpenAI
        client = OpenAI(api_key=settings.openai_api_key, timeout=20.0)
        response = client.chat.completions.create(
            model=settings.openai_model,
            max_tokens=600,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": context},
            ],
        )
        raw = (response.choices[0].message.content or "").strip()
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
        data = json.loads(raw)

        reasoning = TradeReasoning(
            confidence=data.get("confidence", "high"),
            plan_summary=data.get("plan_summary", ""),
            step_summaries=data.get("step_summaries") or [],
            risk_flags=data.get("risk_flags") or [],
            warnings=data.get("warnings") or [],
            alternatives=data.get("alternatives") or [],
            portfolio_impact=data.get("portfolio_impact"),
            reasoning=data.get("reasoning", ""),
        )

        logger.info(
            "Trade reasoning OK: confidence=%s risk_flags=%d alternatives=%d | %r",
            reasoning.confidence,
            len(reasoning.risk_flags),
            len(reasoning.alternatives),
            user_text[:60],
        )
        return reasoning

    except Exception as exc:
        logger.warning("Trade reasoning failed (degrading gracefully): %s", exc)

        steps = [
            "Step {} ({}): {} {}{}".format(
                i + 1,
                "ready" if i == 0 else "queued",
                (a.get("side") or "?").upper(),
                a.get("asset", "?"),
                f" - {a['base_size']:.6f}"
                if a.get("base_size")
                else f" - ${float(a.get('amount_usd') or 0):.2f}",
            )
            for i, a in enumerate(valid_actions)
        ]
        return TradeReasoning(
            confidence="high" if valid_actions else "low",
            plan_summary=(
                f"Ready to execute {len(valid_actions)} trade(s)."
                if valid_actions
                else "No executable trades found."
            ),
            step_summaries=steps,
        )
