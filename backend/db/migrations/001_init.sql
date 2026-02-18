-- Minimal enterprise schema

-- Tenants
CREATE TABLE IF NOT EXISTS tenants (
    tenant_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    kill_switch_enabled INTEGER NOT NULL DEFAULT 0
);

-- Users
CREATE TABLE IF NOT EXISTS users (
    user_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    email TEXT NOT NULL,
    role TEXT NOT NULL,
    password_hash TEXT,
    FOREIGN KEY (tenant_id) REFERENCES tenants(tenant_id),
    UNIQUE(tenant_id, email)
);

-- Runs
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    status TEXT NOT NULL,
    execution_mode TEXT NOT NULL DEFAULT 'PAPER',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    started_at TEXT,
    completed_at TEXT,
    trade_proposal_json TEXT,
    trace_id TEXT,
    FOREIGN KEY (tenant_id) REFERENCES tenants(tenant_id)
);

CREATE INDEX IF NOT EXISTS idx_runs_tenant_id ON runs(tenant_id);
CREATE INDEX IF NOT EXISTS idx_runs_status ON runs(status);

-- Run Events
CREATE TABLE IF NOT EXISTS run_events (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    ts TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (run_id) REFERENCES runs(run_id) ON DELETE CASCADE,
    FOREIGN KEY (tenant_id) REFERENCES tenants(tenant_id)
);

CREATE INDEX IF NOT EXISTS idx_run_events_run_id ON run_events(run_id);
CREATE INDEX IF NOT EXISTS idx_run_events_ts ON run_events(ts);
CREATE INDEX IF NOT EXISTS idx_run_events_tenant_id ON run_events(tenant_id);

-- DAG Nodes
CREATE TABLE IF NOT EXISTS dag_nodes (
    node_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    name TEXT NOT NULL,
    node_type TEXT NOT NULL,
    status TEXT NOT NULL,
    started_at TEXT,
    completed_at TEXT,
    inputs_json TEXT,
    outputs_json TEXT,
    error_json TEXT,
    FOREIGN KEY (run_id) REFERENCES runs(run_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_dag_nodes_run_id ON dag_nodes(run_id);

-- Tool Calls
CREATE TABLE IF NOT EXISTS tool_calls (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    node_id TEXT,
    tool_name TEXT NOT NULL,
    mcp_server TEXT NOT NULL,
    request_json TEXT NOT NULL,
    response_json TEXT,
    status TEXT NOT NULL,
    ts TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (run_id) REFERENCES runs(run_id) ON DELETE CASCADE,
    FOREIGN KEY (node_id) REFERENCES dag_nodes(node_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_tool_calls_run_id ON tool_calls(run_id);
CREATE INDEX IF NOT EXISTS idx_tool_calls_node_id ON tool_calls(node_id);

-- Retrievals
CREATE TABLE IF NOT EXISTS retrievals (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    node_id TEXT,
    query TEXT NOT NULL,
    results_json TEXT NOT NULL,
    ts TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (run_id) REFERENCES runs(run_id) ON DELETE CASCADE,
    FOREIGN KEY (node_id) REFERENCES dag_nodes(node_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_retrievals_run_id ON retrievals(run_id);

-- Policies
CREATE TABLE IF NOT EXISTS policies (
    policy_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    name TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    policy_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (tenant_id) REFERENCES tenants(tenant_id),
    UNIQUE(tenant_id, name, version)
);

CREATE INDEX IF NOT EXISTS idx_policies_tenant_id ON policies(tenant_id);

-- Policy Events
CREATE TABLE IF NOT EXISTS policy_events (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    node_id TEXT,
    policy_id TEXT,
    decision TEXT NOT NULL,
    reasons_json TEXT NOT NULL,
    ts TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (run_id) REFERENCES runs(run_id) ON DELETE CASCADE,
    FOREIGN KEY (policy_id) REFERENCES policies(policy_id)
);

CREATE INDEX IF NOT EXISTS idx_policy_events_run_id ON policy_events(run_id);

-- Approvals
CREATE TABLE IF NOT EXISTS approvals (
    approval_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    decided_at TEXT,
    decided_by TEXT,
    comment TEXT,
    FOREIGN KEY (run_id) REFERENCES runs(run_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_approvals_run_id ON approvals(run_id);
CREATE INDEX IF NOT EXISTS idx_approvals_status ON approvals(status);

-- Orders
CREATE TABLE IF NOT EXISTS orders (
    order_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    provider TEXT NOT NULL,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    order_type TEXT NOT NULL,
    qty REAL,
    notional_usd REAL NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (run_id) REFERENCES runs(run_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_orders_run_id ON orders(run_id);
CREATE INDEX IF NOT EXISTS idx_orders_tenant_id ON orders(tenant_id);

-- Order Events
CREATE TABLE IF NOT EXISTS order_events (
    id TEXT PRIMARY KEY,
    order_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    ts TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (order_id) REFERENCES orders(order_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_order_events_order_id ON order_events(order_id);

-- Portfolio Snapshots
CREATE TABLE IF NOT EXISTS portfolio_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    run_id TEXT,
    tenant_id TEXT NOT NULL,
    balances_json TEXT NOT NULL,
    positions_json TEXT NOT NULL,
    total_value_usd REAL NOT NULL,
    ts TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (run_id) REFERENCES runs(run_id) ON DELETE SET NULL,
    FOREIGN KEY (tenant_id) REFERENCES tenants(tenant_id)
);

CREATE INDEX IF NOT EXISTS idx_portfolio_snapshots_run_id ON portfolio_snapshots(run_id);
CREATE INDEX IF NOT EXISTS idx_portfolio_snapshots_tenant_id ON portfolio_snapshots(tenant_id);
CREATE INDEX IF NOT EXISTS idx_portfolio_snapshots_ts ON portfolio_snapshots(ts);

-- Eval Results
CREATE TABLE IF NOT EXISTS eval_results (
    eval_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    eval_name TEXT NOT NULL,
    score REAL NOT NULL,
    reasons_json TEXT NOT NULL,
    ts TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (run_id) REFERENCES runs(run_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_eval_results_run_id ON eval_results(run_id);
CREATE INDEX IF NOT EXISTS idx_eval_results_tenant_id ON eval_results(tenant_id);

-- Initial data
INSERT OR IGNORE INTO tenants (tenant_id, name, kill_switch_enabled)
VALUES ('t_default', 'Default Tenant', 0);
