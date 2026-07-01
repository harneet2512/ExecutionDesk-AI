"""Vercel serverless function for the ExecutionDesk AI MCP server.

Exposes prediction market tools as a Streamable HTTP MCP endpoint.
Stateless — no session state persists between invocations.
"""
import os
import json

import httpx
from fastmcp import FastMCP

mcp = FastMCP("ExecutionDesk AI")

GAMMA_API = "https://gamma-api.polymarket.com"
CLOB_API = "https://clob.polymarket.com"
STRAPI_API = "https://strapi-matic.polymarket.com"


def _http_get(url: str, params: dict | None = None, timeout: float = 15.0):
    resp = httpx.get(url, params=params, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


# -- Polymarket market data tools -------------------------------------------

@mcp.tool()
def search_markets(query: str, limit: int = 10) -> str:
    """Search Polymarket prediction markets by keyword."""
    try:
        data = _http_get(f"{GAMMA_API}/markets", params={
            "text_query": query,
            "limit": limit,
            "closed": "false",
            "order": "volume",
            "ascending": "false",
        })
    except Exception as e:
        return f"API error: {e}"

    if not data:
        return f"No markets found for '{query}'."
    lines = [f"Found {len(data)} markets for '{query}':\n"]
    for i, m in enumerate(data, 1):
        yes_price = float(m.get("outcomePrices", "[]").strip("[]").split(",")[0].strip('"') or 0)
        vol = float(m.get("volume", 0) or 0)
        cid = m.get("conditionId", "") or m.get("condition_id", "")
        lines.append(f"{i}. {m.get('question', '?')}")
        lines.append(f"   YES: {yes_price * 100:.0f}%  |  Volume: ${vol:,.0f}  |  ID: {cid[:16]}...")
        end = m.get("endDate") or m.get("end_date_iso")
        if end:
            lines.append(f"   Resolves: {str(end)[:10]}")
        lines.append("")
    return "\n".join(lines)


@mcp.tool()
def get_market_detail(condition_id: str) -> str:
    """Get detailed info about a Polymarket market by condition ID."""
    try:
        data = _http_get(f"{GAMMA_API}/markets", params={"condition_id": condition_id})
    except Exception as e:
        return f"API error: {e}"

    if not data:
        return f"Market not found: {condition_id}"
    market = data[0] if isinstance(data, list) else data
    outcomes = market.get("outcomes", "[]")
    if isinstance(outcomes, str):
        try:
            outcomes = json.loads(outcomes)
        except Exception:
            outcomes = [outcomes]
    prices = market.get("outcomePrices", "[]")
    if isinstance(prices, str):
        try:
            prices = json.loads(prices)
        except Exception:
            prices = []

    result = {
        "question": market.get("question"),
        "description": (market.get("description") or "")[:500],
        "outcomes": outcomes,
        "outcome_prices": [float(p) for p in prices] if prices else [],
        "volume": float(market.get("volume", 0) or 0),
        "liquidity": float(market.get("liquidity", 0) or 0),
        "condition_id": market.get("conditionId"),
        "end_date": market.get("endDate"),
        "active": market.get("active"),
        "closed": market.get("closed"),
    }
    tokens = market.get("clobTokenIds")
    if tokens:
        if isinstance(tokens, str):
            try:
                tokens = json.loads(tokens)
            except Exception:
                tokens = [tokens]
        result["token_ids"] = tokens
    return json.dumps(result, indent=2, default=str)


@mcp.tool()
def get_order_book(token_id: str) -> str:
    """Get the order book for a Polymarket outcome token."""
    try:
        data = _http_get(f"{CLOB_API}/book", params={"token_id": token_id})
    except Exception as e:
        return f"API error: {e}"

    bids = sorted(data.get("bids", []), key=lambda x: float(x.get("price", 0)), reverse=True)[:5]
    asks = sorted(data.get("asks", []), key=lambda x: float(x.get("price", 0)))[:5]
    best_bid = float(bids[0]["price"]) if bids else 0
    best_ask = float(asks[0]["price"]) if asks else 1
    spread = best_ask - best_bid

    lines = [f"Order Book (spread: {spread:.4f})\n"]
    lines.append("  BIDS:")
    for b in bids:
        lines.append(f"    ${float(b['price']):.2f}  x  {float(b.get('size', 0)):,.0f}")
    lines.append("  ASKS:")
    for a in asks:
        lines.append(f"    ${float(a['price']):.2f}  x  {float(a.get('size', 0)):,.0f}")
    return "\n".join(lines)


@mcp.tool()
def get_price_history(token_id: str, interval: str = "1w", fidelity: int = 60) -> str:
    """Get historical probability data for a Polymarket outcome token."""
    try:
        data = _http_get(f"{STRAPI_API}/prices-history", params={
            "market": token_id,
            "interval": interval,
            "fidelity": fidelity,
        })
    except Exception as e:
        return f"API error: {e}"

    points = data.get("history", data) if isinstance(data, dict) else data
    if not points:
        return "No price history data."

    prices = []
    for p in points:
        if isinstance(p, dict):
            prices.append(float(p.get("p", p.get("price", 0))))
        else:
            prices.append(float(p))
    if not prices:
        return "No price data."

    current = prices[-1] * 100
    low = min(prices) * 100
    high = max(prices) * 100
    lines = [
        f"Price history ({interval}, {len(points)} points):",
        f"  Current: {current:.1f}%",
        f"  Low:     {low:.1f}%",
        f"  High:    {high:.1f}%",
        "",
    ]
    width = min(50, len(prices))
    step = max(1, len(prices) // width)
    sampled = prices[::step][:width]
    lo, hi = min(sampled), max(sampled)
    rng = hi - lo or 0.01
    for row in range(8, -1, -1):
        threshold = lo + (rng * row / 8)
        label = f"{threshold * 100:5.1f}% |" if row in (0, 4, 8) else "       |"
        bar = "".join("#" if v >= threshold else " " for v in sampled)
        lines.append(f"  {label}{bar}")
    lines.append(f"        +{'-' * len(sampled)}")
    return "\n".join(lines)


@mcp.tool()
def get_recent_trades(condition_id: str, limit: int = 20) -> str:
    """Get recent trades for a Polymarket market."""
    try:
        # Get market detail to find token IDs
        markets = _http_get(f"{GAMMA_API}/markets", params={"condition_id": condition_id})
        if not markets:
            return "Market not found."
        market = markets[0] if isinstance(markets, list) else markets
        tokens = market.get("clobTokenIds", "[]")
        if isinstance(tokens, str):
            tokens = json.loads(tokens)
        if not tokens:
            return "No token IDs found for this market."

        all_trades = []
        for tid in tokens[:2]:
            try:
                data = _http_get(f"{CLOB_API}/trades", params={
                    "asset_id": tid,
                    "limit": limit,
                })
                if isinstance(data, list):
                    all_trades.extend(data)
            except Exception:
                pass

        if not all_trades:
            return "No recent trades."

        lines = [f"Recent {min(len(all_trades), limit)} trades:\n"]
        for t in all_trades[:limit]:
            side = t.get("side", "?")
            price = float(t.get("price", 0))
            size = float(t.get("size", 0))
            ts = t.get("created_at", t.get("timestamp", ""))
            outcome = t.get("outcome", t.get("asset_id", ""))[:12]
            lines.append(f"  {side:>4}  ${price:.2f}  x  {size:>8,.0f}  {outcome}  {str(ts)[:19]}")
        return "\n".join(lines)
    except Exception as e:
        return f"Error fetching trades: {e}"


# -- Platform tools (call backend REST API) ---------------------------------

@mcp.tool()
def execute_trade(command: str) -> str:
    """Send a natural language trade command to ExecutionDesk."""
    base = os.environ.get("EXECUTIONDESK_API_URL", "http://localhost:8000")
    try:
        resp = httpx.post(
            f"{base}/api/v1/chat/command",
            json={"text": command},
            headers={"X-Dev-Tenant": "t_default", "Content-Type": "application/json"},
            timeout=30.0,
        )
        if resp.status_code >= 400:
            try:
                err = resp.json()
                err_detail = err.get("error", err.get("detail", err))
                if isinstance(err_detail, dict):
                    msg = err_detail.get("message", str(err_detail))
                    remediation = err_detail.get("remediation", "")
                    return f"Error: {msg}" + (f"\nRemediation: {remediation}" if remediation else "")
                return f"Error ({resp.status_code}): {err_detail}"
            except Exception:
                return f"Error ({resp.status_code}): {resp.text[:500]}"
        data = resp.json()
        run_id = data.get("run_id")
        confirmation_id = data.get("confirmation_id")
        message = data.get("message", "")
        lines = []
        if message:
            lines.append(message)
        if confirmation_id:
            lines.append(f"\nConfirmation required. ID: {confirmation_id}")
            lines.append(f"Use confirm_trade('{confirmation_id}') to execute.")
        if run_id:
            lines.append(f"\nRun ID: {run_id}")
        if not lines:
            return json.dumps(data, indent=2, default=str)
        return "\n".join(lines)
    except httpx.ConnectError:
        return f"Cannot connect to ExecutionDesk backend at {base}. Backend must be running for trade execution."
    except Exception as e:
        return f"Trade execution failed: {e}"


@mcp.tool()
def confirm_trade(confirmation_id: str) -> str:
    """Confirm a pending trade that requires human approval."""
    base = os.environ.get("EXECUTIONDESK_API_URL", "http://localhost:8000")
    try:
        resp = httpx.post(
            f"{base}/api/v1/chat/command",
            json={"text": "CONFIRM", "confirmation_id": confirmation_id},
            headers={"X-Dev-Tenant": "t_default", "Content-Type": "application/json"},
            timeout=30.0,
        )
        if resp.status_code >= 400:
            try:
                err = resp.json()
                return f"Confirmation failed: {json.dumps(err, default=str)}"
            except Exception:
                return f"Confirmation failed ({resp.status_code}): {resp.text[:500]}"
        data = resp.json()
        run_id = data.get("run_id", "unknown")
        return f"Trade confirmed. Run ID: {run_id}"
    except httpx.ConnectError:
        return f"Cannot connect to backend at {base}."
    except Exception as e:
        return f"Confirmation failed: {e}"


@mcp.tool()
def system_health() -> str:
    """Check ExecutionDesk platform health."""
    base = os.environ.get("EXECUTIONDESK_API_URL", "http://localhost:8000")
    try:
        resp = httpx.get(f"{base}/api/v1/ops/health", timeout=5.0)
        resp.raise_for_status()
        return json.dumps(resp.json(), indent=2, default=str)
    except httpx.ConnectError:
        return f"Backend not reachable at {base}."
    except Exception as e:
        return f"Health check failed: {e}"


# ---------------------------------------------------------------------------
# ASGI app for Vercel
# ---------------------------------------------------------------------------

app = mcp.http_app(path="/api/mcp", stateless_http=True)
