-- Market data storage tables
CREATE TABLE IF NOT EXISTS market_candles (
    id TEXT PRIMARY KEY,
    symbol TEXT NOT NULL,
    interval TEXT NOT NULL,  -- 1h, 24h, etc.
    start_time TEXT NOT NULL,
    end_time TEXT NOT NULL,
    open REAL NOT NULL,
    high REAL NOT NULL,
    low REAL NOT NULL,
    close REAL NOT NULL,
    volume REAL,
    ts TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(symbol, interval, start_time)
);

CREATE INDEX IF NOT EXISTS idx_market_candles_symbol ON market_candles(symbol);
CREATE INDEX IF NOT EXISTS idx_market_candles_symbol_interval ON market_candles(symbol, interval);
CREATE INDEX IF NOT EXISTS idx_market_candles_start_time ON market_candles(start_time);

-- Store reference to candles used in a strategy execution
CREATE TABLE IF NOT EXISTS strategy_candles (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    node_id TEXT,
    symbol TEXT NOT NULL,
    interval TEXT NOT NULL,
    candle_ids TEXT NOT NULL,  -- JSON array of candle IDs
    ts TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (run_id) REFERENCES runs(run_id) ON DELETE CASCADE,
    FOREIGN KEY (node_id) REFERENCES dag_nodes(node_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_strategy_candles_run_id ON strategy_candles(run_id);
CREATE INDEX IF NOT EXISTS idx_strategy_candles_symbol ON strategy_candles(symbol);
