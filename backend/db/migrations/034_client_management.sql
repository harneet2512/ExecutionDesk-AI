-- Client profiles (per-tenant summary, computed periodically)
CREATE TABLE IF NOT EXISTS client_profiles (
    tenant_id TEXT PRIMARY KEY,
    display_name TEXT,
    health_score REAL DEFAULT 0,
    health_classification TEXT DEFAULT 'inactive',
    total_runs INTEGER DEFAULT 0,
    successful_runs INTEGER DEFAULT 0,
    failed_runs INTEGER DEFAULT 0,
    total_orders INTEGER DEFAULT 0,
    total_volume_usd REAL DEFAULT 0,
    last_activity_at TEXT,
    first_seen_at TEXT,
    metadata_json TEXT,
    computed_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Client issues (support tickets / ops notes)
CREATE TABLE IF NOT EXISTS client_issues (
    issue_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT,
    status TEXT NOT NULL DEFAULT 'open',
    priority TEXT NOT NULL DEFAULT 'medium',
    category TEXT DEFAULT 'general',
    assigned_to TEXT,
    created_by TEXT,
    resolved_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_client_issues_tenant ON client_issues(tenant_id);
CREATE INDEX IF NOT EXISTS idx_client_issues_status ON client_issues(status);

-- Issue comments (thread)
CREATE TABLE IF NOT EXISTS client_issue_comments (
    comment_id TEXT PRIMARY KEY,
    issue_id TEXT NOT NULL,
    author TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (issue_id) REFERENCES client_issues(issue_id)
);
CREATE INDEX IF NOT EXISTS idx_client_issue_comments_issue ON client_issue_comments(issue_id);

-- Client alerts
CREATE TABLE IF NOT EXISTS client_alerts (
    alert_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    alert_type TEXT NOT NULL,
    severity TEXT NOT NULL DEFAULT 'warning',
    message TEXT NOT NULL,
    acknowledged INTEGER DEFAULT 0,
    acknowledged_by TEXT,
    acknowledged_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_client_alerts_tenant ON client_alerts(tenant_id);
CREATE INDEX IF NOT EXISTS idx_client_alerts_type ON client_alerts(alert_type);
