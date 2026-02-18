# ExecutiveDesk AI

**Agentic Trading Platform** – Enterprise agentic execution platform.

## Quick Start

### Backend
```bash
# Install dependencies
pip install -r requirements.txt

# Sanity check: Verify no syntax errors (especially useful on Windows)
python -m compileall backend

# Start backend
uvicorn backend.api.main:app --reload --port 8000
```

Backend runs on http://localhost:8000

**Database migrations** are automatically applied on startup via `init_db()`.

**Note for Windows**: If you see "Python-dotenv could not parse statement starting at line X" warnings, check your `.env` file. Ensure all lines follow the format `KEY=VALUE` (no `set`, `$env:`, or `export` prefixes). Comments should be on their own line starting with `#`.

### Frontend
```bash
cd frontend
npm install
npm run dev
```

Frontend runs on http://localhost:3000

### Run Tests
```bash
python -m pytest -v
```

## Database Migrations

**Migrations are automatically applied on backend startup** via `init_db()`. No manual migration commands are needed.

### Check Migration Status

```bash
curl http://localhost:8000/api/v1/ops/health | jq '.migrations'
```

### If You See "Database Setup Required" in the UI

The frontend will display a health gate with actionable instructions if pending migrations are detected.

**To apply migrations:**
1. Stop the backend server (Ctrl+C)
2. Restart it:
   ```bash
   python -m uvicorn backend.api.main:app --port 8000
   ```
3. Migrations will apply automatically on startup
4. Refresh the frontend - the app should load normally

**Troubleshooting:**
- If migrations fail, check the backend logs for errors
- Ensure the database file is not locked by another process
- Check that the `backend/db/migrations/` directory exists and contains `.sql` files

### Health and Capabilities Endpoints

| Endpoint | Purpose |
|----------|---------|
| `GET /health` | Root health check: DB readiness, schema health, pending migrations, LIVE trading flag |
| `GET /api/v1/ops/health` | Deep health check: full migration list, provider config, DB path |
| `GET /api/v1/ops/capabilities` | Feature flags: LIVE/PAPER enabled, news/insights status, DB readiness |

The frontend fetches both `/ops/health` and `/ops/capabilities` on startup and gates the
UI accordingly:
- If DB is unhealthy or migrations are pending: shows "Database Setup Required" screen.
- If LIVE trading is disabled: shows an amber banner and hides LIVE Confirm buttons.


### Configure OpenTelemetry (Optional)

To export telemetry to an OTLP collector:

```bash
export OTLP_ENDPOINT=http://localhost:4317  # OTLP gRPC endpoint
export SERVICE_NAME=executivedesk-ai
export SERVICE_VERSION=1.0.0
```

If `OTLP_ENDPOINT` is not set, spans are logged to console (or silently dropped during pytest).

### View Trades/Evals/Telemetry in UI

1. Navigate to `http://localhost:3000/chat`
2. Use the **sidebar tabs** to switch between:
   - **Chats**: Conversation threads
   - **Trades**: Run history (execution mode, status, timestamps)
   - **Evals**: Evaluation results (placeholder)
   - **Telemetry**: Per-run observability metrics (tool calls, events, errors, duration)

3. Start a new conversation and try: "Buy me the most profitable crypto of the last 24 hours for $10"

## Architecture

- **Backend**: FastAPI with orchestrator, DAG nodes, providers, policy engine
- **Frontend**: Next.js with Recharts for time-series visualization
- **Database**: SQLite with enterprise schema (18 tables)
- **Execution**: Paper trading provider with realistic order lifecycle

## Key Features

- ✅ End-to-end run execution with DAG nodes
- ✅ Policy engine with deterministic checks
- ✅ Approval workflow
- ✅ Portfolio snapshots and time-series charts
- ✅ Order lifecycle with events
- ✅ Online evaluations
- ✅ SSE streaming for real-time updates
- ✅ **Premium ChatGPT-like UI** with persistent conversations
- ✅ **Observability**: Telemetry persisted to DB (survives process exit)
- ✅ **Security**: Rate limiting and audit logging

## New Features

### Premium ChatGPT-Like UI
- Left sidebar with **Chats/Trades/Evals/Telemetry** tabs
- Persistent conversation threads
- Natural language interaction (no command buttons)
- Dark/light mode toggle
- SSE streaming for real-time updates

### Observability
- **Run Telemetry**: Duration, tool calls, events, errors persisted to DB
- **OpenTelemetry**: OTLP exporter support (configurable via env vars)
- **Telemetry API**: Query telemetry via `/api/v1/telemetry/runs`

