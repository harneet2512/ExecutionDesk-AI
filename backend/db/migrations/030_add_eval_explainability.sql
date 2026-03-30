-- Add LLM explainability fields to eval_results (scoring stays rule-based; LLM only generates explanation text)
ALTER TABLE eval_results ADD COLUMN explanation TEXT;
ALTER TABLE eval_results ADD COLUMN explanation_source TEXT;
