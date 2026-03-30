-- Migration: Add News Pipeline Tables
-- Description: Adds tables for news sources, items, clustering, asset mentions, and run artifacts for evidence/visible reasoning.

-- News Sources
CREATE TABLE IF NOT EXISTS news_sources (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    type TEXT NOT NULL, -- 'rss', 'gdelt', 'cryptopanic'
    url TEXT NOT NULL,
    is_enabled BOOLEAN DEFAULT TRUE,
    weight REAL DEFAULT 1.0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- News Items
CREATE TABLE IF NOT EXISTS news_items (
    id TEXT PRIMARY KEY,
    source_id TEXT,
    published_at TIMESTAMP NOT NULL,
    retrieved_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    url TEXT NOT NULL,
    canonical_url TEXT NOT NULL,
    title TEXT NOT NULL,
    summary TEXT,
    raw_payload_json TEXT, -- Full JSON from provider
    content_hash TEXT NOT NULL, -- For dedup
    lang TEXT DEFAULT 'en',
    domain TEXT,
    FOREIGN KEY(source_id) REFERENCES news_sources(id)
);

CREATE INDEX IF NOT EXISTS idx_news_items_canonical_url ON news_items(canonical_url);
CREATE INDEX IF NOT EXISTS idx_news_items_published_at ON news_items(published_at);
CREATE INDEX IF NOT EXISTS idx_news_items_content_hash ON news_items(content_hash);

-- News Asset Mentions
CREATE TABLE IF NOT EXISTS news_asset_mentions (
    item_id TEXT NOT NULL,
    asset_symbol TEXT NOT NULL,
    confidence REAL NOT NULL,
    method TEXT, -- 'regex', 'dict', 'llm'
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(item_id) REFERENCES news_items(id),
    PRIMARY KEY (item_id, asset_symbol)
);

-- News Clusters
CREATE TABLE IF NOT EXISTS news_clusters (
    id TEXT PRIMARY KEY,
    cluster_hash TEXT NOT NULL,
    first_seen_at TIMESTAMP NOT NULL,
    last_seen_at TIMESTAMP NOT NULL,
    top_item_id TEXT, -- Representative item
    size INTEGER DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS news_cluster_items (
    cluster_id TEXT NOT NULL,
    item_id TEXT NOT NULL,
    FOREIGN KEY(cluster_id) REFERENCES news_clusters(id),
    FOREIGN KEY(item_id) REFERENCES news_items(id),
    PRIMARY KEY (cluster_id, item_id)
);

-- Run News Evidence (Deterministic Replay)
CREATE TABLE IF NOT EXISTS run_news_evidence (
    run_id TEXT NOT NULL,
    item_id TEXT NOT NULL,
    cluster_id TEXT,
    used_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    role TEXT, -- 'context', 'blocker', 'supporting'
    notes TEXT,
    FOREIGN KEY(run_id) REFERENCES runs(run_id),
    FOREIGN KEY(item_id) REFERENCES news_items(id)
);

CREATE INDEX IF NOT EXISTS idx_run_news_evidence_run_id ON run_news_evidence(run_id);

-- Run Artifacts (Visible Reasoning)
CREATE TABLE IF NOT EXISTS run_artifacts (
    run_id TEXT NOT NULL,
    step_name TEXT NOT NULL,
    artifact_type TEXT NOT NULL, -- 'plan', 'financial_brief', 'news_brief', 'decision_record', 'ui_thinking'
    artifact_json TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(run_id) REFERENCES runs(run_id)
);

CREATE INDEX IF NOT EXISTS idx_run_artifacts_run_id ON run_artifacts(run_id);

-- Run Step Summaries
CREATE TABLE IF NOT EXISTS run_step_summaries (
    run_id TEXT NOT NULL,
    step_name TEXT NOT NULL,
    status TEXT NOT NULL,
    started_at TIMESTAMP,
    ended_at TIMESTAMP,
    summary_json TEXT, -- refs to artifacts
    FOREIGN KEY(run_id) REFERENCES runs(run_id),
    PRIMARY KEY (run_id, step_name)
);
