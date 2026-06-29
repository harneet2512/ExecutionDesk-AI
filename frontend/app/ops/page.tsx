'use client';

import { useEffect, useState, useRef } from 'react';
import {
  AreaChart, Area, BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip,
} from 'recharts';
import { getOpsMetrics } from '@/lib/api';
import { fmtNumber } from '@/lib/format';
import { CHART_COLORS, AXIS_STYLE, GRID_STYLE, TOOLTIP_STYLE } from '@/lib/chartTheme';
import PageSkeleton from '@/components/PageSkeleton';
import ChartBox from '@/components/ChartBox';

export default function OpsPage() {
  const [metrics, setMetrics] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    loadMetrics();
    intervalRef.current = setInterval(loadMetrics, 10000);
    return () => { if (intervalRef.current) clearInterval(intervalRef.current); };
  }, []);

  async function loadMetrics() {
    try {
      setMetrics(await getOpsMetrics());
    } catch (error) {
      if (process.env.NODE_ENV === 'development') console.error('Failed to load metrics:', error);
    } finally {
      setLoading(false);
    }
  }

  if (loading || !metrics) return <PageSkeleton title="Operations" />;

  const durAvg = metrics.run_durations?.length > 0
    ? Math.round(metrics.run_durations.reduce((s: number, d: any) => s + (d.duration_ms || 0), 0) / metrics.run_durations.length)
    : null;
  const latAvg = metrics.order_fill_latency_ms?.length > 0
    ? Math.round(metrics.order_fill_latency_ms.reduce((s: number, d: any) => s + (d.latency_ms || 0), 0) / metrics.order_fill_latency_ms.length)
    : null;
  const blockTotal = metrics.policy_blocks?.reduce((s: number, d: any) => s + (d.count || 0), 0) ?? 0;
  const lastEvalScore = metrics.eval_trends?.length > 0
    ? metrics.eval_trends[metrics.eval_trends.length - 1]?.score
    : null;

  return (
    <div className="flex-1 overflow-y-auto p-6 lg:p-8 max-w-7xl mx-auto page-enter">
      {/* Header */}
      <div className="flex items-baseline justify-between mb-6">
        <div>
          <h1 className="text-xl font-semibold theme-text">Operations</h1>
          <p className="text-sm theme-text-muted mt-0.5">
            <span className="live-dot" /> Live · refreshing every 10s
          </p>
        </div>
        <button
          onClick={() => { setLoading(true); loadMetrics(); }}
          className="btn-ghost text-xs px-3 py-1.5 rounded-md border theme-border"
        >
          Refresh
        </button>
      </div>

      {/* Summary metrics */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-6 stagger-enter">
        <div className="metric-card">
          <div className="metric-label">Avg Duration</div>
          <div className="metric-value tabular-nums">{durAvg != null ? `${fmtNumber(durAvg)}ms` : '—'}</div>
        </div>
        <div className="metric-card">
          <div className="metric-label">Fill Latency</div>
          <div className="metric-value tabular-nums">{latAvg != null ? `${fmtNumber(latAvg)}ms` : '—'}</div>
        </div>
        <div className="metric-card">
          <div className="metric-label">Policy Blocks</div>
          <div className="metric-value tabular-nums" style={{ color: blockTotal > 0 ? 'var(--color-loss)' : undefined }}>{fmtNumber(blockTotal)}</div>
        </div>
        <div className="metric-card">
          <div className="metric-label">Latest Eval</div>
          <div className="metric-value tabular-nums">{typeof lastEvalScore === 'number' ? lastEvalScore.toFixed(3) : '—'}</div>
        </div>
      </div>

      {/* Charts - 2x2 grid */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <div className="chart-container">
          <div className="chart-title">Run Duration</div>
          {metrics.run_durations?.length > 0 ? (
            <ChartBox height={220}>
              {(w, h) => (
                <AreaChart width={w} height={h} data={metrics.run_durations}>
                  <defs>
                    <linearGradient id="durGrad" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor={CHART_COLORS.primary} stopOpacity={0.15} />
                      <stop offset="100%" stopColor={CHART_COLORS.primary} stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid {...GRID_STYLE} />
                  <XAxis dataKey="ts" tick={AXIS_STYLE} tickLine={false} axisLine={false} />
                  <YAxis tick={AXIS_STYLE} tickLine={false} axisLine={false} width={48} />
                  <Tooltip {...TOOLTIP_STYLE} />
                  <Area type="monotone" dataKey="duration_ms" stroke={CHART_COLORS.primary} fill="url(#durGrad)" strokeWidth={2} dot={false} name="ms" />
                </AreaChart>
              )}
            </ChartBox>
          ) : (
            <div className="h-[220px] flex items-center justify-center theme-text-muted text-sm">No duration data</div>
          )}
        </div>

        <div className="chart-container">
          <div className="chart-title">Fill Latency</div>
          {metrics.order_fill_latency_ms?.length > 0 ? (
            <ChartBox height={220}>
              {(w, h) => (
                <BarChart width={w} height={h} data={metrics.order_fill_latency_ms}>
                  <CartesianGrid {...GRID_STYLE} />
                  <XAxis dataKey="ts" tick={AXIS_STYLE} tickLine={false} axisLine={false} />
                  <YAxis tick={AXIS_STYLE} tickLine={false} axisLine={false} width={48} />
                  <Tooltip {...TOOLTIP_STYLE} />
                  <Bar dataKey="latency_ms" fill={CHART_COLORS.secondary} name="ms" radius={[2, 2, 0, 0]} />
                </BarChart>
              )}
            </ChartBox>
          ) : (
            <div className="h-[220px] flex items-center justify-center theme-text-muted text-sm">No latency data</div>
          )}
        </div>

        <div className="chart-container">
          <div className="chart-title">Eval Score Trend</div>
          {metrics.eval_trends?.length > 0 ? (
            <ChartBox height={220}>
              {(w, h) => (
                <AreaChart width={w} height={h} data={metrics.eval_trends}>
                  <defs>
                    <linearGradient id="evalGrad" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor={CHART_COLORS.positive} stopOpacity={0.15} />
                      <stop offset="100%" stopColor={CHART_COLORS.positive} stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid {...GRID_STYLE} />
                  <XAxis dataKey="ts" tick={AXIS_STYLE} tickLine={false} axisLine={false} />
                  <YAxis domain={[0, 1]} tick={AXIS_STYLE} tickLine={false} axisLine={false} width={48} />
                  <Tooltip {...TOOLTIP_STYLE} />
                  <Area type="monotone" dataKey="score" stroke={CHART_COLORS.positive} fill="url(#evalGrad)" strokeWidth={2} dot={false} name="Score" />
                </AreaChart>
              )}
            </ChartBox>
          ) : (
            <div className="h-[220px] flex items-center justify-center theme-text-muted text-sm">No eval data</div>
          )}
        </div>

        <div className="chart-container">
          <div className="chart-title">Policy Blocks</div>
          {metrics.policy_blocks?.length > 0 ? (
            <ChartBox height={220}>
              {(w, h) => (
                <BarChart width={w} height={h} data={metrics.policy_blocks}>
                  <CartesianGrid {...GRID_STYLE} />
                  <XAxis dataKey="ts" tick={AXIS_STYLE} tickLine={false} axisLine={false} />
                  <YAxis allowDecimals={false} tick={AXIS_STYLE} tickLine={false} axisLine={false} width={48} />
                  <Tooltip {...TOOLTIP_STYLE} />
                  <Bar dataKey="count" fill={CHART_COLORS.loss} name="Blocks" radius={[2, 2, 0, 0]} />
                </BarChart>
              )}
            </ChartBox>
          ) : (
            <div className="h-[220px] flex items-center justify-center theme-text-muted text-sm">No policy blocks</div>
          )}
        </div>
      </div>
    </div>
  );
}
