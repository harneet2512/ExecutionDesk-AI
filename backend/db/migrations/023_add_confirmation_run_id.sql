-- Add run_id to trade_confirmations so we can link confirmations to runs for recovery
ALTER TABLE trade_confirmations ADD COLUMN run_id TEXT;
