-- Add metadata_json column to conversations table for pending trade storage
ALTER TABLE conversations ADD COLUMN metadata_json TEXT;
