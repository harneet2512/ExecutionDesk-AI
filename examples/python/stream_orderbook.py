"""Stream real-time order book updates from Polymarket via WebSocket.

Demonstrates:
- WebSocket connection to Polymarket CLOB
- Subscribing to book updates for a specific token
- Parsing bid/ask depth and spread in real-time
- No authentication required for read-only streams

Usage:
    python stream_orderbook.py <token_id>
    python stream_orderbook.py 71321044596237739740653037547242568798704992805913088308608761455600
"""
import sys
import json
import asyncio
import websockets

WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"


async def stream_order_book(token_id: str):
    """Connect to Polymarket WebSocket and stream order book updates."""
    print(f"Connecting to Polymarket WebSocket for token {token_id[:16]}...\n")

    async with websockets.connect(WS_URL) as ws:
        subscribe_msg = {
            "type": "subscribe",
            "channel": "book",
            "assets_ids": [token_id],
        }
        await ws.send(json.dumps(subscribe_msg))
        print("Subscribed to book channel. Waiting for updates...\n")

        async for raw in ws:
            msg = json.loads(raw)

            if msg.get("type") == "book":
                bids = msg.get("bids", [])
                asks = msg.get("asks", [])

                best_bid = float(bids[0]["price"]) if bids else 0
                best_ask = float(asks[0]["price"]) if asks else 0
                spread = round(best_ask - best_bid, 4) if best_bid and best_ask else 0

                bid_depth = sum(float(b.get("size", 0)) for b in bids[:5])
                ask_depth = sum(float(a.get("size", 0)) for a in asks[:5])

                print(f"  Bid: {best_bid:.2f}  |  Ask: {best_ask:.2f}  |  "
                      f"Spread: {spread:.4f}  |  "
                      f"Depth: {bid_depth:,.0f} / {ask_depth:,.0f}")

            elif msg.get("type") == "error":
                print(f"  Error: {msg.get('message', 'unknown')}")
                break


def main():
    if len(sys.argv) < 2:
        print("Usage: python stream_orderbook.py <token_id>")
        print("\nGet a token_id from: python search_markets.py <query>")
        sys.exit(1)

    token_id = sys.argv[1]
    try:
        asyncio.run(stream_order_book(token_id))
    except KeyboardInterrupt:
        print("\nDisconnected.")


if __name__ == "__main__":
    main()
