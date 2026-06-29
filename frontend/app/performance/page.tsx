'use client';

import { useEffect, useState } from 'react';
import {
  AreaChart, Area, BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
} from 'recharts';
import { getPerformance } from '@/lib/api';
import { fmtCurrency, fmtPercent, fmtNumber, fmtDate, gainLossClass } from '@/lib/format';
import { CHART_COLORS, AXIS_STYLE, GRID_STYLE, TOOLTIP_STYLE } from '@/lib/chartTheme';
import PageSkeleton from '@/components/PageSkeleton';

export default function PerformancePage() {
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [window, setWindow] = useState('7d');

  useEffect(() => { loadData(); }, [window]);

  async function loadData() {
    try {
      setData(await getPerformance(window));
    } catch (error) {
      if (process.env.NODE_ENV === 'development') console.error('Failed to load performance:', error);
    } finally {
      setLoading(false);
    }
  }

  if (loading || !data) return <PageSkeleton title="Performance" />;

  const s = data.summary || {};

  return (
    <div className="p-6 lg:p-8 max-w-7xl mx-auto page-enter">
      {/* Header */}
      <div className="flex items-baseline justify-between mb-6">
        <h1 className="text-xl font-semibold theme-text">Performance</h1>
        <div className="flex gap-1 p-0.5 rounded-lg theme-elevated">
          {['1d', '7d', '30d'].map(w => (
            <button
              key={w}
              onClick={() => setWindow(w)}
              className={`text-xs font-medium px-3 py-1.5 rounded-md transition-colors ${
                window === w
                  ? 'theme-surface shadow-sm theme-text'
                  : 'theme-text-muted hover:theme-text-secondary'
              }`}
            >
              {w}
            </button>
          ))}
        </div>
      </div>

      {/* Metric cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-6 stagger-enter">
        <div className="metric-card">
          <div className="metric-label">Total P&L</div>
          <div className={`metric-value ${gainLossClass(s.total_pnl)}`}>
            {fmtCurrency(s.total_pnl)}
          </div>
        </div>
        <div className="metric-card">
          <div className="metric-label">Returns</div>
          <div className={`metric-value ${gainLossClass(s.total_returns)}`}>
            {fmtPercent(typeof s.total_returns === 'number' ? s.total_returns * 100 : null)}
          </div>
        </div>
        <div className="metric-card">
          <div className="metric-label">Win Rate</div>
          <div className="metric-value">
            {fmtPercent(typeof s.win_rate === 'number' ? s.win_rate * 100 : null)}
          </div>
        </div>
        <div className="metric-card">
          <div className="metric-label">Trades</div>
          <div className="metric-value">{fmtNumber(s.trades_count)}</div>
        </div>
      </div>

      {/* Charts */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 mb-6">
        <div className="chart-container">
          <div className="chart-title">Cumulative P&L</div>
          {data.daily_pnl?.length > 0 ? (
            <ResponsiveContainer width="100%" height={240}>
              <AreaChart data={data.daily_pnl}>
                <defs>
                  <linearGradient id="pnlGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor={CHART_COLORS.primary} stopOpacity={0.15} />
                    <stop offset="100%" stopColor={CHART_COLORS.primary} stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid {...GRID_STYLE} />
                <XAxis dataKey="date" tick={AXIS_STYLE} tickLine={false} axisLine={false} />
                <YAxis tick={AXIS_STYLE} tickLine={false} axisLine={false} width={48} />
                <Tooltip {...TOOLTIP_STYLE} />
                <Area
                  type="monotone"
                  dataKey="pnl"
                  stroke={CHART_COLORS.primary}
                  fill="url(#pnlGrad)"
                  strokeWidth={2}
                  dot={false}
                  name="P&L"
                />
              </AreaChart>
            </ResponsiveContainer>
          ) : (
            <div className="h-[240px] flex items-center justify-center theme-text-muted text-sm">
              No P&L data for this period
            </div>
          )}
        </div>

        <div className="chart-container">
          <div className="chart-title">Daily Returns</div>
          {data.daily_pnl?.length > 0 ? (
            <ResponsiveContainer width="100%" height={240}>
              <BarChart data={data.daily_pnl}>
                <CartesianGrid {...GRID_STYLE} />
                <XAxis dataKey="date" tick={AXIS_STYLE} tickLine={false} axisLine={false} />
                <YAxis tick={AXIS_STYLE} tickLine={false} axisLine={false} width={48} />
                <Tooltip {...TOOLTIP_STYLE} />
                <Bar dataKey="returns" name="Returns" radius={[2, 2, 0, 0]}>
                  {(data.daily_pnl || []).map((_: any, i: number) => {
                    const val = data.daily_pnl[i]?.returns ?? 0;
                    return (
                      <rect key={i} fill={val >= 0 ? CHART_COLORS.gain : CHART_COLORS.loss} />
                    );
                  })}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          ) : (
            <div className="h-[240px] flex items-center justify-center theme-text-muted text-sm">
              No returns data for this period
            </div>
          )}
        </div>
      </div>

      {/* Trades table */}
      {data.trades?.length > 0 && (
        <div className="border theme-border rounded-lg overflow-hidden">
          <div className="px-4 py-3 theme-elevated">
            <span className="section-header">Recent Trades</span>
          </div>
          <table className="data-table">
            <thead>
              <tr>
                <th>Order</th>
                <th>Symbol</th>
                <th>Side</th>
                <th className="num">Notional</th>
                <th>Time</th>
              </tr>
            </thead>
            <tbody>
              {data.trades.slice(0, 20).map((t: any) => (
                <tr key={t.order_id}>
                  <td className="font-mono text-xs">{(t.order_id || '').slice(0, 10)}</td>
                  <td className="font-medium">{t.symbol}</td>
                  <td>
                    <span className={t.side?.toUpperCase() === 'BUY' ? 'gain' : 'loss'}>
                      {(t.side || '').toUpperCase()}
                    </span>
                  </td>
                  <td className="num tabular-nums">{fmtCurrency(t.notional_usd)}</td>
                  <td className="theme-text-muted">{fmtDate(t.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
