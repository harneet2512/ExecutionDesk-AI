# Threat Model: Agentic Trading Assistant

**Version**: 1.0  
**Date**: 2025-01-27  
**Scope**: Full-stack trading assistant (FastAPI backend + Next.js frontend)

---

## System Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                         FRONTEND (Next.js)                      │
│  ┌───────────────────────────────────────────────────────────┐ │
│  │  ChatGPT-like UI: Conversations, Trades, Evals, Telemetry │ │
│  │  SSE Streaming (run events), Charts (Recharts)            │ │
│  └───────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
                              │ HTTPS
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                      TRUST BOUNDARY                              │
│                      ┌───────────────────────────────────────┐  │
│                      │      FASTAPI BACKEND                  │  │
│                      │  ┌─────────────────────────────────┐  │  │
│                      │  │  API Routes                     │  │  │
│                      │  │  - /auth (JWT)                  │  │  │
│                      │  │  - /chat/command                │  │  │
│                      │  │  - /runs/trigger                │  │  │
│                      │  │  - /runs/{id}/events (SSE)      │  │  │
│                      │  │  - /approvals                   │  │  │
│                      │  │  - /telemetry                   │  │  │
│                      │  └─────────────────────────────────┘  │  │
│                      │  ┌─────────────────────────────────┐  │  │
│                      │  │  Middleware                     │  │  │
│                      │  │  - Auth (JWT verify)            │  │  │
│                      │  │  - RBAC (role checks)           │  │  │
│                      │  │  - Rate Limiting                │  │  │
│                      │  │  - Audit Logging                │  │  │
│                      │  └─────────────────────────────────┘  │  │
│                      │  ┌─────────────────────────────────┐  │  │
│                      │  │  Orchestrator                   │  │  │
│                      │  │  - DAG execution                │  │  │
│                      │  │  - MCP tool calls               │  │  │
│                      │  │  - Event emission               │  │  │
│                      │  └─────────────────────────────────┘  │  │
│                      └───────────────────────────────────────┘  │
│                                   │                             │
│                                   ▼                             │
│                      ┌───────────────────────────────────────┐  │
│                      │  DATABASE (SQLite)                    │  │
│                      │  - conversations, messages            │  │
│                      │  - runs, orders, portfolio_snapshots  │  │
│                      │  - run_telemetry, audit_logs          │  │
│                      │  - tool_calls, eval_results           │  │
│                      └───────────────────────────────────────┘  │
│                                   │                             │
│                                   ▼                             │
│                      ┌───────────────────────────────────────┐  │
│                      │  EXTERNAL PROVIDERS                   │  │
│                      │  - Coinbase API (market data/trading) │  │
│                      │  - OpenAI API (LLM)                   │  │
│                      └───────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

**Trust Boundaries**:
- Frontend ↔ Backend: HTTPS required (JWT in Authorization header)
- Backend ↔ Database: Local SQLite (trusted)
- Backend ↔ External APIs: HTTPS (API keys in env/config)

---

## Assets

| Asset | Description | Sensitivity | Location |
|-------|-------------|-------------|----------|
| **API Keys** | Coinbase API key/private key, OpenAI API key | **CRITICAL** | Environment variables, database (redacted in logs) |
| **User Funds** | Portfolio balances, positions, order history | **CRITICAL** | `portfolio_snapshots`, `orders`, `fills` tables |
| **Trade History** | Runs, orders, fills, execution details | **HIGH** | `runs`, `orders`, `order_events`, `fills` tables |
| **Telemetry** | Run metrics (tool calls, errors, duration) | **MEDIUM** | `run_telemetry` table |
| **Audit Logs** | Security audit trail | **HIGH** | `audit_logs` table |
| **PII** | User emails (if stored), IP addresses | **MEDIUM** | `users` table, `audit_logs` |
| **JWT Secrets** | Token signing secret | **CRITICAL** | Environment variable (`JWT_SECRET`) |

---

## Entry Points

