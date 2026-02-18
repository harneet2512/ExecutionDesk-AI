-- Add step-level eval tracking and enterprise eval fields
ALTER TABLE eval_results ADD COLUMN step_name TEXT;
ALTER TABLE eval_results ADD COLUMN rationale TEXT;
ALTER TABLE eval_results ADD COLUMN inputs_json TEXT;
ALTER TABLE eval_results ADD COLUMN evaluator_type TEXT DEFAULT 'heuristic';
ALTER TABLE eval_results ADD COLUMN thresholds_json TEXT;

CREATE INDEX IF NOT EXISTS idx_eval_results_step_name ON eval_results(step_name);
CREATE INDEX IF NOT EXISTS idx_eval_results_eval_name ON eval_results(eval_name);
CREATE INDEX IF NOT EXISTS idx_eval_results_created_at ON eval_results(ts);
