CREATE TABLE IF NOT EXISTS trade_confirmations (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    conversation_id TEXT NOT NULL,
    user_id TEXT NULL,
    proposal_json TEXT NOT NULL,
    mode TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at DATETIME NOT NULL,
    expires_at DATETIME NOT NULL,
    confirmed_at DATETIME NULL
);

CREATE INDEX IF NOT EXISTS idx_trade_confirmations_tenant_conv_status ON trade_confirmations (tenant_id, conversation_id, status);
CREATE INDEX IF NOT EXISTS idx_trade_confirmations_tenant_id ON trade_confirmations (tenant_id, id);
