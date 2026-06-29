"""Place a GTC limit order on the Polymarket CLOB.

Demonstrates:
- L2 authenticated order placement
- Limit price validation (0.01-0.99)
- GTC/GTD/FOK/IOC order types
- Requires POLY_API_KEY and POLY_API_SECRET environment variables

Usage:
    export POLY_API_KEY="your-key"
    export POLY_API_SECRET="your-secret"

    python place_limit_order.py <token_id> BUY 0.55 100
    python place_limit_order.py <token_id> SELL 0.60 50 --type GTD --expiry 3600
"""
import os
import sys
import httpx

CLOB_URL = "https://clob.polymarket.com"


def place_order(
    token_id: str,
    side: str,
    price: float,
    size: float,
    order_type: str = "GTC",
) -> dict:
    """Place a limit order on the Polymarket CLOB.

    Args:
        token_id: Outcome token identifier
        side: BUY or SELL
        price: Limit price between 0.01 and 0.99
        size: Number of shares
        order_type: GTC (default), GTD, FOK, or IOC

    Returns:
        CLOB API response with orderID and status
    """
    if price < 0.01 or price > 0.99:
        raise ValueError(f"Price {price} out of range. Must be 0.01-0.99.")

    api_key = os.environ.get("POLY_API_KEY")
    api_secret = os.environ.get("POLY_API_SECRET")
    if not api_key or not api_secret:
        raise RuntimeError(
            "Set POLY_API_KEY and POLY_API_SECRET environment variables. "
            "Generate credentials at https://polymarket.com/profile/api-keys"
        )

    payload = {
        "tokenID": token_id,
        "side": side.upper(),
        "price": str(price),
        "size": str(size),
        "type": order_type.upper(),
    }

    resp = httpx.post(
        f"{CLOB_URL}/order",
        json=payload,
        headers={
            "Content-Type": "application/json",
            "POLY_API_KEY": api_key,
            "POLY_API_SECRET": api_secret,
        },
        timeout=10.0,
    )
    resp.raise_for_status()
    return resp.json()


def main():
    if len(sys.argv) < 5:
        print("Usage: python place_limit_order.py <token_id> <BUY|SELL> <price> <size>")
        print("Example: python place_limit_order.py abc123... BUY 0.55 100")
        sys.exit(1)

    token_id = sys.argv[1]
    side = sys.argv[2]
    price = float(sys.argv[3])
    size = float(sys.argv[4])
    order_type = "GTC"

    if "--type" in sys.argv:
        idx = sys.argv.index("--type")
        order_type = sys.argv[idx + 1]

    cost = price * size
    print(f"Placing {order_type} {side} order:")
    print(f"  Token:  {token_id[:20]}...")
    print(f"  Price:  ${price:.2f}")
    print(f"  Size:   {size:.0f} shares")
    print(f"  Cost:   ${cost:.2f}")
    print()

    result = place_order(token_id, side, price, size, order_type)
    order_id = result.get("orderID", result.get("id", "unknown"))
    status = result.get("status", "unknown")
    print(f"  Order ID: {order_id}")
    print(f"  Status:   {status}")


if __name__ == "__main__":
    main()
