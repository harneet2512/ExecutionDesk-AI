"""Response templates for message-only intents (no run creation)."""
from typing import Dict, List, Optional


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
    asset_text = f" {asset}" if asset else ""
    return {
        "content": f"How much{asset_text} do you want to {side}? (e.g., $10 or 0.01 BTC)",
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
    asset_class: str = "CRYPTO"
) -> Dict:
    """Generate trade confirmation prompt (required for both LIVE and PAPER).

    For STOCK asset class with ASSISTED_LIVE mode, generates an Order Ticket
    that the user executes manually in their brokerage.
    """
    # Handle ASSISTED_LIVE mode for stocks
    if asset_class == "STOCK" or mode == "ASSISTED_LIVE":
        price_text = f"Estimated price: ${estimated_price:,.2f}." if estimated_price else ""
        content = f"""ORDER TICKET CONFIRMATION

I will generate an order ticket for you to {side.upper()} ${amount_usd:.2f} of {asset}. {price_text}

This is not automated execution. After confirming you will receive an order ticket with details. Execute the order manually in your brokerage (Schwab, Fidelity, etc.) and submit your execution receipt to complete the workflow. EOD (end-of-day) stock data is used for analysis.

Type CONFIRM to generate the order ticket or CANCEL to abort."""

        return {
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
                "confirmation_id": confirmation_id
            },
            "confirmation_id": confirmation_id
        }

    # Crypto: LIVE or PAPER mode
    mode_label = "LIVE ORDER" if mode == "LIVE" else "PAPER TRADE (Simulation)"

    # Estimate fees (0.6% for market orders on Coinbase)
    estimated_fees = amount_usd * 0.006

    price_text = f"Estimated price: ${estimated_price:,.2f}." if estimated_price else ""
    live_warning = "This is a real trade using real funds." if mode == "LIVE" else "This is a simulated trade (no real funds)."

    content = f"""{mode_label} CONFIRMATION

I am about to place a {mode} market {side.upper()} for ${amount_usd:.2f} of {asset}. {price_text}

Estimated fees: ${estimated_fees:.2f}. Total notional: ${amount_usd:.2f}. {live_warning}

Type CONFIRM to place this {mode} order or CANCEL to abort."""

    return {
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
            "confirmation_id": confirmation_id
        },
        "confirmation_id": confirmation_id
    }


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
