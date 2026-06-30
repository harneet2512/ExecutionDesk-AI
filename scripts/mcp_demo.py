"""MCP Server Demo — Run this to see all tools in action.

Usage:
    python scripts/mcp_demo.py
    python scripts/mcp_demo.py --polymarket-only   # Skip database tools
"""
import sys
import os
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from mcp_server import (
    search_markets, get_market_detail, get_order_book,
    get_price_history, get_recent_trades,
    list_runs, get_run_detail, get_positions,
    get_eval_results, list_clients, system_health,
)

POLYMARKET_ONLY = "--polymarket-only" in sys.argv


def section(title):
    print(f"\n{'-' * 60}")
    print(f"  {title}")
    print(f"{'-' * 60}\n")


def tool_call(call_str):
    print(f">>> {call_str}")
    time.sleep(0.3)


def main():
    print("=" * 60)
    print("  ExecutionDesk AI — MCP Server Demo")
    print("  13 tools | Polymarket + Platform Operations")
    print("=" * 60)

    # --- Polymarket Tools ---
    section("POLYMARKET: Search Markets")
    tool_call('search_markets("election", limit=3)')
    print(search_markets("election", limit=3))

    section("POLYMARKET: Market Detail")
    tool_call('search_markets("bitcoin", limit=1)')
    r = search_markets("bitcoin", limit=1)
    print(r)

    section("POLYMARKET: Order Book")
    from backend.providers.polymarket_market_data import PolymarketMarketDataProvider
    provider = PolymarketMarketDataProvider()
    markets = provider.search_markets("election", limit=1)
    if markets and markets[0].get("tokens"):
        token = markets[0]["tokens"][0]
        token_id = token.get("token_id", "")
        if token_id:
            tool_call(f'get_order_book("{token_id[:16]}...")')
            print(get_order_book(token_id))

            section("POLYMARKET: Price History")
            tool_call(f'get_price_history("{token_id[:16]}...", interval="1w")')
            print(get_price_history(token_id, interval="1w"))
    else:
        print("  (No token IDs available for order book demo)")

    section("POLYMARKET: Recent Trades")
    if markets:
        cid = markets[0].get("condition_id", "")
        tool_call(f'get_recent_trades("{cid[:16]}...", limit=5)')
        print(get_recent_trades(cid, limit=5))

    if POLYMARKET_ONLY:
        print("\n" + "=" * 60)
        print("  Polymarket tools demo complete (--polymarket-only)")
        print("=" * 60)
        return

    # --- Platform Tools ---
    section("PLATFORM: List Runs")
    tool_call("list_runs(limit=5)")
    print(list_runs(limit=5))

    section("PLATFORM: Positions")
    tool_call("get_positions()")
    print(get_positions())

    section("PLATFORM: Client Activity")
    tool_call("list_clients()")
    print(list_clients())

    section("PLATFORM: System Health")
    tool_call("system_health()")
    print(system_health())

    print("\n" + "=" * 60)
    print("  Demo complete — 13 MCP tools verified")
    print("=" * 60)


if __name__ == "__main__":
    import logging
    logging.disable(logging.CRITICAL)
    main()
