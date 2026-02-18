-- Enhance eval_results for dashboard and RAG eval tracking
ALTER TABLE eval_results ADD COLUMN conversation_id TEXT;
ALTER TABLE eval_results ADD COLUMN message_id TEXT;
ALTER TABLE eval_results ADD COLUMN eval_category TEXT DEFAULT 'quality';
ALTER TABLE eval_results ADD COLUMN details_json TEXT;

CREATE INDEX IF NOT EXISTS idx_eval_results_category ON eval_results(eval_category);
CREATE INDEX IF NOT EXISTS idx_eval_results_conversation ON eval_results(conversation_id);
