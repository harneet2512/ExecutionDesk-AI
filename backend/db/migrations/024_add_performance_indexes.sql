-- Performance indexes for frequently-queried columns
CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);
CREATE INDEX IF NOT EXISTS idx_orders_created_at ON orders(created_at);
CREATE INDEX IF NOT EXISTS idx_dag_nodes_status ON dag_nodes(status);
CREATE INDEX IF NOT EXISTS idx_run_events_run_id_ts ON run_events(run_id, ts);
CREATE INDEX IF NOT EXISTS idx_audit_logs_tenant_action_date ON audit_logs(tenant_id, action, created_at);
