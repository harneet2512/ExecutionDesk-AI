-- Migration 032: Persistent product catalog + auto-sell support + news fetch log
-- Supports Risk 4 (product catalog), Risk 1 (auto-sell), Risk 5 (news diagnostics)

-- Persistent product catalog (refreshed from Coinbase public API)
CREATE TABLE IF NOT EXISTS product_catalog (
    product_id TEXT PRIMARY KEY,
    base_currency TEXT NOT NULL,
    quote_currency TEXT NOT NULL,
    base_min_size TEXT,
    base_max_size TEXT,
    quote_increment TEXT,
    base_increment TEXT,
    min_market_funds TEXT,
    max_market_funds TEXT,
    status TEXT DEFAULT 'online',
    trading_disabled INTEGER DEFAULT 0,
    updated_at TEXT NOT NULL
);

-- Auto-sell metadata on trade confirmations
ALTER TABLE trade_confirmations ADD COLUMN auto_sell_json TEXT;

-- Link auto-sell order to parent buy order
ALTER TABLE orders ADD COLUMN parent_order_id TEXT;

-- News fetch diagnostics log
CREATE TABLE IF NOT EXISTS news_fetch_log (
    fetch_id TEXT PRIMARY KEY,
    run_id TEXT,
    provider TEXT NOT NULL,
    status TEXT NOT NULL,
    items_count INTEGER DEFAULT 0,
    latency_ms INTEGER,
    error TEXT,
    ts TEXT NOT NULL
);
