-- Coinbase hardening: fills, order enhancements, idempotency

-- Fills table (if not exists)
CREATE TABLE IF NOT EXISTS fills (
    fill_id TEXT PRIMARY KEY,
    order_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    product_id TEXT NOT NULL,
    price REAL NOT NULL,
    size REAL NOT NULL,
    fee REAL DEFAULT 0.0,
    trade_id TEXT,
    liquidity_indicator TEXT,  -- 'MAKER' or 'TAKER'
    filled_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (order_id) REFERENCES orders(order_id) ON DELETE CASCADE,
    FOREIGN KEY (run_id) REFERENCES runs(run_id) ON DELETE CASCADE,
    FOREIGN KEY (tenant_id) REFERENCES tenants(tenant_id)
);

CREATE INDEX IF NOT EXISTS idx_fills_order_id ON fills(order_id);
CREATE INDEX IF NOT EXISTS idx_fills_run_id ON fills(run_id);
CREATE INDEX IF NOT EXISTS idx_fills_tenant_id ON fills(tenant_id);

-- Enhance orders table (idempotent: SQLite doesn't support IF NOT EXISTS for ALTER TABLE)
-- Check if columns exist before adding (via PRAGMA table_info)
-- For idempotency, use INSERT OR IGNORE approach for schema migrations
-- In practice, migrations are only run once via init_db, so ALTER TABLE is safe
-- If column exists, ALTER TABLE will fail; wrap in try/except in Python or use schema check
-- For SQL-only migration, we rely on init_db's migration tracking to prevent duplicate runs

-- Note: SQLite ALTER TABLE ADD COLUMN will fail if column exists
-- Migration tracking in init_db() ensures this only runs once per environment
-- If needed, can use: SELECT sql FROM sqlite_master WHERE name='orders' to check schema
ALTER TABLE orders ADD COLUMN client_order_id TEXT;
ALTER TABLE orders ADD COLUMN filled_qty REAL DEFAULT 0.0;
ALTER TABLE orders ADD COLUMN avg_fill_price REAL;
ALTER TABLE orders ADD COLUMN total_fees REAL DEFAULT 0.0;
ALTER TABLE orders ADD COLUMN status_reason TEXT;
ALTER TABLE orders ADD COLUMN status_updated_at TEXT;

-- Unique index for idempotency (client_order_id + tenant_id + provider)
CREATE UNIQUE INDEX IF NOT EXISTS idx_orders_client_order_id_unique ON orders(tenant_id, provider, client_order_id) WHERE client_order_id IS NOT NULL;

-- Product details cache (for min order size checks)
CREATE TABLE IF NOT EXISTS product_details (
    product_id TEXT PRIMARY KEY,
    base_currency TEXT NOT NULL,
    quote_currency TEXT NOT NULL,
    base_min_size TEXT,
    quote_increment TEXT,
    base_increment TEXT,
    min_market_funds TEXT,
    status TEXT,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_product_details_status ON product_details(status);
