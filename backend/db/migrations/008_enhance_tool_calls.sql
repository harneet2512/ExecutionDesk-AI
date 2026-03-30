-- Enhance tool_calls table with additional fields
ALTER TABLE tool_calls ADD COLUMN latency_ms INTEGER;
ALTER TABLE tool_calls ADD COLUMN error_text TEXT;
ALTER TABLE tool_calls ADD COLUMN http_status INTEGER;
ALTER TABLE tool_calls ADD COLUMN attempt INTEGER DEFAULT 1;

CREATE INDEX IF NOT EXISTS idx_tool_calls_status ON tool_calls(status);
CREATE INDEX IF NOT EXISTS idx_tool_calls_ts ON tool_calls(ts);

-- Enhance runs table
ALTER TABLE runs ADD COLUMN intent_json TEXT;
ALTER TABLE runs ADD COLUMN command_text TEXT;
ALTER TABLE runs ADD COLUMN provider_name TEXT;
ALTER TABLE runs ADD COLUMN error_summary TEXT;

-- Enhance eval_results table
ALTER TABLE eval_results ADD COLUMN evaluator_type TEXT DEFAULT 'default';
ALTER TABLE eval_results ADD COLUMN dataset_id TEXT;
ALTER TABLE eval_results ADD COLUMN thresholds_json TEXT;
