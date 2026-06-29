-- Runbook/Playbook system for operational troubleshooting
CREATE TABLE IF NOT EXISTS runbooks (
    runbook_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    slug TEXT NOT NULL UNIQUE,
    category TEXT NOT NULL DEFAULT 'general',
    error_codes TEXT NOT NULL DEFAULT '[]',   -- JSON array of error codes
    symptoms TEXT NOT NULL DEFAULT '',
    diagnosis_steps TEXT NOT NULL DEFAULT '',
    resolution TEXT NOT NULL DEFAULT '',
    prevention TEXT NOT NULL DEFAULT '',
    severity TEXT NOT NULL DEFAULT 'medium',  -- low, medium, high, critical
    times_used INTEGER NOT NULL DEFAULT 0,
    last_used_at TEXT,
    created_by TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_runbooks_slug ON runbooks(slug);
CREATE INDEX IF NOT EXISTS idx_runbooks_category ON runbooks(category);
CREATE INDEX IF NOT EXISTS idx_runbooks_severity ON runbooks(severity);

CREATE TABLE IF NOT EXISTS runbook_usage (
    usage_id TEXT PRIMARY KEY,
    runbook_id TEXT NOT NULL REFERENCES runbooks(runbook_id) ON DELETE CASCADE,
    tenant_id TEXT,
    issue_id TEXT,
    outcome TEXT,
    notes TEXT,
    used_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_runbook_usage_runbook_id ON runbook_usage(runbook_id);
CREATE INDEX IF NOT EXISTS idx_runbook_usage_tenant_id ON runbook_usage(tenant_id);
