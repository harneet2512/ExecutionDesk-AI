-- Migration 002: Additional indexes for run_events (if needed)
-- Note: run_events table is already created in 001_init.sql with tenant_id
-- This migration is now index-only to avoid conflicts

-- Indexes already created in 001_init.sql, but kept here for idempotency
CREATE INDEX IF NOT EXISTS idx_run_events_run_id ON run_events(run_id);
CREATE INDEX IF NOT EXISTS idx_run_events_ts ON run_events(ts);
CREATE INDEX IF NOT EXISTS idx_run_events_tenant_id ON run_events(tenant_id);