| Entry Point | Method | Auth Required | RBAC | Rate Limit |
|-------------|--------|---------------|------|------------|
| `POST /api/v1/auth/dev-token` | POST | `ENABLE_DEV_AUTH` env | None | 5/min |
| `POST /api/v1/auth/login` | POST | None | None | 10/min |
| `POST /api/v1/chat/command` | POST | JWT | trader/admin | 10/min |
| `POST /api/v1/commands/execute` | POST | JWT | trader/admin | 10/min |
| `POST /api/v1/runs/trigger` | POST | JWT | trader/admin | 10/min |
| `GET /api/v1/runs/{id}/events` | SSE | JWT | viewer/trader/admin | 30/min connections |
| `GET /api/v1/runs` | GET | JWT | viewer/trader/admin | 30/min |
| `GET /api/v1/runs/{id}` | GET | JWT | viewer/trader/admin | 30/min |
| `POST /api/v1/approvals/{id}/approve` | POST | JWT | admin | 10/min |
| `POST /api/v1/approvals/{id}/deny` | POST | JWT | admin | 10/min |
| `GET /api/v1/telemetry/runs` | GET | JWT | viewer/trader/admin | 30/min |
| `GET /api/v1/conversations` | GET | JWT | viewer/trader/admin | 30/min |
| `POST /api/v1/conversations/{id}/messages` | POST | JWT | trader/admin | 10/min |

---

## Threats (STRIDE)

### S - Spoofing

| Threat | Description | Impact | Mitigation |
|--------|-------------|--------|------------|
| **Impersonation via JWT** | Attacker steals JWT or crafts fake token | **HIGH**: Unauthorized access to trades/funds | ✅ JWT signed with `JWT_SECRET` (env var), expiration (60min), algorithm validation (HS256 only) |
| **X-Dev-Tenant header abuse** | Attacker sends `X-Dev-Tenant` header to bypass auth | **CRITICAL**: Tenant isolation bypass | ✅ Only allowed if `ENABLE_DEV_AUTH=false` AND `api_secret_key==dev-secret`, removed in production |
| **SSE connection hijacking** | Attacker connects to SSE stream of another user's run | **MEDIUM**: Leak run execution details | ✅ SSE endpoint requires JWT, tenant_id enforced server-side, user can only access own tenant's runs |

**Mitigations Implemented**:
- JWT token validation with signature verification (`backend/core/security.py`)
- Tenant isolation enforced via JWT `tenant_id` (not `X-Dev-Tenant` for security)
- SSE endpoint checks JWT and tenant membership (`backend/api/routes/runs.py`)

---

### T - Tampering

| Threat | Description | Impact | Mitigation |
|--------|-------------|--------|------------|
| **Command injection** | Malicious command text executes arbitrary code | **CRITICAL**: RCE, data exfiltration | ✅ Input validation (control char stripping, length limits, symbol allowlist), Pydantic models with `extra="forbid"` |
| **Request body tampering** | Attacker modifies POST body to bypass constraints | **HIGH**: Budget override, mode switching | ✅ Server-side validation (Pydantic), `extra="forbid"` rejects unknown fields, max request size middleware |
| **Database tampering** | Attacker modifies audit_logs to erase traces | **HIGH**: Security audit compromised | ✅ Audit logs append-only (no UPDATE/DELETE), request_hash (SHA256) stored for integrity |
| **Symbol injection** | Attacker sends invalid symbols to cause errors | **MEDIUM**: Service disruption | ✅ Symbol allowlist (`KNOWN_SYMBOLS`), normalization to `product_id` format, validation in `chat.py` |

**Mitigations Implemented**:
- Pydantic models with strict validation (`backend/api/routes/chat.py`)
- Symbol allowlist and normalization (`backend/core/symbols.py`)
- Request size limits for sensitive endpoints (middleware)
- Audit log request_hash stored (SHA256) for tamper detection

---

### R - Repudiation