### Security Hardening
- **Rate Limiting**: Per-route quotas (10/min for sensitive endpoints)
- **Audit Logging**: Critical actions logged with secret redaction
- **Input Validation**: Pydantic models for request/response

See `FINAL_SUMMARY.md` for complete documentation.
See `REFACTOR_SUMMARY.md` for refactoring details.

## LIVE Trading RUNBOOK

### Prerequisites

**⚠️ CRITICAL: Rotate Keys First**
If keys were previously shared, rotate them before enabling LIVE trading:
- Coinbase: https://portal.cdp.coinbase.com/
- OpenAI: https://platform.openai.com/api-keys

### 1. Configure Coinbase Private Key

**Option A: File-based (Recommended)**
```bash
# Create secrets directory (already exists)
# Create PEM file
echo "-----BEGIN EC PRIVATE KEY-----
<YOUR_PRIVATE_KEY_DATA>
-----END EC PRIVATE KEY-----" > secrets/coinbase_private_key.pem

# Update .env
COINBASE_API_PRIVATE_KEY_PATH=./secrets/coinbase_private_key.pem
```

**Option B: Environment Variable**
```bash
# Use single-line escaped format in .env
COINBASE_API_PRIVATE_KEY="-----BEGIN EC PRIVATE KEY-----\n<KEY_DATA>\n-----END EC PRIVATE KEY-----"
```

### 2. Enable LIVE Trading

Update `.env`:
```bash
# Enable LIVE trading
ENABLE_LIVE_TRADING=true

# REQUIRED: Use real market data (not stub)
MARKET_DATA_MODE=coinbase

# Set safety cap (default: $20)
LIVE_MAX_NOTIONAL_USD=20.0

# Coinbase credentials
COINBASE_API_KEY_NAME=organizations/.../apiKeys/...
COINBASE_API_PRIVATE_KEY_PATH=./secrets/coinbase_private_key.pem
```

### 3. Start Backend

```bash
python -m uvicorn backend.api.main:app --reload --port 8000
```

**Expected startup log:**
```
⚠️  LIVE TRADING ENABLED WITH REAL KEYS DETECTED ⚠️
    Ensure keys were rotated if previously shared.
    Secrets are never logged by this application.
```

### 4. Verify Configuration

```bash
curl http://localhost:8000/api/v1/ops/health | jq .config
```

**Expected output:**
```json
{
  "enable_live_trading": true,
  "execution_mode_default": "PAPER",
  "market_data_mode": "coinbase",
  "coinbase_private_key_source": "path",
  "live_max_notional_usd": 20.0
}
```

### 5. Safe LIVE Trial

**Test with small order (under $20 cap):**
```bash
curl -X POST http://localhost:8000/api/v1/chat/command \
  -H "Content-Type: application/json" \
  -H "X-Dev-Tenant: t_default" \
  -d '{"text": "buy $5 of BTC", "budget_usd": 5.0, "mode": "LIVE"}'
```

**Monitor execution:**
```bash
# Check run status
curl http://localhost:8000/api/v1/runs | jq

# View telemetry
curl http://localhost:8000/api/v1/telemetry/runs/<run_id> | jq
```

### Safety Features

- ✅ **Hard Order Cap**: LIVE orders limited to $20 by default (configurable via `LIVE_MAX_NOTIONAL_USD`)
- ✅ **Market Data Enforcement**: LIVE mode requires `MARKET_DATA_MODE=coinbase` (not stub)
- ✅ **Startup Warning**: Banner displayed when LIVE trading enabled with real keys
- ✅ **Secret Protection**: No key material in logs, errors, or API responses
- ✅ **Config Sanity Check**: `/api/v1/ops/health` shows configuration (no secrets)

### Verification Commands

```bash
# Check compilation
python -m compileall backend

# Verify no dotenv warnings
python -c "import backend.api.main; print('✓ Import successful')"

# Run tests
python -m pytest -v

# Grep for safety features
Select-String -Path "backend\**\*.py" -Pattern "LIVE_MAX_NOTIONAL_USD"
Select-String -Path "backend\services\market_data_provider.py" -Pattern "LIVE trading requires"
```

### Troubleshooting

**"LIVE trading is disabled"**
- Set `ENABLE_LIVE_TRADING=true` in `.env`

**"LIVE trading requires MARKET_DATA_MODE=coinbase"**
- Set `MARKET_DATA_MODE=coinbase` in `.env` (not `stub`)

**"LIVE order blocked: notional $X exceeds LIVE_MAX_NOTIONAL_USD"**
- Reduce order size or increase `LIVE_MAX_NOTIONAL_USD` in `.env`

