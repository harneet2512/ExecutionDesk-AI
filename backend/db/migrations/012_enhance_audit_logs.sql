-- Migration 012: Enhance audit_logs table with security fields
-- Adds request_hash (SHA256 for tamper detection), request_id, trace_id, role

-- Add new columns to audit_logs
-- Note: SQLite doesn't support IF NOT EXISTS in ALTER TABLE, but migration handler catches duplicate column errors
ALTER TABLE audit_logs ADD COLUMN request_hash TEXT;  -- SHA256 hash of request_json for tamper detection
ALTER TABLE audit_logs ADD COLUMN request_id TEXT;     -- Request ID from middleware
ALTER TABLE audit_logs ADD COLUMN trace_id TEXT;       -- OpenTelemetry trace ID
ALTER TABLE audit_logs ADD COLUMN role TEXT;           -- User role (viewer/trader/admin)

-- Create index on request_hash for integrity checks
CREATE INDEX IF NOT EXISTS idx_audit_logs_request_hash ON audit_logs(request_hash);

-- Create index on request_id for correlation
CREATE INDEX IF NOT EXISTS idx_audit_logs_request_id ON audit_logs(request_id);

-- Create index on trace_id for observability correlation
CREATE INDEX IF NOT EXISTS idx_audit_logs_trace_id ON audit_logs(trace_id);

-- Create index on role for RBAC audit analysis
CREATE INDEX IF NOT EXISTS idx_audit_logs_role ON audit_logs(role);
