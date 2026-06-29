'use client';

import { useEffect, useState, useCallback } from 'react';
import { useRouter } from 'next/navigation';
import PageSkeleton from '@/components/PageSkeleton';
import ProbabilityChart from '@/components/ProbabilityChart';
import { fmtCompact, fmtProbability, fmtCurrency, fmtTimeAgo } from '@/lib/format';
import { apiFetchSafe } from '@/lib/api';

interface Market {
  question: string;
  slug: string;
  condition_id: string;
  yes_price: number;
  no_price: number;
  volume: number;
  liquidity: number;
  active: boolean;
  end_date: string | null;
}

interface MarketDetail {
  condition_id: string;
  question: string;
  outcomes: string[];
  tokens: { token_id: string; outcome: string; price: number }[];
  volume: number;
  liquidity: number;
  end_date: string | null;
}

interface OrderBookData {
  bids: { price: number; size: number }[];
  asks: { price: number; size: number }[];
  spread: number;
  depth: { bid_depth: number; ask_depth: number; total_depth: number };
}

const CATEGORIES = [
  { label: 'All', query: '' },
  { label: 'Politics', query: 'politics' },
  { label: 'Crypto', query: 'crypto bitcoin ethereum' },
  { label: 'Sports', query: 'sports' },
  { label: 'Economics', query: 'economy fed interest rate' },
  { label: 'Tech', query: 'AI technology' },
];

async function fetchMarkets(query: string): Promise<Market[]> {
  const endpoint = query
    ? `/api/v1/markets/search?q=${encodeURIComponent(query)}&limit=20`
    : '/api/v1/markets/popular?limit=20';
  const res = await fetch(endpoint, { headers: { 'X-Dev-Tenant': 't_default' } });
  if (!res.ok) throw new Error(`Failed to fetch markets: ${res.status}`);
  const data = await res.json();
  return data.markets || [];
}

