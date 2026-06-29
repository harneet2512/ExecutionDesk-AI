"""Fetch open Polymarket positions and compute unrealized P&L.

Demonstrates:
- Authenticated position retrieval
- Unrealized P&L calculation (current_price - avg_entry) * size
- Portfolio-level aggregation
- Requires POLY_API_KEY and POLY_API_SECRET

Usage:
    export POLY_API_KEY="your-key"
    export POLY_API_SECRET="your-secret"
    python monitor_positions.py
"""
import os
import httpx

CLOB_URL = "https://clob.polymarket.com"


def get_positions() -> list[dict]:
    """Fetch all open positions from the CLOB."""
    api_key = os.environ.get("POLY_API_KEY", "")
    api_secret = os.environ.get("POLY_API_SECRET", "")

    resp = httpx.get(
        f"{CLOB_URL}/positions",
        headers={
            "POLY_API_KEY": api_key,
            "POLY_API_SECRET": api_secret,
        },
        timeout=10.0,
    )
    resp.raise_for_status()
    data = resp.json()
    return data if isinstance(data, list) else data.get("positions", [])


def main():
    positions = get_positions()

    if not positions:
        print("No open positions.")
        return

    total_value = 0.0
    total_pnl = 0.0

    print(f"{'Market':<40} {'Outcome':<6} {'Size':>8} {'Entry':>7} {'Now':>7} {'P&L':>10}")
    print("-" * 85)

    for pos in positions:
        size = float(pos.get("size", 0))
        avg_price = float(pos.get("avgPrice", pos.get("avg_price", 0)))
        current = float(pos.get("currentPrice", pos.get("current_price", 0)))
        pnl = (current - avg_price) * size
        value = current * size

        market = (pos.get("market") or pos.get("conditionId", ""))[:38]
        outcome = pos.get("outcome", "?")

        total_value += value
        total_pnl += pnl

        pnl_str = f"{'+'if pnl >= 0 else ''}{pnl:.2f}"
        print(f"{market:<40} {outcome:<6} {size:>8.1f} {avg_price:>7.3f} {current:>7.3f} {pnl_str:>10}")

    print("-" * 85)
    pnl_str = f"{'+'if total_pnl >= 0 else ''}{total_pnl:.2f}"
    print(f"{'Total':<40} {'':6} {'':>8} {'':>7} {'':>7} {pnl_str:>10}")
    print(f"\nPortfolio value: ${total_value:,.2f}")


if __name__ == "__main__":
    main()
