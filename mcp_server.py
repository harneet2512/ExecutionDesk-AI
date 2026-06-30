"""ExecutionDesk AI — MCP Server

A Model Context Protocol server that exposes the ExecutionDesk platform
as tools for Claude Code, Codex, or any MCP-compatible client.

Run standalone:
    python mcp_server.py

Add to Claude Code (~/.claude.json):
    {
      "mcpServers": {
        "executiondesk": {
          "command": "python",
          "args": ["D:/ExecutionDesk-AI/mcp_server.py"],
          "env": {"DATABASE_URL": "postgresql://edai:edai@localhost:5432/executiondesk"}
        }
      }
    }

Requires the backend to be importable (run from the project root).
"""
import os
import sys
import json
import asyncio

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("DATABASE_URL", "postgresql://edai:edai@localhost:5432/executiondesk")
os.environ.setdefault("TEST_AUTH_BYPASS", "true")

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("ExecutionDesk AI")


# ---------------------------------------------------------------------------
# Polymarket — prediction market tools
# ---------------------------------------------------------------------------

@mcp.tool()
def search_markets(query: str, limit: int = 10) -> str:
    """Search Polymarket prediction markets by keyword.

    Returns active markets with YES/NO probabilities, volume, and liquidity.
    Examples: "election", "bitcoin price", "FIFA", "AI", "Fed rate cut"
    """
    from backend.providers.polymarket_market_data import PolymarketMarketDataProvider
    provider = PolymarketMarketDataProvider()
    markets = provider.search_markets(query, limit=limit)
    if not markets:
        return f"No markets found for '{query}'."

    lines = [f"Found {len(markets)} markets for '{query}':\n"]
    for i, m in enumerate(markets, 1):
        yes_pct = f"{m['yes_price'] * 100:.0f}%"
        vol = f"${m['volume']:,.0f}"
        lines.append(f"{i}. {m['question']}")
        lines.append(f"   YES: {yes_pct}  |  Volume: {vol}  |  ID: {m['condition_id'][:16]}...")
        if m.get("end_date"):
            lines.append(f"   Resolves: {m['end_date'][:10]}")
        lines.append("")
    return "\n".join(lines)


@mcp.tool()
def get_market_detail(condition_id: str) -> str:
    """Get detailed information about a specific Polymarket prediction market.

    Use the condition_id from search_markets results.
    Returns outcomes, token IDs, prices, volume, liquidity, and end date.
    """
    from backend.providers.polymarket_market_data import PolymarketMarketDataProvider
    provider = PolymarketMarketDataProvider()
    detail = provider.get_market_detail(condition_id)
    if not detail:
        return f"Market not found: {condition_id}"
    return json.dumps(detail, indent=2, default=str)


@mcp.tool()
def get_order_book(token_id: str) -> str:
    """Get the current order book (bids and asks) for a Polymarket outcome token.

    Use token_id from get_market_detail results.
    Returns best bid/ask, spread, and depth.
    """
    from backend.providers.polymarket_market_data import PolymarketMarketDataProvider
    provider = PolymarketMarketDataProvider()
    book = provider.get_order_book(token_id)
    if not book:
        return f"No order book data for token: {token_id}"

    bids = book.get("bids", [])[:5]
    asks = book.get("asks", [])[:5]
    spread = book.get("spread", 0)
    depth = book.get("depth", {})

    lines = [f"Order Book (spread: {spread:.4f})\n"]
    lines.append(f"  Bid depth: {depth.get('bid_depth', 0):,}  |  Ask depth: {depth.get('ask_depth', 0):,}\n")
    lines.append("  BIDS:")
    for b in bids:
        lines.append(f"    ${b['price']:.2f}  x  {b['size']:,.0f}")
    lines.append("  ASKS:")
    for a in asks:
        lines.append(f"    ${a['price']:.2f}  x  {a['size']:,.0f}")
    return "\n".join(lines)


