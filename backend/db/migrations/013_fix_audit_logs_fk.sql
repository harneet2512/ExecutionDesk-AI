-- Migration 013: Fix audit_logs FK constraint
-- Remove FK constraint to non-existent tenants table
-- SQLite doesn't support DROP CONSTRAINT, so we need to recreate the table

-- Create new audit_logs table without FK constraint
CREATE TABLE IF NOT EXISTS audit_logs_new (
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
    request_hash TEXT,  -- SHA256 hash of request_json for tamper detection
    request_id TEXT,  -- Request ID from middleware
    trace_id TEXT,  -- OpenTelemetry trace ID
    role TEXT,  -- User role (viewer/trader/admin)
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Copy existing data
INSERT INTO audit_logs_new SELECT * FROM audit_logs;

-- Drop old table
DROP TABLE audit_logs;

-- Rename new table
ALTER TABLE audit_logs_new RENAME TO audit_logs;

-- Recreate indexes
CREATE INDEX IF NOT EXISTS idx_audit_logs_tenant_id ON audit_logs(tenant_id);
CREATE INDEX IF NOT EXISTS idx_audit_logs_action ON audit_logs(action);
CREATE INDEX IF NOT EXISTS idx_audit_logs_entity_type ON audit_logs(entity_type);
CREATE INDEX IF NOT EXISTS idx_audit_logs_entity_id ON audit_logs(entity_id);
CREATE INDEX IF NOT EXISTS idx_audit_logs_created_at ON audit_logs(created_at);
CREATE INDEX IF NOT EXISTS idx_audit_logs_actor ON audit_logs(actor);
CREATE INDEX IF NOT EXISTS idx_audit_logs_request_hash ON audit_logs(request_hash);
CREATE INDEX IF NOT EXISTS idx_audit_logs_request_id ON audit_logs(request_id);
CREATE INDEX IF NOT EXISTS idx_audit_logs_trace_id ON audit_logs(trace_id);
CREATE INDEX IF NOT EXISTS idx_audit_logs_role ON audit_logs(role);
