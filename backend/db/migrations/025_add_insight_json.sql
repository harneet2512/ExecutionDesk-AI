-- Add insight_json column to trade_confirmations for pre-confirm financial insight
ALTER TABLE trade_confirmations ADD COLUMN insight_json TEXT;