@mcp.tool()
def get_price_history(token_id: str, interval: str = "1w", fidelity: int = 60) -> str:
    """Get historical probability data for a Polymarket outcome token.

    Args:
        token_id: Outcome token ID from get_market_detail
        interval: Time window — 1h, 6h, 1d, 1w, 1m, or all
        fidelity: Granularity in minutes — 1, 5, 15, 60, 360, 1440

    Returns time series of probability values.
    """
    from backend.providers.polymarket_market_data import PolymarketMarketDataProvider
    provider = PolymarketMarketDataProvider()
    points = provider.get_price_history(token_id, fidelity=fidelity, interval=interval)
    if not points:
        return "No price history data."

    prices = [p["p"] for p in points]
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
    lines.append(f"        +{'─' * len(sampled)}")

    return "\n".join(lines)


@mcp.tool()
def get_recent_trades(condition_id: str, limit: int = 20) -> str:
    """Get recent trades for a Polymarket market.

    Returns trade history with price, size, side, and timestamp.
    """
    from backend.providers.polymarket_market_data import PolymarketMarketDataProvider
    provider = PolymarketMarketDataProvider()
    trades = provider.get_market_trades(condition_id, limit=limit)
    if not trades:
        return "No recent trades."

    lines = [f"Recent {len(trades)} trades:\n"]
    for t in trades[:limit]:
        lines.append(
            f"  {t.get('side', '?'):>4}  ${t.get('price', 0):.2f}  x  "
            f"{t.get('size', 0):>8,.0f}  {t.get('outcome', '')}  "
            f"{t.get('timestamp', '')[:19]}"
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Platform operations — runs, trades, health
# ---------------------------------------------------------------------------

@mcp.tool()
def list_runs(limit: int = 10) -> str:
    """List recent execution runs from the platform.

    Shows run ID, status, execution mode, asset, and timestamps.
    """
    from backend.db.connect import get_conn
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT run_id, status, execution_mode, created_at, completed_at "
            "FROM runs ORDER BY created_at DESC LIMIT ?",
            (limit,)
        ).fetchall()

    if not rows:
        return "No runs found."

    lines = [f"Recent {len(rows)} runs:\n"]
    for r in rows:
        status = r[1] or "UNKNOWN"
        mode = r[2] or "PAPER"
        created = (r[3] or "")[:19]
        lines.append(f"  {r[0][:12]}...  {status:<12}  {mode:<6}  {created}")
    return "\n".join(lines)


@mcp.tool()
def get_run_detail(run_id: str) -> str:
    """Get detailed information about a specific execution run.

    Shows the run metadata, DAG node execution history, and artifacts.
    """
    from backend.db.connect import get_conn, row_get
    with get_conn() as conn:
        run = conn.execute(
            "SELECT * FROM runs WHERE run_id = ?", (run_id,)
        ).fetchone()
        if not run:
            return f"Run not found: {run_id}"

        nodes = conn.execute(
            "SELECT name, status, started_at, completed_at "
            "FROM dag_nodes WHERE run_id = ? ORDER BY started_at",
            (run_id,)
        ).fetchall()

    lines = [
        f"Run: {run_id}",
        f"  Status: {row_get(run, 'status', 'UNKNOWN')}",
        f"  Mode:   {row_get(run, 'execution_mode', 'PAPER')}",
        f"  Created: {row_get(run, 'created_at', '')[:19]}",
        "",
    ]

    if nodes:
        lines.append("DAG Nodes:")
        for n in nodes:
            name = n[0] or "?"
            status = n[1] or "?"
            started = (n[2] or "")[:19]
            lines.append(f"  {name:<25} {status:<12} {started}")

    return "\n".join(lines)


