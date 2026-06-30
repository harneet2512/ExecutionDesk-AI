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
          "args": ["/path/to/ExecutionDesk-AI/mcp_server.py"],
          "env": {"DATABASE_URL": "postgresql://edai:edai@localhost:5432/executiondesk"}
        }
      }
    }

Requires the backend to be importable (run from the project root).
"""
import os
import sys
import json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("ExecutionDesk AI")

_provider = None


def _get_provider():
    global _provider
    if _provider is None:
        from backend.providers.polymarket_market_data import PolymarketMarketDataProvider
        _provider = PolymarketMarketDataProvider()
    return _provider


def _db_query(sql: str, params: tuple = ()) -> list:
    """Execute a read query against the database, handling both SQLite and PostgreSQL."""
    from backend.db.connect import get_conn, _is_postgres
    from backend.core.config import get_settings

    is_pg = _is_postgres(get_settings().database_url)
    if is_pg:
        sql = sql.replace("?", "%s")

    with get_conn() as conn:
        if is_pg:
            cur = conn.cursor()
            cur.execute(sql, params)
            return cur.fetchall()
        else:
            return conn.execute(sql, params).fetchall()


def _row_val(row, key_or_idx, default=None):
    """Extract a value from a row that may be a dict (PostgreSQL) or sqlite3.Row."""
    if isinstance(row, dict):
        return row.get(key_or_idx, default)
    try:
        val = row[key_or_idx]
        return val if val is not None else default
    except (IndexError, KeyError):
        return default


def _str_val(row, key_or_idx, default=""):
    """Extract a string value, coercing to str for safe slicing."""
    v = _row_val(row, key_or_idx, default)
    return str(v) if v is not None else default


# ---------------------------------------------------------------------------
# Polymarket — prediction market tools
# ---------------------------------------------------------------------------

@mcp.tool()
def search_markets(query: str, limit: int = 10) -> str:
    """Search Polymarket prediction markets by keyword.

    Returns active markets with YES/NO probabilities, volume, and liquidity.
    Examples: "election", "bitcoin price", "FIFA", "AI", "Fed rate cut"
    """
    provider = _get_provider()
    markets = provider.search_markets(query, limit=limit)
    if not markets:
        return f"No markets found for '{query}'."

    lines = [f"Found {len(markets)} markets for '{query}':\n"]
    for i, m in enumerate(markets, 1):
        yes_pct = f"{m['yes_price'] * 100:.0f}%"
        vol = f"${m['volume']:,.0f}"
        cid = m.get("condition_id") or ""
        lines.append(f"{i}. {m['question']}")
        lines.append(f"   YES: {yes_pct}  |  Volume: {vol}  |  ID: {cid[:16]}...")
        end = m.get("end_date")
        if end:
            lines.append(f"   Resolves: {str(end)[:10]}")
        lines.append("")
    return "\n".join(lines)


@mcp.tool()
def get_market_detail(condition_id: str) -> str:
    """Get detailed information about a specific Polymarket prediction market.

    Use the condition_id from search_markets results.
    Returns outcomes, token IDs, prices, volume, liquidity, and end date.
    """
    provider = _get_provider()
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
    provider = _get_provider()
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
        interval: Time window -- 1h, 6h, 1d, 1w, 1m, or all
        fidelity: Granularity in minutes -- 1, 5, 15, 60, 360, 1440

    Returns time series of probability values with ASCII chart.
    """
    provider = _get_provider()
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
    provider = _get_provider()
    trades = provider.get_market_trades(condition_id, limit=limit)
    if not trades:
        return "No recent trades."

    lines = [f"Recent {len(trades)} trades:\n"]
    for t in trades[:limit]:
        ts = t.get("timestamp") or ""
        lines.append(
            f"  {t.get('side', '?'):>4}  ${t.get('price', 0):.2f}  x  "
            f"{t.get('size', 0):>8,.0f}  {t.get('outcome', '')}  "
            f"{str(ts)[:19]}"
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Platform operations — runs, trades, health
# ---------------------------------------------------------------------------

@mcp.tool()
def list_runs(limit: int = 10) -> str:
    """List recent execution runs from the platform.

    Shows run ID, status, execution mode, and timestamps.
    """
    rows = _db_query(
        "SELECT run_id, status, execution_mode, created_at "
        "FROM runs ORDER BY created_at DESC LIMIT ?",
        (limit,)
    )

    if not rows:
        return "No runs found."

    lines = [f"Recent {len(rows)} runs:\n"]
    for r in rows:
        rid = _str_val(r, "run_id", _str_val(r, 0, "?"))
        status = _str_val(r, "status", _str_val(r, 1, "UNKNOWN"))
        mode = _str_val(r, "execution_mode", _str_val(r, 2, "PAPER"))
        created = _str_val(r, "created_at", _str_val(r, 3, ""))[:19]
        lines.append(f"  {rid[:12]}...  {status:<12}  {mode:<6}  {created}")
    return "\n".join(lines)


@mcp.tool()
def get_run_detail(run_id: str) -> str:
    """Get detailed information about a specific execution run.

    Shows the run metadata and DAG node execution history.
    """
    runs = _db_query(
        "SELECT run_id, status, execution_mode, created_at "
        "FROM runs WHERE run_id = ?",
        (run_id,)
    )
    if not runs:
        return f"Run not found: {run_id}"

    run = runs[0]
    nodes = _db_query(
        "SELECT name, status, started_at, completed_at "
        "FROM dag_nodes WHERE run_id = ? ORDER BY started_at",
        (run_id,)
    )

    lines = [
        f"Run: {run_id}",
        f"  Status: {_str_val(run, 'status', _str_val(run, 1, 'UNKNOWN'))}",
        f"  Mode:   {_str_val(run, 'execution_mode', _str_val(run, 2, 'PAPER'))}",
        f"  Created: {_str_val(run, 'created_at', _str_val(run, 3, ''))[:19]}",
        "",
    ]

    if nodes:
        lines.append("DAG Nodes:")
        for n in nodes:
            name = _str_val(n, "name", _str_val(n, 0, "?"))
            status = _str_val(n, "status", _str_val(n, 1, "?"))
            started = _str_val(n, "started_at", _str_val(n, 2, ""))[:19]
            lines.append(f"  {name:<25} {status:<12} {started}")

    return "\n".join(lines)


@mcp.tool()
def execute_trade(command: str) -> str:
    """Send a natural language trade command to the platform.

    The command goes through intent parsing and may trigger a confirmation
    flow (the platform requires human approval before executing trades).

    Args:
        command: Natural language instruction, e.g. "buy $10 of BTC",
                 "buy yes on Trump winning for $5", "what is the price of ETH"

    Returns the platform response. For trade commands, you'll get a
    confirmation prompt — use the confirmation_id with confirm_trade to proceed.
    """
    import httpx
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
        status = data.get("status", "")
        message = data.get("message", "")
        intent = data.get("intent", "")

        lines = []
        if message:
            lines.append(message)
        if confirmation_id:
            lines.append(f"\nConfirmation required. ID: {confirmation_id}")
            lines.append(f"Use confirm_trade('{confirmation_id}') to execute.")
        if run_id:
            lines.append(f"\nRun ID: {run_id}")
            lines.append(f"Use get_run_detail('{run_id}') to check progress.")
        if not lines:
            return json.dumps(data, indent=2, default=str)
        return "\n".join(lines)

    except httpx.ConnectError:
        return (
            f"Cannot connect to ExecutionDesk backend at {base}. "
            "Start it with: uvicorn backend.api.main:app --port 8000"
        )
    except Exception as e:
        return f"Trade execution failed: {e}"


@mcp.tool()
def confirm_trade(confirmation_id: str) -> str:
    """Confirm a pending trade that requires human approval.

    Use the confirmation_id from execute_trade's response.
    """
    import httpx
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
        return f"Trade confirmed. Run ID: {run_id}\nUse get_run_detail('{run_id}') to track execution."

    except httpx.ConnectError:
        return f"Cannot connect to backend at {base}."
    except Exception as e:
        return f"Confirmation failed: {e}"


@mcp.tool()
def get_positions() -> str:
    """Get current portfolio positions from the platform database."""
    rows = _db_query(
        "SELECT symbol, side, qty, avg_fill_price, notional_usd, status, created_at "
        "FROM orders WHERE status IN ('FILLED', 'SUBMITTED') "
        "ORDER BY created_at DESC LIMIT 20"
    )

    if not rows:
        return "No positions found."

    lines = ["Current positions:\n"]
    for r in rows:
        symbol = _str_val(r, "symbol", _str_val(r, 0, "?"))
        side = _str_val(r, "side", _str_val(r, 1, "?"))
        qty = float(_row_val(r, "qty", _row_val(r, 2, 0)) or 0)
        price = float(_row_val(r, "avg_fill_price", _row_val(r, 3, 0)) or 0)
        notional = float(_row_val(r, "notional_usd", _row_val(r, 4, 0)) or 0)
        status = _str_val(r, "status", _str_val(r, 5, "?"))
        lines.append(
            f"  {symbol:<12} {side:<5} qty={qty:<10.4f} "
            f"@${price:<8.2f} ${notional:<10.2f} [{status}]"
        )
    return "\n".join(lines)


@mcp.tool()
def system_health() -> str:
    """Check ExecutionDesk platform health -- database, migrations, config."""
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
    rows = _db_query(
        "SELECT eval_name, score, eval_category, details_json "
        "FROM eval_results WHERE run_id = ? ORDER BY eval_name",
        (run_id,)
    )

    if not rows:
        return f"No eval results for run {run_id}."

    lines = [f"Eval results for {run_id}:\n"]
    total_score = 0.0
    count = 0
    for r in rows:
        name = _str_val(r, "eval_name", _str_val(r, 0, "?"))
        score_val = _row_val(r, "score", _row_val(r, 1, 0))
        score = float(score_val) if score_val is not None else 0.0
        category = _str_val(r, "eval_category", _str_val(r, 2, "?"))
        total_score += score
        count += 1
        lines.append(f"  {name:<30} {score:.3f}  [{category}]")

    if count > 0:
        avg = total_score / count
        lines.append(f"\n  Average: {avg:.3f}")
    return "\n".join(lines)


@mcp.tool()
def list_clients() -> str:
    """List partner clients with activity summary.

    Shows client tenant ID, run count, success rate, and last activity.
    """
    rows = _db_query(
        "SELECT tenant_id, COUNT(*) as run_count, "
        "SUM(CASE WHEN status = 'COMPLETED' THEN 1 ELSE 0 END) as success, "
        "MAX(created_at) as last_active "
        "FROM runs GROUP BY tenant_id ORDER BY run_count DESC LIMIT 20"
    )

    if not rows:
        return "No client data found."

    lines = ["Clients:\n"]
    for r in rows:
        tenant = _str_val(r, "tenant_id", _str_val(r, 0, "?"))
        total = int(_row_val(r, "run_count", _row_val(r, 1, 0)) or 0)
        success = int(_row_val(r, "success", _row_val(r, 2, 0)) or 0)
        rate = (success / total * 100) if total > 0 else 0
        last = _str_val(r, "last_active", _str_val(r, 3, ""))[:10]
        lines.append(f"  {tenant:<20} {total:>4} runs  {rate:>5.1f}% success  last: {last}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run(transport="stdio")
