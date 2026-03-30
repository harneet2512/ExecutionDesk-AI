-- Create notification_events table for tracking all notifications
CREATE TABLE IF NOT EXISTS notification_events (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    channel TEXT NOT NULL,  -- 'pushover', 'email', 'webhook', etc.
    status TEXT NOT NULL,   -- 'sent', 'failed'
    action TEXT NOT NULL,   -- 'trade_placed', 'trade_failed', 'pending_confirm'
    run_id TEXT,
    conversation_id TEXT,
    order_id TEXT,
    payload_redacted TEXT,  -- JSON with non-sensitive data
    error TEXT
);

CREATE INDEX IF NOT EXISTS idx_notification_events_run_id ON notification_events(run_id);
CREATE INDEX IF NOT EXISTS idx_notification_events_conversation_id ON notification_events(conversation_id);
CREATE INDEX IF NOT EXISTS idx_notification_events_created_at ON notification_events(created_at);
CREATE INDEX IF NOT EXISTS idx_notification_events_status ON notification_events(status);
