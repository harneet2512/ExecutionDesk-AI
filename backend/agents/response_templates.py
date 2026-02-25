"""Response templates for message-only intents (no run creation)."""
from typing import Any, Dict, List, Optional


def greeting_response() -> Dict:
    """Return greeting response with suggestions."""
    return {
        "content": "Hi - I'm your financial assistant. I can analyze markets (crypto & stocks), review your portfolio, or execute trades. Try asking me something!",
        "suggestions": [
            "Find the most profitable crypto in the last 24h",
            "Analyze my portfolio risk and allocation",
            "Buy $10 of BTC in PAPER mode",
            "Buy $50 of AAPL stock"
        ],
        "run_id": None,
        "intent": "GREETING",
        "status": "COMPLETED"
    }


def capabilities_response() -> Dict:
    """Return capabilities/help response."""
    return {
        "content": """I can help with:

**Market Analysis**
• Price data, returns, volatility, candles
• Top gainers/losers, technical indicators
• Comparative analysis (BTC vs ETH, AAPL vs MSFT)

**Portfolio & Risk**
• Allocation, exposure, P&L
• Drawdown, risk metrics, diversification

**Trading - Crypto (Automated)**
• Paper/live order execution via Coinbase
• Supported: BTC, ETH, SOL, ADA, DOT, MATIC, AVAX, LINK, UNI, ATOM

**Trading - Stocks (Order Tickets)**
• Generate order tickets for manual execution
• Supported: AAPL, MSFT, NVDA, TSLA, SPY, and more
• EOD data via Polygon.io

**App Features**
• View runs, telemetry, evaluations
• Interpret steps panel and charts

**Example Prompts:**
• "Analyze BTC volatility over the last 24 hours"
• "What's the most profitable crypto today?"
• "Buy $10 of ETH in PAPER mode"
• "Buy $50 of AAPL stock" (generates order ticket)
• "Show me my portfolio allocation"
• "What's my current P&L?"
""",
        "run_id": None,
        "intent": "CAPABILITIES_HELP",
        "status": "COMPLETED"
    }


def out_of_scope_response() -> Dict:
    """Return out-of-scope refusal with redirect."""
    return {
        "content": "I'm a financial/trading assistant, so I can't help with that. Ask me about market analysis, portfolio risk, or executing a trade.",
        "suggestions": [
            "What's the most profitable crypto today?",
            "Analyze my portfolio allocation",
            "Execute a paper trade for $10 of BTC"
        ],
        "run_id": None,
        "intent": "OUT_OF_SCOPE",
        "status": "COMPLETED"
    }


def app_diagnostics_response(query: str) -> Dict:
    """Return app diagnostics explanation."""
    return {
        "content": """**App Features:**

• **Runs**: Each trading command creates a run that executes your request step-by-step
• **Steps Panel**: Shows real-time progress of your run (research, ranking, execution)
• **Telemetry**: Performance metrics for each run (duration, tool calls, events, errors)
• **Evals**: Evaluation results that assess run quality and correctness
• **Charts**: Visual representations of market data, portfolio allocation, and performance

To view these features, use the navigation icons on the left sidebar.

Try a trading command to see runs and steps in action!
""",
        "run_id": None,
        "intent": "APP_DIAGNOSTICS",
        "status": "COMPLETED"
    }


def portfolio_response_template() -> Dict:
    """Template for portfolio queries (may create run depending on implementation)."""
    # This can be customized based on whether portfolio queries should create runs
    # For now, returning a template that indicates run creation is optional
    return {
        "content": "Analyzing your portfolio...",
        "run_id": None,  # Will be set if run is created
        "intent": "PORTFOLIO",
        "status": "COMPLETED"
    }


def missing_amount_prompt(side: str, asset: Optional[str] = None) -> Dict:
    """Prompt user for missing amount."""
    from backend.agents.narrative import format_missing_amount_narrative
    return {
        "content": format_missing_amount_narrative(side, asset),
        "run_id": None,
        "intent": "TRADE_EXECUTION_INCOMPLETE",
        "status": "AWAITING_INPUT"
    }


