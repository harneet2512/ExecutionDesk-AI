# Integration Examples

Standalone scripts demonstrating common Polymarket CLOB integration patterns.
Each script is self-contained — no dependency on the main ExecutionDesk backend.

## Python

| Script | Description |
|--------|-------------|
| `python/search_markets.py` | Search and browse prediction markets via the Gamma API |
| `python/stream_orderbook.py` | Stream real-time order book updates over WebSocket |
| `python/place_limit_order.py` | Place a GTC limit order on the CLOB |
| `python/monitor_positions.py` | Fetch open positions and compute unrealized P&L |
| `python/price_history.py` | Fetch and chart historical probability data |

## TypeScript

| Script | Description |
|--------|-------------|
| `typescript/websocket_client.ts` | Browser-ready WebSocket client for market data |

## Setup

```bash
pip install httpx websockets
```

For order placement, set your API credentials:
```bash
export POLY_API_KEY="your-api-key"
export POLY_API_SECRET="your-api-secret"
```

Read-only endpoints (search, order book, price history) require no authentication.
