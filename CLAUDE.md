# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Build & Run Commands

```bash
# One-time setup (creates venv, installs deps, initializes DB, installs frontend)
make bootstrap          # Linux/macOS
scripts/bootstrap.ps1   # Windows

# Start backend (port 8000) + frontend (port 3000)
make dev                # Linux/macOS
scripts/dev.ps1         # Windows

# Run all tests
make test               # Linux/macOS
scripts/test.ps1        # Windows
pytest tests/ -v --tb=short

# Run a single test
pytest tests/test_some_file.py -v --tb=short
pytest tests/test_some_file.py::test_function_name -v

# Backend only
uvicorn backend.api.main:app --reload --port 8000

# Frontend only (from frontend/)
npm run dev

# Lint
ruff check backend/                # Python (non-blocking in CI)
cd frontend && npm run lint        # TypeScript/Next.js

# Compile check
python -m compileall backend
```

## Architecture

**Stack:** FastAPI (Python) backend + Next.js 15 (React 18, TypeScript, Tailwind) frontend + SQLite

**Backend layout (`backend/`):**
- `api/main.py` - FastAPI app entry point; migrations auto-run on startup
- `api/routes/` - REST endpoints (chat, runs, orders, approvals, confirmations, evals, portfolio, market, ops, analytics)
- `api/middleware/` - Request ID (contextvars), rate limiting, audit logging, request size, SSE tracking
- `agents/` - Intent parsing (rule-based + optional LLM), command routing, planning
- `orchestrator/runner.py` - DAG-based run execution engine (create_run, execute_run)
- `orchestrator/nodes/` - DAG nodes: research > signals > news > risk > strategy > proposal > policy_check > approval > execution > post_trade > eval
- `orchestrator/state_machine.py` - Run status (CREATED > RUNNING > COMPLETED/FAILED) and confirmation status enums
- `db/connect.py` - SQLite connection management (`get_conn` context manager, `row_get` helper, `init_db`)
- `db/migrations/` - 29 sequential SQL migrations (auto-applied on startup)
- `db/repo/` - Repository pattern data access layer
- `services/` - Market data, policy engine, news ingestion, notifications, pre-confirmation insights
- `providers/` - Paper trading (simulated), Coinbase CDP (live), Polygon (stocks), news (RSS/GDELT)
- `mcp_servers/` - MCP servers for market data and broker operations
- `evals/` - Evaluation modules (execution quality, grounding, tool reliability, etc.)
- `core/config.py` - Pydantic BaseSettings loaded from `.env`

**Frontend layout (`frontend/`):**
- `app/` - Next.js App Router pages (chat, runs, runs/[id], evals, performance, ops)
- `components/` - 25+ React components (trading cards, charts, chat UI)
- `lib/api.ts` - REST client with `fetchWithRetry` (exponential backoff for 429/503)
- `next.config.js` - Proxies `/api/v1/*` to backend on port 8000

**Key data flow:** User chat command > intent parsing > create_run > DAG node execution > policy check > optional human approval > order execution > post-trade analysis > SSE events to frontend

## Critical Patterns and Pitfalls

**Database:**
- Always use `get_conn()` context manager (NOT `get_db_connection` which doesn't exist)
- `sqlite3.Row` has NO `.get()` method - use `row_get(row, key, default)` from `db/connect.py`
- `dag_nodes` PK is `node_id` (not `id`), column is `name` (not `node_name`), requires `node_type`
- Check `backend/db/migrations/` for actual column names before writing queries

**Logging:**
- NEVER use `extra={"request_id": ...}` in logger calls - RequestIDMiddleware sets request_id via contextvars automatically. Using `extra` causes "Attempt to overwrite" crash.

**JSON:**
- `json.loads()` crashes on None/malformed - always use `_safe_json_loads(s, default=None)` from `backend/core/utils.py`
- Use `json_dumps()` from utils.py for serializing Enum, Decimal, set, bytes, Pydantic objects

**Frontend:**
- `dark:bg-slate-750` is NOT a valid Tailwind class - use `dark:bg-slate-800/50`
- Guard `.toFixed()`: use `typeof v === 'number' && isFinite(v) ? v.toFixed(n) : '\u2014'`
- `RunDetail` type in api.ts doesn't have `fills` - cast with `(runDetail as any).fills`
- Inline arrows in JSX `onX={(args) => handler(args, extra)}` create new refs every render, causing infinite loops with useEffect deps

**Middleware:**
- BaseHTTPMiddleware wraps HTTPException in ExceptionGroup - catch HTTPException in middleware `call_next()` try-except to prevent 500s

**Function signatures (do not pass extra args):**
- `create_run(tenant_id, execution_mode, source_run_id)` - no run_id, user_id, metadata
- `execute_run(run_id)` - no parsed_intent, execution_mode

**Error responses follow this shape:**
```json
{"error": {"code": "...", "error_code": "...", "message": "...", "request_id": "...", "remediation": "..."}}
```

## Testing

- Config: `pytest.ini` sets `testpaths = tests` and `TEST_AUTH_BYPASS=true`
- Tests use isolated SQLite databases via `test_db` fixture in `tests/conftest.py`
- Auth in tests: use `X-Dev-Tenant` header with FastAPI TestClient
- When mocking lazily-imported functions, patch at source module (e.g., `backend.db.connect.get_schema_status`)
- CI runs: pytest with coverage, ruff lint, secret redaction security checks

## Environment

- Copy `.env` with required keys: `OPENAI_API_KEY`, `COINBASE_API_KEY_NAME`, `COINBASE_API_PRIVATE_KEY`, `DATABASE_URL`
- `EXECUTION_MODE_DEFAULT=PAPER` for safe development (paper trading)
- `DEMO_SAFE_MODE=1` blocks all LIVE orders
- Frontend reads `NEXT_PUBLIC_API_URL` from `frontend/.env.local` (default: `http://localhost:8000`)
- Portfolio analysis is synchronous; trade execution is async (background thread)
