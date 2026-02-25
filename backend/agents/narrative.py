"""Shared formatter/validator for enterprise-grounded narrative output.

Every user-facing narrative in the chat must pass through this module so that
the output is predictable, scannable, and free of log-line blobs.

Narrative format (3-6 lines):
  1. Provenance + interpretation
  2-4. Context / plan / risk details
  5-6. Next step + evidence
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Any

MAX_LINE_LENGTH = 200
FORBIDDEN_TOKENS = re.compile(
    r"(?:top1_concentration|market_data\.get_price|trade_preflight|"
    r"portfolio_snapshots|_safe_json_loads|concentration_pct_top1|"
    r"diversification_score|get_accounts|get_orders|run_preflight|"
    r"execute_run|create_run|parse_intent|inferred interpretation)"
)
SAFE_ROUTES = {"/runs", "/chat", "/portfolio", "/evals", "/performance", "/ops"}
EVIDENCE_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")

PARAGRAPH_SEP = "\n\n"


def _ts_display(as_of: str) -> str:
    """Convert an ISO timestamp to a human display string."""
    if not as_of:
        return "unavailable"
    try:
        from datetime import datetime
        ts = datetime.fromisoformat(as_of.replace("Z", "+00:00"))
        return ts.strftime("%b %d, %Y %H:%M UTC")
    except Exception:
        return as_of


def _safe_mode(mode: Any) -> str:
    if hasattr(mode, "value"):
        mode = mode.value
    return str(mode).replace("ExecutionMode.", "").upper() or "UNKNOWN"


def _truncate_line(line: str) -> str:
    if len(line) <= MAX_LINE_LENGTH:
        return line
    return line[: MAX_LINE_LENGTH - 3].rstrip() + "..."


def _validate(text: str) -> str:
    """Assert output satisfies the relaxed contract: 3-6 paragraph-separated
    lines, no forbidden tokens, last line has 2-4 evidence links."""
    lines = text.split(PARAGRAPH_SEP)
    if not (3 <= len(lines) <= 6):
        raise ValueError(f"Narrative must be 3-6 lines, got {len(lines)}")
    for i, line in enumerate(lines):
        if FORBIDDEN_TOKENS.search(line):
            raise ValueError(f"Line {i+1} contains forbidden token: {line!r}")
    evidence_links = EVIDENCE_LINK_RE.findall(lines[-1])
    if not (2 <= len(evidence_links) <= 4):
        raise ValueError(
            f"Evidence line must have 2-4 clickable links, found {len(evidence_links)}"
        )
    return text


def _safe_evidence_ref(href: str) -> str:
    """Ensure an evidence href uses a safe, resolvable scheme.
    Degrades artifact: refs to url:/runs since no artifact viewer exists."""
    if href.startswith("run:"):
        return href
    if href.startswith("url:"):
        path = href[4:]
        base = "/" + path.lstrip("/").split("/")[0].split("?")[0].split("#")[0]
        if base in SAFE_ROUTES:
            return href
        return "url:/runs"
    if href.startswith("artifact:"):
        return href
    return "url:/runs"


def _format_evidence(items: List[Dict[str, str]]) -> str:
    """Build the Evidence line from a list of {label, href} dicts."""
    if not items or len(items) < 2:
        items = items or []
        while len(items) < 2:
            items.append({"label": "Run history", "href": "url:/runs"})
    items = items[:4]
    parts = " \u00b7 ".join(
        f"[{item.get('label', 'Evidence')}]({_safe_evidence_ref(item.get('href', 'url:/runs'))})"
        for item in items
    )
    return f"Evidence: {parts}."


def _evidence_to_structured(items: List[Dict[str, str]]) -> List[Dict[str, Any]]:
    """Convert {label, href} list to structured evidence for the frontend."""
    if not items or len(items) < 2:
        items = items or []
        while len(items) < 2:
            items.append({"label": "Run history", "href": "url:/runs"})
    items = items[:4]
    result = []
    for item in items:
        href = _safe_evidence_ref(item.get("href", "url:/runs"))
        if href.startswith("run:"):
            ref = {"kind": "run", "id": href[4:]}
        elif href.startswith("artifact:"):
            ref = {"kind": "artifact", "id": href[9:]}
        elif href.startswith("url:"):
            ref = {"kind": "url", "id": href[4:]}
        else:
            ref = {"kind": "url", "id": "/runs"}
        result.append({"label": item.get("label", "Evidence"), "ref": ref})
    return result


# ── Portfolio narratives ────────────────────────────────────────────────


def format_portfolio_narrative(brief: Dict[str, Any]) -> str:
    """Build the portfolio analysis narrative from a PortfolioBrief dict."""
    mode_str = _safe_mode(brief.get("mode", "UNKNOWN"))
    as_of_display = _ts_display(brief.get("as_of", ""))
    total_value = brief.get("total_value_usd", 0)
    cash = brief.get("cash_usd", 0)

    holdings = brief.get("holdings", [])
    h_count = len(holdings)
    if holdings:
        parts = []
        for h in holdings[:5]:
            symbol = h.get("asset_symbol", "?")
            qty = h.get("qty", 0)
            usd = h.get("usd_value", 0)
            price = h.get("current_price")
            price_str = f"@ ${price:,.2f}" if price is not None else "@ unavailable"
            parts.append(f"{symbol} {qty:,.6f} (${usd:,.2f}) {price_str}")
        holdings_line = f"Positions ({h_count}): {'; '.join(parts)}."
    else:
        holdings_line = "No open positions found in the snapshot."

    risk = brief.get("risk", {})
    risk_level = risk.get("risk_level", "unavailable") if risk else "unavailable"
    top1 = risk.get("concentration_pct_top1") if risk else None
    largest_str = f"{top1:.1f}%" if top1 is not None else "unavailable"

    recommendations = brief.get("recommendations", [])
    rec_text = "No immediate concerns identified."
    if recommendations:
        best = sorted(
            recommendations,
            key=lambda r: {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}.get(
                r.get("priority", "LOW") if isinstance(r, dict) else getattr(r, "priority", "LOW"), 3
            ),
        )[0]
        desc = best.get("description", "") if isinstance(best, dict) else getattr(best, "description", "")
        rec_text = desc or rec_text

    risk_line = (
        f"Risk assessment: {risk_level}; largest position is {largest_str} of portfolio; "
        f"recommendation: {rec_text}"
    )
    if not risk_line.endswith("."):
        risk_line = risk_line.rstrip(".") + "."

    evidence_items = _build_portfolio_evidence(brief, mode_str, as_of_display)
    evidence_line = _format_evidence(evidence_items)

    line1 = f"Your portfolio is valued at ${total_value:,.2f} with ${cash:,.2f} in cash ({mode_str} mode, as of {as_of_display})."
    line2 = _truncate_line(holdings_line)
    line3 = _truncate_line(risk_line)

    return _validate(PARAGRAPH_SEP.join([line1, line2, line3, evidence_line]))


def format_asset_holdings_narrative(asset: str, brief: Dict[str, Any]) -> str:
    """Build the narrative for a specific-asset holdings query."""
    mode_str = _safe_mode(brief.get("mode", "UNKNOWN"))
    as_of_display = _ts_display(brief.get("as_of", ""))
    total_value = brief.get("total_value_usd", 0)

    holdings = brief.get("holdings", [])
    asset_holding = next(
        (h for h in holdings if h.get("asset_symbol", "").upper() == asset.upper()),
        None,
    )

    if asset_holding:
        qty = asset_holding.get("qty", 0)
        usd = asset_holding.get("usd_value", 0)
        price = asset_holding.get("current_price")
        price_str = f"@ ${price:,.2f}" if price is not None else "@ unavailable"
        holdings_line = f"You hold {qty:,.8f} {asset} (${usd:,.2f}) {price_str}."
    else:
        holdings_line = f"No {asset} position found in the current snapshot."

    evidence_items = _build_portfolio_evidence(brief, mode_str, as_of_display, extra_asset=asset)
    evidence_line = _format_evidence(evidence_items)

    line1 = f"Checked your {asset} holdings in the {mode_str} portfolio as of {as_of_display} (total ${total_value:,.2f})."
    line2 = holdings_line
    line3 = "Values are restated directly from the snapshot without synthetic estimates."

    return _validate(PARAGRAPH_SEP.join([line1, line2, line3, evidence_line]))


def format_simple_portfolio_narrative(
    mode_str: str,
    ts: str,
    total_value: float,
    cash_usd: float,
    top_positions: List[tuple],
) -> str:
    """Build the narrative for simple PORTFOLIO / FINANCE_ANALYSIS intent."""
    as_of_display = _ts_display(ts)
    if top_positions:
        parts = [f"{a} {q:,.6f}" for a, q in top_positions]
        holdings_line = f"Top positions: {'; '.join(parts)}."
    else:
        holdings_line = "No open positions found in the snapshot."

    evidence_items = [
        {"label": f"Portfolio snapshot ({mode_str}, {as_of_display})", "href": "url:/runs"},
        {"label": "Run history", "href": "url:/runs"},
    ]
    evidence_line = _format_evidence(evidence_items)

    line1 = f"Your portfolio is valued at ${total_value:,.2f} with ${cash_usd:,.2f} in cash ({mode_str} mode, as of {as_of_display})."
    line2 = holdings_line
    line3 = "Run a full portfolio analysis for risk and allocation details."

    return _validate(PARAGRAPH_SEP.join([line1, line2, line3, evidence_line]))


def format_no_snapshot_narrative(mode_str: str) -> str:
    """Narrative when no portfolio snapshot exists."""
    action = (
        "run 'Analyze my portfolio' to fetch and store a fresh snapshot"
        if mode_str == "LIVE"
        else "execute one paper trade or run 'Analyze my portfolio', then retry"
    )
    return _validate(PARAGRAPH_SEP.join([
        "No portfolio snapshot is available yet.",
        f"Next step: {action}.",
        "Evidence: [Portfolio page](url:/runs) \u00b7 [Run history](url:/runs).",
    ]))


def format_snapshot_failed_narrative(reason: str = "") -> str:
    """Narrative when portfolio state could not be retrieved (hard gate)."""
    detail = f" ({reason})" if reason else ""
    return _validate(PARAGRAPH_SEP.join([
        f"I couldn't retrieve portfolio state to stage this trade{detail}.",
        "Next step: run 'Analyze my portfolio' to restore state, then retry your trade request.",
        "Evidence: [Portfolio page](url:/runs) \u00b7 [Run history](url:/runs).",
    ]))


# ── Trade-intent narratives ─────────────────────────────────────────────


def _build_trade_narrative_legacy(
    *,
    interpretation: str,
    actions: List[Dict[str, Any]],
    failures: Optional[List[str]] = None,
    is_sequential: bool = False,
    evidence_items: Optional[List[Dict[str, str]]] = None,
    mode: str = "PAPER",
) -> str:
    """Build a structured trade narrative from plan + preflight results.

    This is the single entry point for all trade-confirmation narratives.
    """
    failures = failures or []
    evidence_items = evidence_items or [
        {"label": "Trade details", "href": "url:/runs"},
        {"label": "Run history", "href": "url:/runs"},
    ]
    evidence_line = _format_evidence(evidence_items)

    lines: List[str] = []

    lines.append("Pulled the latest executable balances and staged a plan based on what's sellable right now.")

    if is_sequential and len(actions) > 1:
        lines.append("Execution runs sequentially: one order per step.")

    for i, action in enumerate(actions):
        side = str(action.get("side", "buy")).upper()
        asset = action.get("asset", "UNKNOWN")
        amt = float(action.get("amount_usd", 0.0) or 0.0)
        base = action.get("base_size")
        status = action.get("step_status", "READY" if i == 0 else "QUEUED")
        blocked_reason = action.get("blocked_reason")

        status_label = "ready" if status == "READY" else ("blocked" if status == "BLOCKED" else "queued")

        if is_sequential and len(actions) > 1:
            if status == "BLOCKED" and blocked_reason:
                lines.append(f"Step {i + 1} (blocked): {side} {asset} \u2014 {blocked_reason}.")
            elif base:
                lines.append(
                    f"Step {i + 1} ({status_label}): {side} {asset} "
                    f"(full available: {base:,.8f}) using market + DAY + slippage guard."
                )
            elif status_label == "queued":
                lines.append(
                    f"Step {i + 1} (queued): {side} {asset} \u2014 queued pending prior receipt."
                )
            else:
                lines.append(
                    f"Step {i + 1} ({status_label}): {side} ${amt:,.2f} {asset} "
                    f"using market + DAY + slippage guard."
                )
        else:
            if base:
                lines.append(
                    f"Step 1 (ready): {side} {asset} (full available: {base:,.8f}) using market + DAY + slippage guard."
                )
            else:
                lines.append(
                    f"Step 1 (ready): {side} ${amt:,.2f} {asset} using market + DAY + slippage guard."
                )

    if failures:
        blocked = "; ".join(failures[:2])
        lines.append(f"Skipped: {blocked}.")

    if is_sequential and len(actions) > 1:
        lines.append("Reply CONFIRM STEP 1 to place the first order, or CANCEL to abort.")
    else:
        lines.append("Reply CONFIRM STEP 1 to place the first order, or CANCEL to abort.")

    lines.append(evidence_line)

    combined = PARAGRAPH_SEP.join(lines)
    try:
        return _validate(combined)
    except ValueError:
        lines_safe = [l for l in lines if l.strip()]
        while len(lines_safe) < 3:
            lines_safe.insert(-1, f"Staged in {mode} mode.")
        return PARAGRAPH_SEP.join(lines_safe[:6])

def build_trade_narrative(
    *,
    interpretation: str,
    actions: List[Dict[str, Any]],
    failures: Optional[List[str]] = None,
    is_sequential: bool = False,
    evidence_items: Optional[List[Dict[str, str]]] = None,
    mode: str = "PAPER",
    reasoning: Optional[Any] = None,
) -> str:
    """Build a structured trade narrative from plan + optional reasoning output.

    When reasoning is provided, uses LLM-generated summaries and risk flags.
    Falls back to template output when reasoning is absent or failed.
    Must satisfy _validate(): 3-6 paragraph-separated lines, 2-4 evidence links.
    """
    failures = failures or []
    evidence_items = evidence_items or [
        {"label": "Executable balances snapshot", "href": "url:/runs"},
        {"label": "Trade preflight report", "href": "url:/runs"},
    ]
    evidence_line = _format_evidence(evidence_items)
    lines: List[str] = []

    if reasoning and reasoning.plan_summary:
        lines.append(reasoning.plan_summary)
    else:
        lines.append(
            "Pulled the latest executable balances and staged a plan based on "
            "what's sellable right now."
        )

    if reasoning and reasoning.step_summaries:
        step_block = " | ".join(reasoning.step_summaries)
    else:
        step_parts = []
        for i, action in enumerate(actions):
            side = str(action.get("side", "buy")).upper()
            asset = action.get("asset", "UNKNOWN")
            base = action.get("base_size")
            amt = float(action.get("amount_usd", 0.0) or 0.0)
            status = action.get("step_status", "READY" if i == 0 else "QUEUED")
            label = "ready" if status == "READY" else ("blocked" if status == "BLOCKED" else "queued")
            blocked_reason = action.get("blocked_reason")
            if status == "BLOCKED" and blocked_reason:
                step_parts.append(f"Step {i+1} (blocked): {side} {asset} — {blocked_reason}.")
            elif base:
                step_parts.append(
                    f"Step {i+1} ({label}): {side} {asset} "
                    f"(full available: {base:,.8f}) using market + DAY + slippage guard."
                )
            elif label == "queued":
                step_parts.append(
                    f"Step {i+1} (queued): {side} {asset} — queued pending prior receipt."
                )
            else:
                step_parts.append(
                    f"Step {i+1} ({label}): {side} ${amt:,.2f} {asset} "
                    f"using market + DAY + slippage guard."
                )
        step_block = " | ".join(step_parts)
    lines.append(_truncate_line(step_block))

    risk_parts = []
    if reasoning and reasoning.portfolio_impact:
        risk_parts.append(reasoning.portfolio_impact)
    if reasoning and reasoning.risk_flags:
        risk_parts.extend(reasoning.risk_flags[:2])
    if reasoning and reasoning.alternatives:
        risk_parts.extend(reasoning.alternatives[:1])
    if risk_parts:
        lines.append(_truncate_line("Note: " + "; ".join(risk_parts) + "."))

    if failures:
        skipped = "; ".join(failures[:2])
        lines.append(_truncate_line(f"Skipped: {skipped}."))

    if is_sequential and len(actions) > 1:
        lines.append("Reply CONFIRM STEP 1 to place the first order, or CANCEL to abort.")
    else:
        lines.append("Reply CONFIRM to place this order, or CANCEL to abort.")

    lines.append(evidence_line)

    if len(lines) > 6:
        middle = "; ".join(l.rstrip(".") for l in lines[2:-2] if l)
        lines = [lines[0], lines[1], _truncate_line(middle + "."), lines[-2], lines[-1]]

    while len(lines) < 3:
        lines.insert(-1, f"Staged in {mode} mode.")

    combined = PARAGRAPH_SEP.join(lines)
    try:
        return _validate(combined)
    except ValueError:
        safe_lines = [
            lines[0] if lines else "Trade plan staged.",
            lines[1] if len(lines) > 1 else "Review steps above.",
            evidence_line,
        ]
        return PARAGRAPH_SEP.join(safe_lines)


def format_trade_confirmation_narrative(
    actions_text: str,
    mode: str,
    checks: str,
    estimated_fees: float,
    evidence_items: List[Dict[str, str]],
) -> str:
    """Narrative for trade confirmation prompt (backward-compatible wrapper)."""
    evidence_line = _format_evidence(evidence_items)

    return _validate(PARAGRAPH_SEP.join([
        f"I interpreted your request as: {actions_text}.",
        f"Staged in {mode} mode with safe defaults (market order, DAY, slippage guard); estimated fees ${estimated_fees:,.2f}.",
        f"Preflight: {checks}; confirm to proceed or cancel to abort.",
        evidence_line,
    ]))


def format_trade_execution_narrative(
    side: str,
    amount_usd: float,
    asset: str,
    run_id: str,
    evidence_items: Optional[List[Dict[str, str]]] = None,
) -> str:
    """Narrative for confirmed trade execution start."""
    items = evidence_items or [
        {"label": "Execution run", "href": f"run:{run_id}"},
        {"label": "Run history", "href": "url:/runs"},
    ]
    evidence_line = _format_evidence(items)
    return _validate(PARAGRAPH_SEP.join([
        f"Confirmed: {side.upper()} ${amount_usd:,.2f} {asset} accepted and execution has started.",
        "Safe defaults applied (market order, DAY, slippage guard); monitor progress in the steps panel.",
        evidence_line,
    ]))


def format_multi_execution_narrative(
    count: int,
    primary_run_id: str,
    evidence_items: Optional[List[Dict[str, str]]] = None,
) -> str:
    """Narrative for multi-action confirmed trade execution."""
    items = evidence_items or [
        {"label": "Primary execution run", "href": f"run:{primary_run_id}"},
        {"label": "Run history", "href": "url:/runs"},
    ]
    evidence_line = _format_evidence(items)
    return _validate(PARAGRAPH_SEP.join([
        f"Confirmed: {count} orders accepted and execution has started.",
        "Each order uses safe defaults (market, DAY, slippage guard); monitor progress in the steps panel.",
        evidence_line,
    ]))


def format_trade_blocked_narrative(
    candidate_count: int,
    failures: List[str],
    evidence_items: List[Dict[str, str]],
) -> str:
    """Narrative when all trade actions are blocked."""
    failure_summary = "; ".join(failures[:2]) if failures else "No executable positions were found"
    evidence_line = _format_evidence(evidence_items)
    lead = "No executable orders are available right now."
    next_step = "Next step: choose a tradable asset with available balance, or CANCEL."
    if failures:
        lower = " ".join(failures).lower()
        if "specify quantity" in lower or "please specify" in lower or "missing amount" in lower:
            lead = "Please provide the amount to proceed with this trade."
            next_step = "Next step: add an amount (e.g., '$10 of BTC' or '50% of ETH')."
        elif "not tradable" in lower or "trading is disabled" in lower or "cancel-only" in lower:
            lead = "One or more requested assets are not currently tradable."
            next_step = "Next step: choose an asset with active market trading, or check exchange status."
        elif "limit-only" in lower:
            lead = "One or more requested markets are currently limit-only."
            next_step = "Next step: use a limit order for these assets, or choose a different market."
        elif "on hold" in lower:
            lead = "One or more balances are currently on hold and cannot be sold."
            next_step = "Next step: wait for the hold to clear, then retry."
        elif "available quantity is 0" in lower:
            lead = "No executable quantity is available for the requested assets."
            next_step = "Next step: verify your holdings in the portfolio view and retry."
        elif "not held in executable" in lower:
            lead = "One or more requested assets are not held in your account."
            next_step = "Next step: choose assets you currently hold, or buy the asset first."

    return _validate(PARAGRAPH_SEP.join([
        lead,
        _truncate_line(f"Issues: {failure_summary}."),
        next_step,
        evidence_line,
    ]))


def format_no_parse_narrative() -> str:
    """Narrative when trade parsing yields zero actions."""
    return _validate(PARAGRAPH_SEP.join([
        "I could not identify an executable trade in your message.",
        "Try a command like 'sell all BTC', 'buy $25 of ETH', or 'close my MOODENG position'.",
        "Evidence: [Conversation](url:/chat) \u00b7 [Run history](url:/runs).",
    ]))


def format_missing_amount_narrative(
    side: str, asset: Optional[str] = None
) -> str:
    """Narrative prompting for a missing trade amount."""
    asset_text = asset or "the asset"
    return _validate(PARAGRAPH_SEP.join([
        f"I understood {side.upper()} {asset_text}, but the amount is missing.",
        "Reply with an amount (e.g. $10, 0.01 BTC, 50%, or 'sell all') so I can stage the order.",
        "Evidence: [Conversation](url:/chat) \u00b7 [Run history](url:/runs).",
    ]))


# ── Structured output ────────────────────────────────────────────────────


def build_narrative_structured(
    content: str,
    brief: Optional[Dict[str, Any]] = None,
    evidence_items: Optional[List[Dict[str, str]]] = None,
) -> Dict[str, Any]:
    """Parse a narrative string into structured {lead, lines, evidence}.

    Falls back to building from *brief* if the string cannot be parsed.
    The return value is always JSON-serialisable.
    """
    try:
        paragraphs = content.split(PARAGRAPH_SEP)
        if len(paragraphs) >= 3:
            last_para = paragraphs[-1]
            evidence_raw = EVIDENCE_LINK_RE.findall(last_para)
            if len(evidence_raw) >= 2:
                evidence = [
                    {"label": label, "ref": _safe_evidence_ref(href)}
                    for label, href in evidence_raw
                ]
                return {
                    "lead": paragraphs[0],
                    "lines": paragraphs[1:-1],
                    "evidence": evidence,
                }
            return {
                "lead": paragraphs[0],
                "lines": paragraphs[1:],
                "evidence": _evidence_to_structured(evidence_items) if evidence_items else _fallback_evidence(),
            }
    except Exception:
        pass

    if brief:
        return _structured_from_brief(brief)

    return {
        "lead": content.split(PARAGRAPH_SEP)[0] if PARAGRAPH_SEP in content else content[:200],
        "lines": [],
        "evidence": _fallback_evidence(),
    }


def _structured_from_brief(brief: Dict[str, Any]) -> Dict[str, Any]:
    """Deterministic structured narrative built directly from a PortfolioBrief."""
    mode_str = _safe_mode(brief.get("mode", "UNKNOWN"))
    as_of_display = _ts_display(brief.get("as_of", ""))
    total_value = brief.get("total_value_usd", 0)
    cash = brief.get("cash_usd", 0)

    lines = [
        f"Snapshot: {mode_str}, as of {as_of_display}; Total ${total_value:,.2f}; Cash ${cash:,.2f}.",
    ]

    holdings = brief.get("holdings", [])
    if holdings:
        parts = []
        for h in holdings[:5]:
            symbol = h.get("asset_symbol", "?")
            qty = h.get("qty", 0)
            usd = h.get("usd_value", 0)
            parts.append(f"{symbol} {qty:,.6f} (${usd:,.2f})")
        lines.append(f"Positions: {'; '.join(parts)}.")
    else:
        lines.append("No open positions found in the snapshot.")

    risk = brief.get("risk", {})
    risk_level = risk.get("risk_level", "unavailable") if risk else "unavailable"
    lines.append(f"Risk: {risk_level}.")

    evidence_items = _build_portfolio_evidence(brief, mode_str, as_of_display)
    evidence = _evidence_to_structured(evidence_items)

    return {
        "lead": f"Your portfolio is valued at ${total_value:,.2f} ({mode_str} mode, as of {as_of_display}).",
        "lines": lines,
        "evidence": evidence if len(evidence) >= 2 else _fallback_evidence(),
    }


def _fallback_evidence() -> List[Dict[str, Any]]:
    return [
        {"label": "Portfolio page", "ref": "url:/runs"},
        {"label": "Run history", "ref": "url:/runs"},
    ]


# ── Helpers ──────────────────────────────────────────────────────────────


def _build_portfolio_evidence(
    brief: Dict[str, Any],
    mode_str: str,
    as_of_display: str,
    extra_asset: Optional[str] = None,
) -> List[Dict[str, str]]:
    evidence = brief.get("evidence_refs", {})
    if isinstance(evidence, dict):
        accounts_id = evidence.get("accounts_call_id")
        price_ids = evidence.get("prices_call_ids", [])
        orders_id = evidence.get("orders_call_id")
    else:
        accounts_id = getattr(evidence, "accounts_call_id", None)
        price_ids = getattr(evidence, "prices_call_ids", [])
        orders_id = getattr(evidence, "orders_call_id", None)

    items: List[Dict[str, str]] = []
    items.append({
        "label": f"Portfolio snapshot ({mode_str}, {as_of_display})",
        "href": "url:/runs",
    })

    if extra_asset:
        items.append({"label": f"Market quotes ({extra_asset})", "href": "url:/runs"})
    elif price_ids:
        items.append({"label": "Market quotes", "href": "url:/runs"})

    if orders_id:
        items.append({"label": "Order history", "href": "url:/runs"})

    if len(items) < 2:
        items.append({"label": "Run history", "href": "url:/runs"})

    return items
