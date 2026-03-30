-- Migration 010: Conversations, Telemetry, and Audit Logging
-- Adds conversation management, run telemetry persistence, and audit logging

-- ============================================================================
-- CONVERSATIONS & MESSAGES
-- ============================================================================

-- Conversations table (chat threads)
CREATE TABLE IF NOT EXISTS conversations (
    conversation_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    title TEXT,  -- Auto-generated from first message or user-provided
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (tenant_id) REFERENCES tenants(tenant_id)
);

CREATE INDEX IF NOT EXISTS idx_conversations_tenant_id ON conversations(tenant_id);
CREATE INDEX IF NOT EXISTS idx_conversations_created_at ON conversations(created_at);

-- Messages table (chat messages in conversations)
CREATE TABLE IF NOT EXISTS messages (
    message_id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    role TEXT NOT NULL,  -- 'user' or 'assistant'
    content TEXT NOT NULL,  -- Message text
    run_id TEXT,  -- Link to run if message triggered a run
    metadata_json TEXT,  -- JSON object for additional metadata (e.g., charts, artifacts)
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (conversation_id) REFERENCES conversations(conversation_id) ON DELETE CASCADE,
    FOREIGN KEY (run_id) REFERENCES runs(run_id) ON DELETE SET NULL,
    FOREIGN KEY (tenant_id) REFERENCES tenants(tenant_id)
);

CREATE INDEX IF NOT EXISTS idx_messages_conversation_id ON messages(conversation_id);
CREATE INDEX IF NOT EXISTS idx_messages_run_id ON messages(run_id);
CREATE INDEX IF NOT EXISTS idx_messages_tenant_id ON messages(tenant_id);
CREATE INDEX IF NOT EXISTS idx_messages_created_at ON messages(created_at);

-- ============================================================================
-- RUN TELEMETRY (persisted observability metrics)
-- ============================================================================

-- Run telemetry table (aggregated metrics per run)
CREATE TABLE IF NOT EXISTS run_telemetry (
    run_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    started_at TEXT,
    ended_at TEXT,
    duration_ms INTEGER,  -- Total duration in milliseconds
    tool_calls_count INTEGER DEFAULT 0,
    sse_events_count INTEGER DEFAULT 0,
    error_count INTEGER DEFAULT 0,
    last_error TEXT,
    tokens_in INTEGER,  -- Input tokens (if available)
    tokens_out INTEGER,  -- Output tokens (if available)
    trace_id TEXT,  -- OpenTelemetry trace ID
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (run_id) REFERENCES runs(run_id) ON DELETE CASCADE,
    FOREIGN KEY (tenant_id) REFERENCES tenants(tenant_id)
);

CREATE INDEX IF NOT EXISTS idx_run_telemetry_tenant_id ON run_telemetry(tenant_id);
CREATE INDEX IF NOT EXISTS idx_run_telemetry_started_at ON run_telemetry(started_at);
CREATE INDEX IF NOT EXISTS idx_run_telemetry_trace_id ON run_telemetry(trace_id);

-- ============================================================================
-- AUDIT LOGS (security and compliance)
-- ============================================================================

-- Audit log table (records critical actions)
CREATE TABLE IF NOT EXISTS audit_logs (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    actor TEXT,  -- user_id or 'system'
    action TEXT NOT NULL,  -- e.g., 'commands.execute', 'runs.trigger', 'approvals.approve', 'live.blocked'
    entity_type TEXT,  -- e.g., 'run', 'order', 'approval'
    entity_id TEXT,  -- ID of the affected entity
    request_json TEXT,  -- Redacted request body (JSON)
    response_status INTEGER,  -- HTTP status code
    error_message TEXT,  -- Error message if action failed
    ip_address TEXT,  -- Client IP address
    user_agent TEXT,  -- Client user agent
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (tenant_id) REFERENCES tenants(tenant_id)
);

CREATE INDEX IF NOT EXISTS idx_audit_logs_tenant_id ON audit_logs(tenant_id);
CREATE INDEX IF NOT EXISTS idx_audit_logs_action ON audit_logs(action);
CREATE INDEX IF NOT EXISTS idx_audit_logs_entity_type ON audit_logs(entity_type);
CREATE INDEX IF NOT EXISTS idx_audit_logs_entity_id ON audit_logs(entity_id);
CREATE INDEX IF NOT EXISTS idx_audit_logs_created_at ON audit_logs(created_at);
CREATE INDEX IF NOT EXISTS idx_audit_logs_actor ON audit_logs(actor);