def trade_confirmation_prompt(
    side: str,
    asset: str,
    amount_usd: float,
    mode: str,
    confirmation_id: Optional[str] = None,
    estimated_price: Optional[float] = None,
    asset_class: str = "CRYPTO",
    actions: Optional[List[Dict]] = None,
    failures: Optional[List[str]] = None,
    evidence_text: Optional[str] = None,
    evidence_links: Optional[List[Dict[str, str]]] = None,
    trade_reasoning: Optional[Any] = None,
) -> Dict:
    """Generate trade confirmation prompt with sequential step layout.

    For multi-action trades the narrative shows Step 1 as READY and
    remaining steps as Queued, reflecting the one-order-per-confirm
    broker submission policy.
    """
    from backend.agents.narrative import build_trade_narrative, build_narrative_structured

    actions = actions or [{"side": side, "asset": asset, "amount_usd": amount_usd}]
    failures = failures or []
    is_sequential = len(actions) > 1

    ev_items = evidence_links[:4] if evidence_links else [
        {"label": evidence_text or "Executable balances snapshot", "href": "url:/runs"},
        {"label": "Trade preflight report", "href": "url:/runs"},
    ]

    if is_sequential:
        parts = []
        for a in actions:
            a_side = str(a.get("side", "buy")).upper()
            a_asset = a.get("asset", "UNKNOWN")
            a_base = a.get("base_size")
            if a_base:
                parts.append(f"{a_side} full position of {a_asset}")
            else:
                a_amt = float(a.get("amount_usd", 0.0) or 0.0)
                parts.append(f"{a_side} ${a_amt:,.2f} of {a_asset}")
        interpretation = " and ".join(parts)
    else:
        first = actions[0]
        first_base = first.get("base_size")
        if first_base:
            interpretation = (
                f"{str(first.get('side', 'buy')).upper()} full position of "
                f"{first.get('asset', 'UNKNOWN')}"
            )
        else:
            interpretation = (
                f"{str(first.get('side', 'buy')).upper()} "
                f"${float(first.get('amount_usd', 0.0) or 0.0):,.2f} of "
                f"{first.get('asset', 'UNKNOWN')}"
            )

    content = build_trade_narrative(
        interpretation=interpretation,
        actions=actions,
        failures=failures,
        is_sequential=is_sequential,
        evidence_items=ev_items,
        mode=mode,
        reasoning=trade_reasoning,
    )

    narrative_structured = None
    try:
        narrative_structured = build_narrative_structured(content, evidence_items=ev_items)
    except Exception:
        pass

    resp: Dict = {
        "content": content,
        "run_id": None,
        "intent": "TRADE_CONFIRMATION_PENDING",
        "status": "AWAITING_CONFIRMATION",
        "pending_trade": {
            "side": side,
            "asset": asset,
            "amount_usd": amount_usd,
            "mode": mode,
            "asset_class": asset_class,
            "actions": actions,
            "confirmation_id": confirmation_id
        },
        "confirmation_id": confirmation_id,
    }
    if narrative_structured:
        resp["narrative_structured"] = narrative_structured
    return resp


def trade_cancelled_response() -> Dict:
    """Response when user cancels pending trade."""
    return {
        "content": "Trade cancelled.",
        "run_id": None,
        "intent": "TRADE_CANCELLED",
        "status": "COMPLETED"
    }


def confirmation_not_recognized_response() -> Dict:
    """Response when user doesn't say CONFIRM or CANCEL."""
    return {
        "content": "Not confirmed. Reply CONFIRM to execute the pending trade or CANCEL to abort.",
        "run_id": None,
        "intent": "CONFIRMATION_NOT_RECOGNIZED",
        "status": "AWAITING_CONFIRMATION"
    }


def pending_trade_expired_response() -> Dict:
    """Response when pending trade has expired."""
    return {
        "content": "Your pending trade has expired (5 minute timeout). Please submit your trade request again.",
        "run_id": None,
        "intent": "PENDING_TRADE_EXPIRED",
        "status": "COMPLETED"
    }
