-- Add news toggle and asset class columns to runs table
-- news_enabled: 1 = news analysis ON (default), 0 = OFF
-- asset_class: CRYPTO (default) or STOCK

ALTER TABLE runs ADD COLUMN news_enabled INTEGER DEFAULT 1;
ALTER TABLE runs ADD COLUMN asset_class TEXT DEFAULT 'CRYPTO';
