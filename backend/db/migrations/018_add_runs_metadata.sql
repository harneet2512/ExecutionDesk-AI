-- Add metadata_json and intent_json columns to runs table
ALTER TABLE runs ADD COLUMN metadata_json TEXT;
ALTER TABLE runs ADD COLUMN intent_json TEXT;