**"Coinbase private key not configured"**
- Set `COINBASE_API_PRIVATE_KEY_PATH` or `COINBASE_API_PRIVATE_KEY` in `.env`

## Observability

### Prometheus Metrics

The platform exposes Prometheus-compatible metrics at `/api/v1/metrics`.

**Key Metrics:**
- `run_success_total{mode}` - Successful runs by mode (LIVE/PAPER/REPLAY)
- `run_failure_total{mode,reason}` - Failed runs with reason codes
- `node_latency_seconds{node}` - Node execution latency histogram
- `external_api_latency_seconds{provider,endpoint}` - External API latency
- `coinbase_429_total` - Coinbase rate limit hits
- `ranked_assets_count` - Assets successfully ranked
- `dropped_assets_total{reason}` - Assets dropped from ranking by reason

**Example Queries:**
```promql
# Success rate over last hour
rate(run_success_total[1h]) / (rate(run_success_total[1h]) + rate(run_failure_total[1h]))

# P95 node latency
histogram_quantile(0.95, rate(node_latency_seconds_bucket[5m]))

# Coinbase 429 rate
rate(coinbase_429_total[1h])
```

**JSON Metrics (debugging):**
```bash
curl http://localhost:8000/api/v1/metrics/json | jq
```

### OpenTelemetry Tracing

Traces are exported via OTLP (configurable via `OTLP_ENDPOINT`).

**Span Hierarchy:**
- `execute_run` (root span)
  - `node.research` - Market data fetching
  - `node.signals` - Signal generation
  - `node.risk` - Risk assessment
  - `node.strategy` - Asset selection
  - ... (10 nodes total)

**Node Span Attributes:**
- `run_id`, `tenant_id`, `node_name`, `mode`
- `external_calls_count`, `rate_limit_hits`, `cache_hits`
- `ranked_assets_count`, `dropped_assets_count`

### Structured Logging

All logs are JSON-formatted with automatic secret redaction.

**Log Fields:**
- `timestamp`, `level`, `message`, `module`, `function`
- Correlation IDs: `run_id`, `trace_id`, `request_id`, `tenant_id`
- Node context: `node`, `event`, `elapsed_ms`, `error_class`

**Secret Redaction:**
- API keys, private keys, JWT tokens, passwords automatically redacted
- Patterns matched: `api_key=*`, `sk-*`, `-----BEGIN.*PRIVATE KEY-----`, `eyJ*.*.*`

## Evaluations

### Built-in Evals (16 deep evals)

**Hallucination Detection:**
- `evidence_coverage` - All claims have evidence artifacts
- `claim_faithfulness` - Numeric claims match artifacts
- `tool_use_truthfulness` - Tool calls actually exist in DB
- `uncertainty_discipline` - Empty rankings produce failure artifacts

**Agent Quality:**
- `plan_completeness` - Required nodes executed
- `loop_thrash` - Tool calls bounded (no infinite loops)
- `constraint_respect` - Caps/allowlists enforced
- `empty_rankings_never_silent` - Failures properly documented
- `rate_limit_resilience` - Backoff/retry behavior correct

**Other Evals:**
- `action_grounding`, `budget_compliance`, `ranking_correctness`
- `numeric_grounding`, `execution_quality`, `tool_reliability`
- `determinism_replay`, `policy_invariants`, `ux_completeness`

### Running Evals

Evals run automatically after each run. View results:

```bash
# Get all evals for a run
curl http://localhost:8000/api/v1/evals/run/{run_id} | jq

# Check for failures
curl http://localhost:8000/api/v1/evals/run/{run_id} | jq '.failures'
```

## Testing

### Run Tests

```bash
# All tests
python -m pytest -v

# Unit tests only (fast)
python -m pytest tests/test_research_rankings.py tests/test_intent_classification.py -v

# Integration tests
python -m pytest tests/test_confirmation_flow.py -v

# Golden run tests
python -m pytest tests/test_golden_runs.py -v

# Secret redaction tests
python -m pytest tests/test_secret_redaction.py -v
```

### VCR-Style Fixtures

Tests use recorded HTTP responses for determinism:
- Fixtures: `tests/fixtures/vcr_cassettes/*.json`
- Golden runs: `tests/fixtures/golden_runs/*.json`

### Verification Script

Run end-to-end verification:

```bash
# Start backend first
uvicorn backend.api.main:app --port 8000

# Then run verification
python scripts/verify_commands.py
```

Checks:
- Health check
- Conversation creation
- Trade confirmation flow
- Artifact generation (universe_snapshot, research_summary, financial_brief)
- Eval execution
- Prometheus metrics