| Threat | Description | Impact | Mitigation |
|--------|-------------|--------|------------|
| **Denial of trades** | User claims they didn't execute a trade | **HIGH**: Financial disputes | ✅ Audit logs record `actor_id`, `tenant_id`, `role`, `timestamp`, `request_json_redacted`, `request_hash` |
| **Denial of approvals** | Admin claims they didn't approve a run | **HIGH**: Compliance violations | ✅ Audit log captures approval action with immutable `request_hash` |
| **Missing audit records** | Critical actions not logged | **CRITICAL**: No accountability | ✅ Middleware automatically logs: `commands.execute`, `runs.trigger`, `approvals.approve/deny`, auth failures |

**Mitigations Implemented**:
- Comprehensive audit logging (`backend/api/middleware/audit_log.py`)
- Request hash (SHA256) for non-repudiation
- Timestamp, actor_id, tenant_id, role in every audit record
- Audit logs written synchronously (not async fire-and-forget)

---

### I - Information Disclosure

| Threat | Description | Impact | Mitigation |
|--------|-------------|--------|------------|
| **API key leakage** | API keys exposed in logs/responses | **CRITICAL**: Unauthorized access to Coinbase/OpenAI | ✅ Central redaction utility (`redact_secrets()`), keys redacted in audit logs, tool_call payloads |
| **Tenant data leakage** | User A sees User B's runs/telemetry | **HIGH**: Privacy violation, trade secrets | ✅ Tenant isolation enforced server-side (JWT `tenant_id`), all queries filter by `tenant_id` |
| **SSE data leak** | Run events streamed to wrong user | **MEDIUM**: Execution details leaked | ✅ SSE endpoint validates JWT and tenant membership before streaming |
| **Audit log exposure** | Audit logs contain sensitive data | **MEDIUM**: PII/API keys in logs | ✅ Request JSON redacted before logging, long base64-like strings redacted heuristically |

**Mitigations Implemented**:
- Central redaction utility (`backend/core/redaction.py`)
- Tenant isolation in all data access (`backend/api/deps.py`, routes)
- SSE tenant validation (`backend/api/routes/runs.py`)
- Audit log redaction (secrets, tokens, API keys)

---

### D - Denial of Service

| Threat | Description | Impact | Mitigation |
|--------|-------------|--------|------------|
| **Rate limit bypass** | Attacker floods endpoints | **HIGH**: Service unavailability | ✅ In-memory rate limiting (30/min read, 10/min write, 5/min auth), 429 with `Retry-After` |
| **SSE connection exhaustion** | Attacker opens many SSE connections | **MEDIUM**: Resource exhaustion | ✅ Max 3 concurrent SSE connections per user, idle timeout, connection cleanup |
| **Large request bodies** | Attacker sends huge POST bodies | **MEDIUM**: Memory exhaustion | ✅ Request size limit middleware (e.g., 1MB for sensitive endpoints) |
| **Long-running queries** | Malicious queries cause DB locks | **MEDIUM**: Database unavailability | ✅ Query timeouts (implicit via SQLite), indexed queries on `tenant_id` |

**Mitigations Implemented**:
- Rate limiting middleware (`backend/api/middleware/rate_limit.py`)
- SSE connection limits and timeouts (`backend/api/routes/runs.py`)
- Request size limits (middleware)

---

### E - Elevation of Privilege

| Threat | Description | Impact | Mitigation |
|--------|-------------|--------|------------|
| **Role escalation** | Attacker crafts JWT with admin role | **CRITICAL**: Unauthorized approvals, LIVE mode access | ✅ JWT signed with `JWT_SECRET`, role cannot be spoofed, RBAC checks on every sensitive endpoint |
| **Viewer triggering runs** | `viewer` role attempts to execute trades | **HIGH**: Unauthorized trading | ✅ RBAC middleware checks role before `POST /runs/trigger`, `POST /commands/execute` |
| **LIVE mode bypass** | Attacker enables LIVE trading without permission | **CRITICAL**: Real funds at risk | ✅ `ENABLE_LIVE_TRADING` env var required, admin-only if implemented, default disabled |

**Mitigations Implemented**:
- RBAC dependency (`backend/api/deps.py`: `require_role()`)
- Role checks on sensitive endpoints (`backend/api/routes/runs.py`, `chat.py`, `commands.py`, `approvals.py`)
- JWT role cannot be spoofed (signed token)

