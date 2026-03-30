-- Evidence artifacts for execution trace
CREATE TABLE IF NOT EXISTS market_candles_batches (
    batch_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    node_id TEXT,
    symbol TEXT NOT NULL,
    window TEXT NOT NULL,
    candles_json TEXT NOT NULL,
    query_params_json TEXT NOT NULL,
    ts TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (run_id) REFERENCES runs(run_id) ON DELETE CASCADE,
    FOREIGN KEY (node_id) REFERENCES dag_nodes(node_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_candles_batches_run_id ON market_candles_batches(run_id);
CREATE INDEX IF NOT EXISTS idx_candles_batches_symbol ON market_candles_batches(symbol);

-- Rankings table for asset selection evidence
CREATE TABLE IF NOT EXISTS rankings (
    ranking_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    node_id TEXT,
    window TEXT NOT NULL,
    metric TEXT NOT NULL,
    table_json TEXT NOT NULL,  -- JSON array of {symbol, score, ...}
    selected_symbol TEXT NOT NULL,
    selected_score REAL NOT NULL,
    rationale TEXT,
    ts TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (run_id) REFERENCES runs(run_id) ON DELETE CASCADE,
    FOREIGN KEY (node_id) REFERENCES dag_nodes(node_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_rankings_run_id ON rankings(run_id);
CREATE INDEX IF NOT EXISTS idx_rankings_selected_symbol ON rankings(selected_symbol);

-- Intents table (separate from runs for evidence trail)
CREATE TABLE IF NOT EXISTS intents (
    intent_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    command TEXT NOT NULL,
    intent_json TEXT NOT NULL,
    ts TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (run_id) REFERENCES runs(run_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_intents_run_id ON intents(run_id);