export default function MarketsPage() {
  const router = useRouter();
  const [markets, setMarkets] = useState<Market[]>([]);
  const [loading, setLoading] = useState(true);
  const [searchText, setSearchText] = useState('');
  const [activeCategory, setActiveCategory] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [selectedMarket, setSelectedMarket] = useState<Market | null>(null);
  const [detail, setDetail] = useState<MarketDetail | null>(null);
  const [orderBook, setOrderBook] = useState<OrderBookData | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  const loadMarkets = useCallback(async (query: string) => {
    setLoading(true);
    setError(null);
    try {
      setMarkets(await fetchMarkets(query));
    } catch (err: any) {
      setError(err.message || 'Failed to load markets');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { loadMarkets(''); }, [loadMarkets]);

  async function selectMarket(m: Market) {
    setSelectedMarket(m);
    setDetailLoading(true);
    setDetail(null);
    setOrderBook(null);
    try {
      const [d, ob] = await Promise.allSettled([
        apiFetchSafe(`/api/v1/markets/${m.condition_id}`),
        apiFetchSafe(`/api/v1/markets/${m.condition_id}/order-book?outcome=YES`),
      ]);
      if (d.status === 'fulfilled') setDetail(d.value);
      if (ob.status === 'fulfilled') setOrderBook(ob.value);
    } catch {} finally {
      setDetailLoading(false);
    }
  }

  function handleCategoryClick(query: string) {
    setActiveCategory(query);
    setSearchText('');
    loadMarkets(query);
  }

  function handleSearch(e: React.FormEvent) {
    e.preventDefault();
    setActiveCategory('');
    loadMarkets(searchText);
  }

  if (loading && markets.length === 0) return <PageSkeleton title="Prediction Markets" />;

  return (
    <div className="flex-1 flex flex-col min-h-0 overflow-hidden">
      <div className="flex-1 flex min-h-0">
        {/* Market list panel */}
        <div className={`flex-1 flex flex-col min-h-0 overflow-y-auto p-6 lg:p-8 ${selectedMarket ? 'hidden lg:flex lg:max-w-[55%]' : ''}`}>
          {/* Header */}
          <div className="flex items-baseline justify-between mb-4">
            <h1 className="text-xl font-semibold theme-text">Prediction Markets</h1>
            <span className="text-xs theme-text-muted">{markets.length} markets</span>
          </div>

          {/* Search */}
          <form onSubmit={handleSearch} className="mb-3">
            <input
              type="text"
              value={searchText}
              onChange={(e) => setSearchText(e.target.value)}
              placeholder="Search markets..."
              className="w-full px-3 py-2 text-sm rounded-lg border theme-border theme-surface theme-text focus:outline-none focus:ring-1 focus:ring-[var(--color-focus-ring)]"
            />
          </form>

          {/* Category pills */}
          <div className="flex gap-1.5 mb-4 flex-wrap">
            {CATEGORIES.map((cat) => (
              <button
                key={cat.label}
                onClick={() => handleCategoryClick(cat.query)}
                className={`px-2.5 py-1 text-xs rounded-md transition-colors ${
                  activeCategory === cat.query
                    ? 'btn-primary'
                    : 'btn-ghost border theme-border'
                }`}
              >
                {cat.label}
              </button>
            ))}
          </div>

          {error && (
            <div className="px-3 py-2 mb-3 rounded-lg text-xs badge-error">{error}</div>
          )}

          {/* Market list */}
          {markets.length === 0 && !loading ? (
            <div className="text-center py-16 theme-text-muted text-sm">
              No markets found. Try a different search.
            </div>
          ) : (
            <div className="space-y-1.5">
              {markets.map((m) => (
                <button
                  key={m.condition_id || m.slug}
                  onClick={() => selectMarket(m)}
                  className={`w-full text-left px-4 py-3 rounded-lg border transition-all ${
                    selectedMarket?.condition_id === m.condition_id
                      ? 'border-[var(--color-border-strong)] theme-surface shadow-sm'
                      : 'border-transparent hover:theme-surface hover:border-[var(--color-border)]'
                  }`}
                >
                  <p className="text-sm theme-text leading-snug mb-2 line-clamp-2">{m.question}</p>
                  <div className="flex items-center gap-3">
                    <div className="flex-1">
                      <div className="prob-bar">
                        <div className="prob-bar-fill" style={{ width: `${(m.yes_price || 0) * 100}%` }} />
                      </div>
                    </div>
                    <div className="flex items-center gap-2">
                      <span className="text-xs font-semibold tabular-nums gain">{fmtProbability(m.yes_price)}</span>
                      <span className="text-[10px] theme-text-muted">YES</span>
                    </div>
                    <span className="text-[10px] theme-text-muted tabular-nums">{fmtCompact(m.volume)} vol</span>
                  </div>
                </button>
              ))}
            </div>
          )}
        </div>

        {/* Detail panel */}
        {selectedMarket && (
          <div className="flex-1 lg:max-w-[45%] border-l theme-border overflow-y-auto p-6 lg:p-8 theme-surface">
            {/* Back button on mobile */}
            <button
              onClick={() => setSelectedMarket(null)}
              className="lg:hidden text-xs btn-ghost mb-4 px-2 py-1 rounded"
            >
              ← Back to markets
            </button>

            {/* Market header */}
            <h2 className="text-lg font-semibold theme-text mb-2 leading-snug">{selectedMarket.question}</h2>

            {/* Probability display */}
            <div className="grid grid-cols-2 gap-3 mb-6">
              <div className="metric-card !p-3">
                <div className="metric-label">Yes</div>
                <div className="text-2xl font-bold tabular-nums gain">{fmtProbability(selectedMarket.yes_price)}</div>
                <div className="text-[10px] theme-text-muted">${fmtCompact(selectedMarket.yes_price)} per share</div>
              </div>
              <div className="metric-card !p-3">
                <div className="metric-label">No</div>
                <div className="text-2xl font-bold tabular-nums loss">{fmtProbability(selectedMarket.no_price)}</div>
                <div className="text-[10px] theme-text-muted">${fmtCompact(selectedMarket.no_price)} per share</div>
              </div>
            </div>

            {/* Market stats */}
            <div className="grid grid-cols-3 gap-3 mb-6">
              <div className="metric-card !p-3">
                <div className="metric-label">Volume</div>
                <div className="text-sm font-semibold tabular-nums theme-text">{fmtCurrency(selectedMarket.volume)}</div>
              </div>
              <div className="metric-card !p-3">
                <div className="metric-label">Liquidity</div>
                <div className="text-sm font-semibold tabular-nums theme-text">{fmtCurrency(selectedMarket.liquidity)}</div>
              </div>
              <div className="metric-card !p-3">
                <div className="metric-label">Ends</div>
                <div className="text-sm font-semibold theme-text">
                  {selectedMarket.end_date ? fmtTimeAgo(selectedMarket.end_date) : '—'}
                </div>
              </div>
            </div>

            {/* Probability Chart */}
            <div className="mb-6">
              <ProbabilityChart conditionId={selectedMarket.condition_id} />
            </div>

            {/* Order book */}
            <div className="mb-6">
              <div className="section-header">Order Book (YES)</div>
              {detailLoading ? (
                <div className="h-48 flex items-center justify-center theme-text-muted text-xs">Loading...</div>
              ) : orderBook && (orderBook.bids.length > 0 || orderBook.asks.length > 0) ? (
                <div className="border theme-border rounded-lg overflow-hidden">
                  {/* Spread indicator */}
                  <div className="px-3 py-1.5 theme-elevated flex items-center justify-between text-[10px]">
                    <span className="theme-text-muted">Spread</span>
                    <span className="tabular-nums font-semibold theme-text">{(orderBook.spread * 100).toFixed(1)}%</span>
                  </div>
                  <div className="grid grid-cols-2 divide-x divide-[var(--color-border)]">
                    {/* Bids */}
                    <div>
                      <div className="px-3 py-1 text-[10px] font-semibold uppercase tracking-wider theme-text-muted border-b theme-border">
                        Bids
                      </div>
                      {orderBook.bids.slice(0, 8).map((b, i) => {
                        const maxSize = Math.max(...orderBook.bids.slice(0, 8).map(x => x.size));
                        const pct = maxSize > 0 ? (b.size / maxSize) * 100 : 0;
                        return (
                          <div key={i} className="relative px-3 py-1 flex justify-between text-xs">
                            <div className="absolute inset-y-0 left-0 bg-[var(--color-gain-bg)]" style={{ width: `${pct}%` }} />
                            <span className="relative tabular-nums gain">{(b.price * 100).toFixed(1)}¢</span>
                            <span className="relative tabular-nums theme-text-muted">{b.size.toFixed(0)}</span>
                          </div>
                        );
                      })}
                    </div>
                    {/* Asks */}
                    <div>
                      <div className="px-3 py-1 text-[10px] font-semibold uppercase tracking-wider theme-text-muted border-b theme-border">
                        Asks
                      </div>
                      {orderBook.asks.slice(0, 8).map((a, i) => {
                        const maxSize = Math.max(...orderBook.asks.slice(0, 8).map(x => x.size));
                        const pct = maxSize > 0 ? (a.size / maxSize) * 100 : 0;
                        return (
                          <div key={i} className="relative px-3 py-1 flex justify-between text-xs">
                            <div className="absolute inset-y-0 right-0 bg-[var(--color-loss-bg)]" style={{ width: `${pct}%` }} />
                            <span className="relative tabular-nums loss">{(a.price * 100).toFixed(1)}¢</span>
                            <span className="relative tabular-nums theme-text-muted">{a.size.toFixed(0)}</span>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                  {/* Depth summary */}
                  <div className="px-3 py-1.5 theme-elevated flex items-center justify-between text-[10px] theme-text-muted">
                    <span>Bid depth: {fmtCompact(orderBook.depth.bid_depth)}</span>
                    <span>Ask depth: {fmtCompact(orderBook.depth.ask_depth)}</span>
                  </div>
                </div>
              ) : (
                <div className="h-32 flex items-center justify-center theme-text-muted text-xs border theme-border rounded-lg">
                  No order book data available
                </div>
              )}
            </div>

            {/* Outcomes breakdown */}
            {detail && detail.tokens?.length > 0 && (
              <div className="mb-6">
                <div className="section-header">Outcomes</div>
                <div className="space-y-2">
                  {detail.tokens.map((t, i) => (
                    <div key={i} className="flex items-center gap-3 px-3 py-2 border theme-border rounded-lg">
                      <span className="text-sm font-medium theme-text flex-1">{t.outcome}</span>
                      <span className="text-sm font-semibold tabular-nums" style={{
                        color: t.outcome === 'Yes' ? 'var(--color-gain)' : 'var(--color-loss)'
                      }}>
                        {fmtProbability(t.price)}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Trade action */}
            <div className="flex gap-2">
              <button
                onClick={() => router.push(`/chat?suggestion=${encodeURIComponent(`Buy YES on: ${selectedMarket.question}`)}`)}
                className="flex-1 py-2.5 text-sm font-medium rounded-lg text-white transition-colors"
                style={{ backgroundColor: 'var(--color-gain)' }}
              >
                Buy YES
              </button>
              <button
                onClick={() => router.push(`/chat?suggestion=${encodeURIComponent(`Buy NO on: ${selectedMarket.question}`)}`)}
                className="flex-1 py-2.5 text-sm font-medium rounded-lg text-white transition-colors"
                style={{ backgroundColor: 'var(--color-loss)' }}
              >
                Buy NO
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
