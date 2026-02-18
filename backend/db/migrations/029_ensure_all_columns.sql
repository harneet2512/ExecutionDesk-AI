-- Migration 029: Ensure all required columns exist on runs and related tables.
-- This is a safety-net migration that idempotently adds columns which may have
-- been missed due to partial migration failures.  Each ALTER TABLE will be
-- executed individually; "duplicate column" errors are silently skipped by the
-- migration runner.

-- runs table columns added by migrations 006, 018, 019, 022
ALTER TABLE runs ADD COLUMN command_text TEXT;
ALTER TABLE runs ADD COLUMN execution_plan_json TEXT;
ALTER TABLE runs ADD COLUMN parsed_intent_json TEXT;
ALTER TABLE runs ADD COLUMN metadata_json TEXT;
ALTER TABLE runs ADD COLUMN intent_json TEXT;
ALTER TABLE runs ADD COLUMN failure_reason TEXT;
ALTER TABLE runs ADD COLUMN failure_code TEXT;
ALTER TABLE runs ADD COLUMN news_enabled INTEGER DEFAULT 1;
ALTER TABLE runs ADD COLUMN asset_class TEXT DEFAULT 'CRYPTO';

-- orders columns added by migration 009
ALTER TABLE orders ADD COLUMN filled_qty REAL;
ALTER TABLE orders ADD COLUMN avg_fill_price REAL;
ALTER TABLE orders ADD COLUMN total_fees REAL DEFAULT 0;
ALTER TABLE orders ADD COLUMN client_order_id TEXT;
ALTER TABLE orders ADD COLUMN status_reason TEXT;
ALTER TABLE orders ADD COLUMN status_updated_at TEXT;

-- tool_calls columns added by migration 008
ALTER TABLE tool_calls ADD COLUMN error_text TEXT;
ALTER TABLE tool_calls ADD COLUMN latency_ms REAL;

-- trade_confirmations columns added by migration 025
ALTER TABLE trade_confirmations ADD COLUMN insight_json TEXT;

-- trade_confirmations run_id link added by migration 023
ALTER TABLE trade_confirmations ADD COLUMN run_id TEXT;

-- approvals: decision and updated_at columns used by approval_node and approvals route
ALTER TABLE approvals ADD COLUMN decision TEXT;
ALTER TABLE approvals ADD COLUMN updated_at TEXT;

-- Ensure run_artifacts table exists (created in migration 016)
CREATE TABLE IF NOT EXISTS run_artifacts (
    run_id TEXT NOT NULL,
    step_name TEXT NOT NULL,
    artifact_type TEXT NOT NULL,
    artifact_json TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(run_id) REFERENCES runs(run_id)
);
CREATE INDEX IF NOT EXISTS idx_run_artifacts_run_id ON run_artifacts(run_id);

-- Ensure fills table exists (created in migration 009)
-- Schema must match migration 009: tenant_id NOT NULL, NOT NULL constraints, FKs
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
    liquidity_indicator TEXT,
    filled_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (order_id) REFERENCES orders(order_id) ON DELETE CASCADE,
    FOREIGN KEY (run_id) REFERENCES runs(run_id) ON DELETE CASCADE,
    FOREIGN KEY (tenant_id) REFERENCES tenants(tenant_id)
);
CREATE INDEX IF NOT EXISTS idx_fills_order_id ON fills(order_id);
CREATE INDEX IF NOT EXISTS idx_fills_run_id ON fills(run_id);

-- Ensure market_candles table exists (created in migration 005)
CREATE TABLE IF NOT EXISTS market_candles (
    id TEXT PRIMARY KEY,
    symbol TEXT NOT NULL,
    interval TEXT NOT NULL,
    start_time TEXT NOT NULL,
    end_time TEXT,
    open REAL,
    high REAL,
    low REAL,
    close REAL,
    volume REAL,
    ts TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_market_candles_symbol ON market_candles(symbol);
