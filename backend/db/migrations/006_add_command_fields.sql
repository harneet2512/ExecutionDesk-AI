-- Add fields for natural language command support
ALTER TABLE runs ADD COLUMN command_text TEXT;
ALTER TABLE runs ADD COLUMN execution_plan_json TEXT;
ALTER TABLE runs ADD COLUMN parsed_intent_json TEXT;
