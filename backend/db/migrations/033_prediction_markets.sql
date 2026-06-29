-- Migration 033: Prediction markets tables
-- Adds tables for Polymarket prediction market integration.

-- Cached prediction market metadata
CREATE TABLE IF NOT EXISTS prediction_markets_cache (
    condition_id TEXT PRIMARY KEY,
    question TEXT NOT NULL,
    slug TEXT,
    outcomes_json TEXT,              -- JSON: ["Yes", "No"]
    tokens_json TEXT,                -- JSON: [{token_id, outcome, price}, ...]
    volume REAL DEFAULT 0,
    liquidity REAL DEFAULT 0,
    yes_price REAL DEFAULT 0,
    no_price REAL DEFAULT 0,
    active INTEGER DEFAULT 1,
    end_date TEXT,
    fetched_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_prediction_markets_cache_slug
    ON prediction_markets_cache(slug);
CREATE INDEX IF NOT EXISTS idx_prediction_markets_cache_active
    ON prediction_markets_cache(active);

-- Prediction market positions
CREATE TABLE IF NOT EXISTS prediction_positions (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    condition_id TEXT NOT NULL,
    token_id TEXT NOT NULL,
    outcome TEXT NOT NULL,            -- YES or NO
    size REAL NOT NULL DEFAULT 0,
    avg_price REAL NOT NULL DEFAULT 0,
    cost_basis_usd REAL DEFAULT 0,
    current_price REAL DEFAULT 0,
    unrealized_pnl REAL DEFAULT 0,
    status TEXT DEFAULT 'OPEN',       -- OPEN, CLOSED, EXPIRED
    opened_at TEXT NOT NULL,
    closed_at TEXT,
    run_id TEXT,
    order_id TEXT,
    FOREIGN KEY (tenant_id) REFERENCES runs(tenant_id)
);

CREATE INDEX IF NOT EXISTS idx_prediction_positions_tenant
    ON prediction_positions(tenant_id);
CREATE INDEX IF NOT EXISTS idx_prediction_positions_condition
    ON prediction_positions(condition_id);
CREATE INDEX IF NOT EXISTS idx_prediction_positions_status
    ON prediction_positions(status);
