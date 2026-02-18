-- Trade tickets for ASSISTED_LIVE execution mode (stocks)
-- User receives an order ticket, executes manually, then submits receipt

CREATE TABLE IF NOT EXISTS trade_tickets (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    asset_class TEXT NOT NULL DEFAULT 'STOCK',
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    notional_usd REAL NOT NULL,
    est_qty REAL,
    suggested_limit REAL,
    tif TEXT NOT NULL DEFAULT 'DAY',
    expires_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'PENDING',
    receipt_json TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_trade_tickets_run ON trade_tickets(run_id);
CREATE INDEX IF NOT EXISTS idx_trade_tickets_tenant_status ON trade_tickets(tenant_id, status);
CREATE INDEX IF NOT EXISTS idx_trade_tickets_expires ON trade_tickets(expires_at);