---

## Residual Risks

| Risk | Description | Acceptability | Future Mitigation |
|------|-------------|---------------|-------------------|
| **In-memory rate limiting** | Not distributed; resets on restart | **ACCEPTABLE for demo** | Use Redis for distributed rate limiting in production |
| **SQLite single-file** | No replication, single point of failure | **ACCEPTABLE for demo** | Migrate to PostgreSQL with replication in production |
| **Local secrets** | JWT_SECRET, API keys in env vars (not secrets manager) | **ACCEPTABLE for demo** | Use AWS Secrets Manager / HashiCorp Vault in production |
| **No request signing** | Requests not cryptographically signed | **ACCEPTABLE** | Add HMAC request signing for API-to-API calls if needed |
| **No WAF** | No Web Application Firewall | **ACCEPTABLE** | Add Cloudflare WAF / AWS WAF in production |
| **No TLS termination** | Assuming HTTPS at load balancer | **ACCEPTABLE** | Ensure TLS 1.3 at load balancer, HSTS headers |

---

## Demo Security Posture

**Explicitly stated for demo**:

1. **Rate Limiting**: In-memory (resets on restart), per-tenant+actor+route
2. **Secrets**: Stored in environment variables (not a secrets manager)
3. **Database**: SQLite (single file, no replication)
4. **Auth**: JWT with HS256 (symmetric key, not RS256)
5. **Dev Token**: `POST /api/v1/auth/dev-token` available when `ENABLE_DEV_AUTH=true` (demo-only)
6. **X-Dev-Tenant**: Only allowed if `ENABLE_DEV_AUTH=false` AND dev secret (fallback, not secure)

**Production Requirements**:
- Distributed rate limiting (Redis)
- Secrets manager (AWS Secrets Manager / Vault)
- PostgreSQL with replication
- RS256 JWT (asymmetric keys)
- Remove `dev-token` endpoint
- Remove `X-Dev-Tenant` header support

---

## Security Controls Summary

| Control | Implementation | Status |
|---------|----------------|--------|
| **JWT Authentication** | `backend/core/security.py`, `backend/api/deps.py` | ✅ Implemented |
| **RBAC (viewer/trader/admin)** | `backend/api/deps.py`: `require_role()` | ✅ Implemented |
| **Tenant Isolation** | Server-side filtering by JWT `tenant_id` | ✅ Implemented |
| **Input Validation** | Pydantic models with `extra="forbid"`, constraints | ✅ Implemented |
| **Audit Logging** | `backend/api/middleware/audit_log.py`, redaction | ✅ Implemented |
| **Rate Limiting** | `backend/api/middleware/rate_limit.py` | ✅ Implemented |
| **SSE Protection** | Max connections, idle timeout, tenant validation | ✅ Implemented |
| **Secret Redaction** | `backend/core/redaction.py` | ✅ Implemented |
| **Request Size Limits** | Middleware for sensitive endpoints | ✅ Implemented |
| **Telemetry Persistence** | `run_telemetry` table, persisted to DB | ✅ Implemented |

---

## Future Work

1. **Distributed Rate Limiting**: Replace in-memory with Redis
2. **Request Signing**: HMAC-based request signing for API-to-API calls
3. **Audit Log Archival**: Move old audit logs to cold storage (S3)
4. **IP Allowlisting**: Restrict admin endpoints to specific IPs
5. **MFA**: Multi-factor authentication for admin role
6. **Session Management**: JWT refresh tokens, revocation list
7. **Secrets Rotation**: Automated rotation of JWT_SECRET, API keys
8. **SIEM Integration**: Send audit logs to Splunk/ELK for correlation
9. **Penetration Testing**: Regular pen tests by external security firm
10. **Compliance**: SOC 2, ISO 27001 certification

---

## References

- STRIDE framework: https://docs.microsoft.com/en-us/previous-versions/commerce-server/ee823878(v=cs.20)
- OWASP Top 10: https://owasp.org/www-project-top-ten/
- JWT Best Practices: https://tools.ietf.org/html/rfc8725
