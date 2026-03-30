-- Migration: Enhance Run Failure Tracking
-- Description: Adds structured failure tracking to runs table for better observability

-- Add failure_reason column (JSON with code, summary, root_cause, recommended_fix)
ALTER TABLE runs ADD COLUMN failure_reason TEXT;

-- Add failure_code column (e.g., RESEARCH_EMPTY_RANKINGS, EXECUTION_INSUFFICIENT_FUNDS)
ALTER TABLE runs ADD COLUMN failure_code TEXT;

-- Create index for failure_code lookups
CREATE INDEX IF NOT EXISTS idx_runs_failure_code ON runs(failure_code);
