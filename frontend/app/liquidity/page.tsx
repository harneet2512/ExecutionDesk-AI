'use client';

import { useEffect, useState, useRef } from 'react';
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
} from 'recharts';
import { apiFetchSafe } from '@/lib/api';
import { fmtCompact, fmtCurrency, fmtProbability } from '@/lib/format';
import { AXIS_STYLE, GRID_STYLE, TOOLTIP_STYLE, CHART_COLORS } from '@/lib/chartTheme';
import PageSkeleton from '@/components/PageSkeleton';

interface MarketLiquidity {
  question: string;
  condition_id: string;
  yes_price: number;
  volume: number;
  liquidity: number;
  spread?: number;
  bid_depth?: number;
  ask_depth?: number;
}

type SortKey = 'liquidity' | 'volume' | 'spread';

export default function LiquidityPage() {
  const [markets, setMarkets] = useState<MarketLiquidity[]>([]);
  const [loading, setLoading] = useState(true);
  const [sortKey, setSortKey] = useState<SortKey>('liquidity');
  const [sortAsc, setSortAsc] = useState(false);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    loadData();
    intervalRef.current = setInterval(loadData, 30000);
    return () => { if (intervalRef.current) clearInterval(intervalRef.current); };
  }, []);

  async function loadData() {
    try {
      const data = await apiFetchSafe('/api/v1/markets/popular?limit=20');
      if (!data?.markets) return;

      const enriched: MarketLiquidity[] = await Promise.all(
        data.markets.slice(0, 12).map(async (m: any) => {
          const base: MarketLiquidity = {
            question: m.question,
            condition_id: m.condition_id,
            yes_price: m.yes_price,
            volume: m.volume,
            liquidity: m.liquidity || 0,
          };
          try {
            const ob = await apiFetchSafe(`/api/v1/markets/${m.condition_id}/order-book?outcome=YES`);
            if (ob) {
              base.spread = ob.spread;
              base.bid_depth = ob.depth?.bid_depth || 0;
              base.ask_depth = ob.depth?.ask_depth || 0;
            }
          } catch {}
          return base;
        })
      );
      setMarkets(enriched);
    } catch {} finally {
      setLoading(false);
    }
  }

  function toggleSort(key: SortKey) {
    if (sortKey === key) setSortAsc(!sortAsc);
    else { setSortKey(key); setSortAsc(false); }
  }

  const sortIndicator = (key: SortKey) =>
    sortKey === key ? (sortAsc ? ' ▲' : ' ▼') : '';

  const sorted = [...markets].sort((a, b) => {
    const av = a[sortKey] ?? 0;
    const bv = b[sortKey] ?? 0;
    return sortAsc ? (av as number) - (bv as number) : (bv as number) - (av as number);
  });

  const avgSpread = markets.filter(m => m.spread != null).length > 0
    ? markets.filter(m => m.spread != null).reduce((s, m) => s + (m.spread || 0), 0) / markets.filter(m => m.spread != null).length
    : null;
  const totalLiquidity = markets.reduce((s, m) => s + (m.liquidity || 0), 0);
  const totalVolume = markets.reduce((s, m) => s + (m.volume || 0), 0);
  const healthyCount = markets.filter(m => (m.spread ?? 1) < 0.05).length;

  const depthChartData = sorted.slice(0, 10).map(m => ({
    name: m.question.slice(0, 30) + (m.question.length > 30 ? '...' : ''),
    bids: m.bid_depth || 0,
    asks: m.ask_depth || 0,
  }));

  if (loading) return <PageSkeleton title="Liquidity Monitor" />;

  return (
    <div className="flex-1 overflow-y-auto p-6 lg:p-8 max-w-7xl mx-auto page-enter">
      {/* Header */}
      <div className="flex items-baseline justify-between mb-6">
        <div>
          <h1 className="text-xl font-semibold theme-text">Liquidity Monitor</h1>
          <p className="text-sm theme-text-muted mt-0.5">
            <span className="live-dot" /> Live · {markets.length} markets tracked
          </p>
        </div>
        <button
          onClick={() => { setLoading(true); loadData(); }}
          className="btn-ghost text-xs px-3 py-1.5 rounded-md border theme-border"
        >
          Refresh
        </button>
      </div>

      {/* Summary metrics */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-6 stagger-enter">
        <div className="metric-card">
          <div className="metric-label">Total Liquidity</div>
          <div className="metric-value tabular-nums">{fmtCurrency(totalLiquidity)}</div>
        </div>
        <div className="metric-card">
          <div className="metric-label">Total Volume</div>
          <div className="metric-value tabular-nums">{fmtCurrency(totalVolume)}</div>
        </div>
        <div className="metric-card">
          <div className="metric-label">Avg Spread</div>
          <div className="metric-value tabular-nums" style={{
            color: avgSpread != null && avgSpread < 0.03 ? 'var(--color-gain)' : avgSpread != null && avgSpread > 0.08 ? 'var(--color-loss)' : undefined
          }}>
            {avgSpread != null ? `${(avgSpread * 100).toFixed(1)}%` : '—'}
          </div>
        </div>
        <div className="metric-card">
          <div className="metric-label">Healthy Markets</div>
          <div className="metric-value tabular-nums" style={{ color: 'var(--color-gain)' }}>
            {healthyCount}/{markets.length}
          </div>
        </div>
      </div>

      {/* Depth chart */}
      {depthChartData.some(d => d.bids > 0 || d.asks > 0) && (
        <div className="chart-container mb-6">
          <div className="chart-title">Order Book Depth by Market</div>
          <ResponsiveContainer width="100%" height={240}>
            <BarChart data={depthChartData} layout="vertical" margin={{ left: 120 }}>
              <CartesianGrid {...GRID_STYLE} />
              <XAxis type="number" tick={AXIS_STYLE} tickLine={false} axisLine={false} />
              <YAxis type="category" dataKey="name" width={120} tick={{ ...AXIS_STYLE, fontSize: 10 }} tickLine={false} axisLine={false} />
              <Tooltip {...TOOLTIP_STYLE} />
              <Bar dataKey="bids" fill={CHART_COLORS.gain} name="Bid Depth" radius={[0, 3, 3, 0]} />
              <Bar dataKey="asks" fill={CHART_COLORS.loss} name="Ask Depth" radius={[0, 3, 3, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Market liquidity table */}
      <div className="border theme-border rounded-lg overflow-hidden">
        <div className="px-4 py-3 theme-elevated">
          <span className="section-header !mb-0">Market Liquidity</span>
        </div>
        <table className="data-table">
          <thead>
            <tr>
              <th>Market</th>
              <th>Prob</th>
              <th className="sortable num" onClick={() => toggleSort('liquidity')}>Liquidity{sortIndicator('liquidity')}</th>
              <th className="sortable num" onClick={() => toggleSort('volume')}>Volume{sortIndicator('volume')}</th>
              <th className="sortable num" onClick={() => toggleSort('spread')}>Spread{sortIndicator('spread')}</th>
              <th className="num">Bid Depth</th>
              <th className="num">Ask Depth</th>
              <th>Health</th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((m) => {
              const spreadPct = m.spread != null ? m.spread * 100 : null;
              const health = spreadPct == null ? 'unknown' : spreadPct < 3 ? 'healthy' : spreadPct < 8 ? 'fair' : 'poor';
              const healthColor = health === 'healthy' ? 'var(--color-gain)' : health === 'fair' ? '#ea580c' : health === 'poor' ? 'var(--color-loss)' : undefined;
              return (
                <tr key={m.condition_id}>
                  <td className="max-w-[260px]">
                    <span className="text-xs theme-text leading-snug line-clamp-2">{m.question}</span>
                  </td>
                  <td>
                    <span className="text-xs font-semibold tabular-nums" style={{ color: 'var(--color-probability)' }}>
                      {fmtProbability(m.yes_price)}
                    </span>
                  </td>
                  <td className="num tabular-nums">{fmtCompact(m.liquidity)}</td>
                  <td className="num tabular-nums">{fmtCompact(m.volume)}</td>
                  <td className="num tabular-nums" style={{ color: healthColor }}>
                    {spreadPct != null ? `${spreadPct.toFixed(1)}%` : '—'}
                  </td>
                  <td className="num tabular-nums">{m.bid_depth != null ? fmtCompact(m.bid_depth) : '—'}</td>
                  <td className="num tabular-nums">{m.ask_depth != null ? fmtCompact(m.ask_depth) : '—'}</td>
                  <td>
                    <span className="text-[10px] font-semibold uppercase tracking-wider px-1.5 py-0.5 rounded" style={{
                      color: healthColor,
                      backgroundColor: healthColor ? `color-mix(in srgb, ${healthColor} 12%, transparent)` : undefined,
                    }}>
                      {health}
                    </span>
                  </td>
                </tr>
              );
            })}
            {sorted.length === 0 && (
              <tr>
                <td colSpan={8} className="text-center py-10 theme-text-muted">
                  No market data available
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
