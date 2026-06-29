"""Search and browse Polymarket prediction markets.

Demonstrates:
- Gamma API market discovery
- Parsing outcome prices from JSON-encoded strings
- Sorting by volume/liquidity
- No authentication required

Usage:
    python search_markets.py "FIFA World Cup"
    python search_markets.py "bitcoin" --limit 5
"""
import sys
import json
import httpx

GAMMA_URL = "https://gamma-api.polymarket.com"


def search_markets(query: str, limit: int = 10) -> list[dict]:
    """Search for active prediction markets by keyword."""
    resp = httpx.get(
        f"{GAMMA_URL}/markets",
        params={"search": query, "limit": limit, "active": True},
        timeout=10.0,
    )
    resp.raise_for_status()
    raw = resp.json()
    if not isinstance(raw, list):
        return []

    markets = []
    for m in raw:
        prices = m.get("outcomePrices", "[]")
        if isinstance(prices, str):
            prices = json.loads(prices)
        yes_price = float(prices[0]) if len(prices) > 0 else 0.0

        volume = float(m.get("volume", 0) or 0)
        liquidity = float(m.get("liquidity", 0) or 0)

        markets.append({
            "question": m.get("question", ""),
            "condition_id": m.get("conditionId", ""),
            "yes_price": yes_price,
            "volume": volume,
            "liquidity": liquidity,
            "end_date": m.get("endDate"),
        })

    markets.sort(key=lambda x: x["volume"], reverse=True)
    return markets


def main():
    query = sys.argv[1] if len(sys.argv) > 1 else "election"
    limit = int(sys.argv[3]) if len(sys.argv) > 3 and sys.argv[2] == "--limit" else 10

    print(f"Searching Polymarket for: '{query}'\n")
    markets = search_markets(query, limit)

    if not markets:
        print("No markets found.")
        return

    for i, m in enumerate(markets, 1):
        prob = f"{m['yes_price'] * 100:.0f}%"
        vol = f"${m['volume']:,.0f}"
        print(f"  {i}. {m['question']}")
        print(f"     YES: {prob}  |  Volume: {vol}  |  ID: {m['condition_id'][:12]}...")
        print()


if __name__ == "__main__":
    main()
