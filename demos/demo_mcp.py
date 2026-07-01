"""Demo MCP server: real Polymarket data + paper trade execution.

Run as stdio for Claude Code:
    python demos/demo_mcp.py
"""
import json
import uuid
import re
import httpx
from fastmcp import FastMCP

mcp = FastMCP("ExecutionDesk AI")

GAMMA_API = "https://gamma-api.polymarket.com"
CLOB_API = "https://clob.polymarket.com"

_market_cache = {}
_last_ask_price = {}
_pending_trades = {}


def _http_get(url, params=None, timeout=15.0):
    resp = httpx.get(url, params=params, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def _parse_json_field(val, default=None):
    if default is None:
        default = []
    if isinstance(val, str):
        try:
            return json.loads(val)
        except (json.JSONDecodeError, TypeError):
            return default
    return val if val else default


def _cache_market(m):
    cid = m.get("conditionId", "") or m.get("condition_id", "")
    if cid:
        _market_cache[cid] = m


@mcp.tool()
def search_markets(query: str, limit: int = 10) -> str:
    """Search Polymarket prediction markets by keyword."""
    try:
        events = _http_get(f"{GAMMA_API}/events", params={
            "closed": "false",
            "limit": 50,
            "order": "volume",
            "ascending": "false",
        })
    except Exception as e:
        return f"API error: {e}"

    if not events:
        return f"No markets found for '{query}'."

    query_lower = query.lower()
    query_words = query_lower.split()

    scored = []
    for ev in events:
        title = (ev.get("title") or "").lower()
        score = sum(2 for w in query_words if w in title)
        if score == 0:
            for m in ev.get("markets", []):
                q = (m.get("question") or "").lower()
                if any(w in q for w in query_words):
                    score = 1
                    break
        if score > 0:
            scored.append((score, ev))

    if not scored:
        scored = [(0, ev) for ev in events[:limit]]

    scored.sort(key=lambda x: (-x[0], -float(x[1].get("volume", 0) or 0)))
    matched_events = [ev for _, ev in scored[:3]]

    all_markets = []
    for ev in matched_events:
        for m in ev.get("markets", []):
            m["_event_title"] = ev.get("title", "")
            _cache_market(m)
            all_markets.append(m)

    all_markets.sort(key=lambda m: float(m.get("volume", 0) or 0), reverse=True)
    top = all_markets[:limit]

    if not top:
        return f"No markets found for '{query}'."

    lines = [f"Found {len(top)} markets for '{query}':\n"]
    for i, m in enumerate(top, 1):
        prices = _parse_json_field(m.get("outcomePrices", "[]"))
        yes_price = float(prices[0]) * 100 if prices else 0
        vol = float(m.get("volume", 0) or 0)
        cid = m.get("conditionId", "") or m.get("condition_id", "")
        tokens = _parse_json_field(m.get("clobTokenIds"))
        lines.append(f"{i}. {m.get('question', '?')}")
        lines.append(f"   YES: {yes_price:.0f}%  |  Volume: ${vol:,.0f}  |  ID: {cid}")
        if tokens:
            lines.append(f"   Token: {tokens[0]}")
        end = m.get("endDate") or m.get("end_date_iso")
        if end:
            lines.append(f"   Resolves: {str(end)[:10]}")
        lines.append("")
    return "\n".join(lines)


@mcp.tool()
def get_market_detail(condition_id: str) -> str:
    """Get detailed info about a Polymarket market by condition ID."""
    market = _market_cache.get(condition_id)
    if not market:
        try:
            data = _http_get(f"{GAMMA_API}/markets", params={"condition_id": condition_id})
            if data:
                market = data[0] if isinstance(data, list) else data
        except Exception as e:
            return f"API error: {e}"
    if not market:
        return f"Market not found: {condition_id}"

    outcomes = _parse_json_field(market.get("outcomes", "[]"))
    prices = _parse_json_field(market.get("outcomePrices", "[]"))
    tokens = _parse_json_field(market.get("clobTokenIds"))

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
    if tokens:
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
    _last_ask_price[token_id] = best_ask
    bid_depth = sum(float(b.get("size", 0)) for b in data.get("bids", []))
    ask_depth = sum(float(a.get("size", 0)) for a in data.get("asks", []))
    lines = [f"Order Book (spread: {spread:.4f}, bid depth: {bid_depth:,.0f}, ask depth: {ask_depth:,.0f})\n"]
    lines.append("  BIDS:")
    for b in bids:
        lines.append(f"    ${float(b['price']):.2f}  x  {float(b.get('size', 0)):,.0f}")
    lines.append("  ASKS:")
    for a in asks:
        lines.append(f"    ${float(a['price']):.2f}  x  {float(a.get('size', 0)):,.0f}")
    return "\n".join(lines)


@mcp.tool()
def get_price_history(token_id: str, interval: str = "max", fidelity: int = 60) -> str:
    """Get historical probability data for a Polymarket outcome token."""
    try:
        data = _http_get(f"{CLOB_API}/prices-history", params={
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
def execute_trade(command: str) -> str:
    """Stage a prediction market trade (PAPER mode). Returns a confirmation_id."""
    side_match = re.search(r'\b(buy|sell)\b', command, re.IGNORECASE)
    qty_match = re.search(r'\b(\d+)\b', command)
    outcome_match = re.search(r'\b(YES|NO)\b', command, re.IGNORECASE)

    side = (side_match.group(1).upper() if side_match else "BUY")
    qty = int(qty_match.group(1)) if qty_match else 10
    outcome = (outcome_match.group(1).upper() if outcome_match else "YES")
    asset = re.sub(r'\b(buy|sell)\b\s*\d*\s*(YES|NO)?\s*(shares?\s*(of)?)?',
                   '', command, flags=re.IGNORECASE).strip() or "prediction market"

    price = max(_last_ask_price.values()) if _last_ask_price else 0.50
    cost = round(qty * price, 2)
    payout = round(qty * 1.00, 2)
    conf_id = f"conf_{uuid.uuid4().hex[:12]}"

    _pending_trades[conf_id] = {
        "side": side, "qty": qty, "outcome": outcome,
        "asset": asset, "price": price, "cost": cost,
    }

    return (
        f"Order staged (PAPER mode):\n"
        f"  {side} {qty} {outcome} shares — {asset}\n"
        f"  Price: ${price:.2f}/share | Est. cost: ${cost:.2f}\n"
        f"  Max payout: ${payout:.2f} (if {outcome})\n\n"
        f"Confirmation required. ID: {conf_id}\n"
        f"Use confirm_trade('{conf_id}') to execute."
    )


@mcp.tool()
def confirm_trade(confirmation_id: str) -> str:
    """Confirm a pending prediction market trade."""
    trade = _pending_trades.pop(confirmation_id, None)
    if not trade:
        return f"No pending trade for '{confirmation_id}'."
    run_id = f"run_{uuid.uuid4().hex[:16]}"
    return (
        f"Trade FILLED (PAPER mode):\n"
        f"  {trade['side']} {trade['qty']} {trade['outcome']} shares — {trade['asset']}\n"
        f"  Fill price: ${trade['price']:.2f}/share | Total: ${trade['cost']:.2f}\n"
        f"  Max payout: ${trade['qty'] * 1.00:.2f}\n"
        f"  Run ID: {run_id}\n"
        f"  Status: COMPLETED | Mode: PAPER"
    )


if __name__ == "__main__":
    mcp.run()
