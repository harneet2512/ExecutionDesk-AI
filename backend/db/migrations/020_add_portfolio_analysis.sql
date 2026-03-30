-- Migration 020: Add portfolio analysis snapshots table
-- Stores full PortfolioBrief artifacts for portfolio analysis runs

CREATE TABLE IF NOT EXISTS portfolio_analysis_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    mode TEXT NOT NULL, -- LIVE, PAPER, REPLAY
    total_value_usd REAL NOT NULL,
    brief_json TEXT NOT NULL, -- Full PortfolioBrief JSON
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (tenant_id) REFERENCES tenants(tenant_id),
    FOREIGN KEY (run_id) REFERENCES runs(run_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_portfolio_analysis_tenant_id ON portfolio_analysis_snapshots(tenant_id);
CREATE INDEX IF NOT EXISTS idx_portfolio_analysis_run_id ON portfolio_analysis_snapshots(run_id);
CREATE INDEX IF NOT EXISTS idx_portfolio_analysis_created_at ON portfolio_analysis_snapshots(created_at);