@mcp.tool()
def execute_trade(command: str, mode: str = "PAPER") -> str:
    """Execute a natural language trade command through the platform.

    The command goes through intent parsing, DAG execution (research, signals,
    risk, strategy, policy check), and paper/live execution.

    Args:
        command: Natural language trade instruction, e.g. "buy $10 of BTC",
                 "buy yes on Trump winning for $5"
        mode: PAPER (simulated, default) or LIVE (real money, requires keys)

    Returns the run ID and status. Use get_run_detail to check progress.
    """
    import httpx
    base = os.environ.get("EXECUTIONDESK_API_URL", "http://localhost:8000")
    try:
        resp = httpx.post(
            f"{base}/api/v1/chat/command",
            json={"text": command, "mode": mode},
            headers={"X-Dev-Tenant": "t_default", "Content-Type": "application/json"},
            timeout=30.0,
        )
        resp.raise_for_status()
        data = resp.json()
        run_id = data.get("run_id", "unknown")
        return f"Trade submitted. Run ID: {run_id}\nUse get_run_detail('{run_id}') to check status."
    except httpx.ConnectError:
        return (
            "Cannot connect to ExecutionDesk backend at "
            f"{base}. Start it with: uvicorn backend.api.main:app --port 8000"
        )
    except Exception as e:
        return f"Trade execution failed: {e}"


@mcp.tool()
def get_positions() -> str:
    """Get current portfolio positions and P&L from the platform database."""
    from backend.db.connect import get_conn
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT symbol, side, qty, fill_price, notional_usd, status, created_at "
            "FROM orders WHERE status IN ('FILLED', 'SUBMITTED') "
            "ORDER BY created_at DESC LIMIT 20"
        ).fetchall()

    if not rows:
        return "No positions found."

    lines = ["Current positions:\n"]
    for r in rows:
        symbol = r[0] or "?"
        side = r[1] or "?"
        qty = r[2] or 0
        price = r[3] or 0
        notional = r[4] or 0
        status = r[5] or "?"
        lines.append(
            f"  {symbol:<12} {side:<5} qty={qty:<10.4f} "
            f"@${price:<8.2f} ${notional:<10.2f} [{status}]"
        )
    return "\n".join(lines)


@mcp.tool()
def system_health() -> str:
    """Check ExecutionDesk platform health — database, migrations, config."""
    import httpx
    base = os.environ.get("EXECUTIONDESK_API_URL", "http://localhost:8000")
    try:
        resp = httpx.get(f"{base}/api/v1/ops/health", timeout=5.0)
        resp.raise_for_status()
        data = resp.json()
        return json.dumps(data, indent=2, default=str)
    except httpx.ConnectError:
        return f"Backend not reachable at {base}. Start with: uvicorn backend.api.main:app --port 8000"
    except Exception as e:
        return f"Health check failed: {e}"


@mcp.tool()
def get_eval_results(run_id: str) -> str:
    """Get evaluation results for a specific run.

    Shows scores across 16 eval dimensions: hallucination detection,
    agent quality, grounding, budget compliance, execution quality, etc.
    """
    from backend.db.connect import get_conn
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT eval_name, score, grade, details "
            "FROM eval_results WHERE run_id = ? ORDER BY eval_name",
            (run_id,)
        ).fetchall()

    if not rows:
        return f"No eval results for run {run_id}."

    lines = [f"Eval results for {run_id}:\n"]
    total_score = 0
    count = 0
    for r in rows:
        name = r[0] or "?"
        score = r[1] if r[1] is not None else 0
        grade = r[2] or "?"
        total_score += score
        count += 1
        lines.append(f"  {name:<30} {score:.3f}  [{grade}]")

    if count > 0:
        avg = total_score / count
        lines.append(f"\n  Average: {avg:.3f}")
    return "\n".join(lines)


@mcp.tool()
def list_clients() -> str:
    """List partner clients with health scores and status.

    Shows client tenant ID, health classification, recent activity,
    and open issues.
    """
    from backend.db.connect import get_conn
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT tenant_id, COUNT(*) as run_count, "
            "SUM(CASE WHEN status = 'COMPLETED' THEN 1 ELSE 0 END) as success, "
            "MAX(created_at) as last_active "
            "FROM runs GROUP BY tenant_id ORDER BY run_count DESC LIMIT 20"
        ).fetchall()

    if not rows:
        return "No client data found."

    lines = ["Clients:\n"]
    for r in rows:
        tenant = r[0] or "?"
        total = r[1] or 0
        success = r[2] or 0
        rate = (success / total * 100) if total > 0 else 0
        last = (r[3] or "")[:10]
        lines.append(f"  {tenant:<20} {total:>4} runs  {rate:>5.1f}% success  last: {last}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run(transport="stdio")
