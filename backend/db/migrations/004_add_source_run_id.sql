-- Add source_run_id column to runs table for REPLAY determinism
ALTER TABLE runs ADD COLUMN source_run_id TEXT;

CREATE INDEX IF NOT EXISTS idx_runs_source_run_id ON runs(source_run_id);
