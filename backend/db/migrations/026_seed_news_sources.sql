-- Seed default RSS news sources for crypto headlines.
-- These are free, public RSS feeds that require no API keys.
-- Idempotent: uses INSERT OR IGNORE so re-running is safe.

INSERT OR IGNORE INTO news_sources (id, name, type, url, is_enabled, created_at)
VALUES
  ('src_coindesk', 'CoinDesk', 'rss', 'https://www.coindesk.com/arc/outboundfeeds/rss/', 1, datetime('now')),
  ('src_cointelegraph', 'CoinTelegraph', 'rss', 'https://cointelegraph.com/rss', 1, datetime('now')),
  ('src_bitcoinmag', 'Bitcoin Magazine', 'rss', 'https://bitcoinmagazine.com/feed', 1, datetime('now')),
  ('src_decrypt', 'Decrypt', 'rss', 'https://decrypt.co/feed', 1, datetime('now')),
  ('src_gdelt', 'GDELT', 'gdelt', 'https://api.gdeltproject.org/api/v2/doc/doc', 1, datetime('now'));
