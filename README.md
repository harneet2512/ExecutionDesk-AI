# ExecutionDesk AI

<p align="center">
  <img src="./docs/media/executiondesk-demo.gif" alt="ExecutionDesk AI demo" width="100%" />
</p>

<p align="center">
  <strong>Execution infrastructure for prediction markets, crypto, and equities</strong><br />
  Polymarket CLOB integration, partner client operations, and developer tooling in one platform.
</p>

---

## What This Is

ExecutionDesk is an internal operations platform for a prediction market exchange. It handles what a Forward Deployed Product Engineer builds day-to-day: partner onboarding, trade execution infrastructure, client health monitoring, operational runbooks, and developer-facing APIs.

Built on top of the Polymarket CLOB and Gamma APIs — the same stack a Polymarket FDPE would work with daily.

### Platform Overview

| Home Dashboard | Markets Browser | Chat Execution |
|:-:|:-:|:-:|
| ![Home](frontend/screenshot-vercel-home.png) | ![Markets](frontend/screenshot-vercel-markets.png) | ![Chat](frontend/screenshot-vercel-chat.png) |

| Client Operations | API Documentation | Evaluations |
|:-:|:-:|:-:|
| ![Clients](frontend/screenshot-vercel-clients.png) | ![Docs](frontend/screenshot-vercel-docs.png) | ![Evals](frontend/screenshot-vercel-evals.png) |

| Runs (DAG Execution) | Performance Telemetry | Operations |
|:-:|:-:|:-:|
| ![Runs](frontend/screenshot-vercel-runs.png) | ![Performance](frontend/screenshot-vercel-perf.png) | ![Ops](frontend/screenshot-vercel-ops.png) |

---

## MCP Server — Use From Claude Code / Codex

ExecutionDesk exposes the entire platform as an MCP (Model Context Protocol) server. Connect it to Claude Code, Codex, or any MCP-compatible client and interact with Polymarket, run trades, check positions, and monitor client health — without opening the web UI.

**12 tools available:** `search_markets`, `get_market_detail`, `get_order_book`, `get_price_history`, `get_recent_trades`, `list_runs`, `get_run_detail`, `execute_trade`, `get_positions`, `system_health`, `get_eval_results`, `list_clients`

### Setup (Claude Code)

Add to your `~/.claude.json` or project `.claude/settings.json`:

```json
{
  "mcpServers": {
    "executiondesk": {
      "command": "python",
      "args": ["/path/to/ExecutionDesk-AI/mcp_server.py"],
      "env": {
        "DATABASE_URL": "postgresql://edai:edai@localhost:5432/executiondesk"
      }
    }
  }
}
```

Then in Claude Code:
```
> Search Polymarket for "bitcoin" markets
> What's the order book for the Trump election market?
> Show me recent execution runs
> Execute a paper trade: buy $10 of ETH
```

---

## Polymarket Integration

Direct integration with Polymarket's CLOB and Gamma APIs — limit orders, order book streaming, position tracking, market discovery.

```python
# examples/python/place_limit_order.py — standalone, no app dependency
import httpx

resp = httpx.post("https://clob.polymarket.com/order", json={
    "tokenID": token_id,
    "side": "BUY",
    "price": "0.55",      # probability: 55%
    "size": "100",         # 100 shares
    "type": "GTC",         # Good-Til-Cancelled
}, headers={"POLY_API_KEY": api_key, "POLY_API_SECRET": api_secret})
```

**What's implemented:**
- `backend/providers/polymarket_clob.py` — BrokerProvider for CLOB order placement, positions, balances, fills, order book
- `backend/providers/polymarket_market_data.py` — Market search (Gamma API), price history, order book depth, trade feed
- `backend/orchestrator/nodes/prediction_*.py` — DAG nodes for prediction market research, signals, and risk
- `backend/agents/intent_parser.py` — NL parsing: "buy yes on Trump winning 2028 for $5" -> structured trade intent
- `frontend/components/ProbabilityChart.tsx` — Polymarket-style area chart with gradient fills
- `frontend/components/OrderBook.tsx` — Real-time bid/ask display with depth bars
- `frontend/app/markets/page.tsx` — Market browser with search, filters, probability charting

**Standalone integration examples** in [`examples/`](./examples/):

| Script | What It Does |
|--------|-------------|
| `python/search_markets.py` | Search prediction markets via Gamma API |
| `python/stream_orderbook.py` | WebSocket order book streaming |
| `python/place_limit_order.py` | Authenticated GTC limit order on CLOB |
| `python/monitor_positions.py` | Fetch positions + compute unrealized P&L |
| `python/price_history.py` | Historical probability data + ASCII chart |
| `typescript/websocket_client.ts` | Browser-ready WS client with auto-reconnect |

---

## Client Operations

The FDPE manages partner relationships. This platform tracks client health, surfaces degradation, and provides operational playbooks.

- **Health scoring** (0-100) with classification: healthy / good / at_risk / churning / inactive
- **Scoring model**: activity 30% + success rate 25% + volume trend 20% + error frequency 15% + feature adoption 10%
- **Alert triggers**: 7-day inactivity, error spike, 50%+ volume drop, repeated policy blocks
- **Issue tracking** with threaded comments, priority, and linked run IDs
- **Runbooks**: 8 pre-populated operational guides (insufficient balance, order timeout, rate limiting, etc.)

| ![Clients](frontend/screenshot-vercel-clients.png) | ![Positions](frontend/screenshot-vercel-positions.png) |
|:-:|:-:|
| Client dashboard with health gauges | Position tracking |

---

## Developer Platform

Partner-facing APIs with auth, webhooks, and interactive docs — the kind of tooling an FDPE ships to help partners self-serve.

- **API keys**: SHA256 hash storage, permission scoping (read/trade/admin), rotation with 24h grace period
- **Webhooks**: HMAC-signed payloads, async delivery with retry, dead letter queue after 3 failures
- **WebSocket streaming**: Real-time prices, order book, trades per symbol
- **Interactive docs**: Endpoint reference with Python/JS/cURL snippets, auth quickstart, error reference

Events: `trade.filled`, `trade.failed`, `run.completed`, `approval.needed`, `policy.blocked`, `alert.triggered`

---

## Architecture

```
FastAPI (Python)          Next.js 15 (React 18, TypeScript, Tailwind)
├── api/routes/           ├── app/ (17 pages)
│   ├── chat.py           │   ├── chat/         (NL command interface)
│   ├── markets.py        │   ├── markets/       (prediction market browser)
│   ├── clients.py        │   ├── clients/       (partner health dashboard)
│   ├── runs.py           │   ├── runs/          (DAG execution history)
│   ├── api_keys.py       │   ├── docs/          (interactive API docs)
│   ├── webhooks.py       │   ├── evals/         (evaluation results)
│   ├── analytics.py      │   ├── ops/           (system health + runbooks)
│   └── ws_market_data.py │   └── performance/   (telemetry)
├── providers/            ├── components/ (41 components)
│   ├── polymarket_clob   │   ├── ProbabilityChart
│   ├── polymarket_market │   ├── OrderBook
│   ├── coinbase_cdp      │   ├── ClientHealthGauge
│   ├── polygon           │   ├── PredictionMarketCard
│   └── paper_trading     │   └── ...
├── orchestrator/         └── lib/
│   ├── runner.py (DAG)       ├── api.ts (REST client)
│   └── nodes/ (16 nodes)     └── useWebSocket.ts
├── services/
│   ├── client_health.py
│   ├── webhook_dispatcher.py
│   └── api_key_auth.py
├── db/ (PostgreSQL 16, 36 migrations)
└── evals/ (16 evaluation modules)
```

**DAG execution pipeline:**
```
research > signals > news > risk > strategy > proposal > policy_check > approval > execution > post_trade > eval
```

Prediction markets use specialized nodes: `prediction_research > prediction_signals > prediction_risk > ...`

---

## Quick Start

```bash
# Option 1: Docker (recommended — includes PostgreSQL)
docker compose up --build
# Frontend: http://localhost:3000  |  Backend: http://localhost:8000  |  PostgreSQL: localhost:5432

# Option 2: Manual (requires PostgreSQL running locally)
createdb executiondesk  # or use docker: docker run -d -p 5432:5432 -e POSTGRES_USER=edai -e POSTGRES_PASSWORD=edai -e POSTGRES_DB=executiondesk postgres:16-alpine
pip install -r requirements.txt
uvicorn backend.api.main:app --reload --port 8000

cd frontend && npm install && npm run dev
```

Database migrations auto-apply on startup. Copy `.env.example` to `.env` for configuration. PostgreSQL 16 is the default database backend.

## Testing

```bash
# Backend (185+ tests)
pytest tests/ -v --tb=short

# Frontend
cd frontend && npm run lint && npx next build

# Single test
pytest tests/test_polymarket_provider.py -v
```

## Stats

| Metric | Count |
|--------|-------|
| API routes | 33 |
| Frontend pages | 17 |
| React components | 41 |
| DAG nodes | 16 |
| Database migrations | 36 |
| Evaluation modules | 16 |
| Automated tests | 185+ |
| Providers | 5 (Polymarket CLOB, Polymarket Market Data, Coinbase CDP, Polygon, Paper) |

## Configuration

Copy `.env.example` and set:

```bash
# Required
OPENAI_API_KEY=...
DATABASE_URL=postgresql://edai:edai@localhost:5432/executiondesk

# Polymarket (for CLOB trading)
POLYMARKET_API_KEY=...
POLYMARKET_API_SECRET=...

# Coinbase (for crypto)
COINBASE_API_KEY_NAME=...
COINBASE_API_PRIVATE_KEY_PATH=./secrets/coinbase_private_key.pem

# Safety
EXECUTION_MODE_DEFAULT=PAPER
DEMO_SAFE_MODE=1
LIVE_MAX_NOTIONAL_USD=20.0
```

## Observability

- **Prometheus metrics** at `/api/v1/metrics` (success/failure rates, node latency, rate limit hits)
- **OpenTelemetry tracing** via OTLP exporter (per-node spans with run context)
- **Structured JSON logging** with automatic secret redaction
- **16 evaluation modules**: hallucination detection, agent quality, grounding, budget compliance, execution quality

## License

MIT
