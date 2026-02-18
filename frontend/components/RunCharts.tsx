'use client';

import { useState, useEffect } from 'react';
import { apiFetchSafe } from '@/lib/api';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, BarChart, Bar, ComposedChart, Area, AreaChart } from 'recharts';

interface RunChartsProps {
  runId: string;
}

export default function RunCharts({ runId }: RunChartsProps) {
  const [portfolioData, setPortfolioData] = useState<any[]>([]);
  const [pnlData, setPnlData] = useState<any>(null);
  const [candlesData, setCandlesData] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function loadChartData() {
      if (!runId) return;
      
      try {
        // Load all data in parallel via apiFetchSafe (retries + headers)
        const [portfolio, pnl, trace] = await Promise.all([
          apiFetchSafe(`/api/v1/portfolio/metrics/value-over-time?run_id=${runId}`),
          apiFetchSafe(`/api/v1/analytics/pnl?run_id=${runId}`),
          apiFetchSafe(`/api/v1/runs/${runId}/trace`),
        ]);

        // Process portfolio data
        if (portfolio && Array.isArray(portfolio)) {
          setPortfolioData(portfolio.map((p: any) => ({
            time: new Date(p.ts).toLocaleTimeString(),
            value: p.total_value_usd,
            cash: p.cash_usd,
          })));
        }

        // Process P&L data
        if (pnl) {
          setPnlData(pnl);
        }

        // Process candles from trace
        if (trace) {
          const candlesBatches = trace.artifacts?.candles_batches || trace.candles_batches || [];
          if (candlesBatches.length > 0) {
            const latestBatch = candlesBatches[0];
            const candles = latestBatch.candles || [];
            if (candles.length > 0 && typeof candles[0] === 'string') {
              // If candles are stored as JSON strings, parse them
              try {
                const parsed = candles.map((c: any) => typeof c === 'string' ? JSON.parse(c) : c);
                setCandlesData(parsed.map((c: any) => ({
                  time: c.time || c.t || new Date(c.start || c.start_time).toLocaleTimeString(),
                  open: c.open || c.o,
                  high: c.high || c.h,
                  low: c.low || c.l,
                  close: c.close || c.c,
                  volume: c.volume || c.v,
                })));
              } catch {
                // If parsing fails, use as-is
                setCandlesData(candles);
              }
            } else {
              setCandlesData(candles.map((c: any) => ({
                time: c.time || c.t || new Date(c.start || c.start_time).toLocaleTimeString(),
                open: c.open || c.o,
                high: c.high || c.h,
                low: c.low || c.l,
                close: c.close || c.c,
                volume: c.volume || c.v,
              })));
            }
          }
        }
      } catch (e: any) {
        console.error('Failed to load chart data:', e);
        setError(e?.message || 'Failed to load chart data');
      } finally {
        setLoading(false);
      }
    }

    loadChartData();
  }, [runId]);

  if (loading) {
    return <div className="text-sm theme-text-secondary p-4">Loading charts...</div>;
  }

  if (error) {
    return (
      <div className="mt-4 p-3 bg-[var(--color-status-error-bg)] border border-[var(--color-status-error)]/20 rounded-lg">
        <p className="text-sm text-[var(--color-status-error)]">Chart data unavailable: {error}</p>
      </div>
    );
  }

  const hasData = portfolioData.length > 0 || pnlData || candlesData.length > 0;

  if (!hasData) {
    return null; // Don't show empty chart section
  }

  return (
    <div className="mt-4 space-y-4 border-t theme-border pt-4">
      {/* Portfolio Value Chart */}
      {portfolioData.length > 0 && (
        <div>
          <h4 className="text-xs font-semibold theme-text-secondary mb-2">Portfolio Value Over Time</h4>
          <ResponsiveContainer width="100%" height={200}>
            <AreaChart data={portfolioData}>
              <defs>
                <linearGradient id="colorValue" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#737373" stopOpacity={0.3}/>
                  <stop offset="95%" stopColor="#737373" stopOpacity={0}/>
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--chart-grid, #334155)" />
              <XAxis dataKey="time" stroke="var(--chart-axis, #94a3b8)" fontSize={12} />
              <YAxis stroke="var(--chart-axis, #94a3b8)" fontSize={12} />
              <Tooltip
                contentStyle={{ backgroundColor: 'var(--chart-tooltip-bg, #1e293b)', border: '1px solid var(--chart-tooltip-border, #334155)', borderRadius: '6px', color: 'var(--chart-tooltip-text, #f1f5f9)' }}
                labelStyle={{ color: 'var(--chart-tooltip-text, #f1f5f9)' }}
              />
              <Area
                type="monotone"
                dataKey="value"
                stroke="#737373"
                fillOpacity={1}
                fill="url(#colorValue)"
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* P&L Chart */}
      {pnlData && pnlData.pnl_over_time && pnlData.pnl_over_time.length > 0 && (
        <div>
          <h4 className="text-xs font-semibold theme-text-secondary mb-2">
            P&L Over Time (Total: ${pnlData.total_pnl?.toFixed(2) || '0.00'})
          </h4>
          <div className="grid grid-cols-3 gap-2 mb-2 text-xs">
            <div className="theme-elevated p-2 rounded">
              <div className="theme-text-secondary">Realized</div>
              <div className="font-semibold theme-text">${pnlData.realized_pnl?.toFixed(2) || '0.00'}</div>
            </div>
            <div className="theme-elevated p-2 rounded">
              <div className="theme-text-secondary">Unrealized</div>
              <div className="font-semibold theme-text">${pnlData.unrealized_pnl?.toFixed(2) || '0.00'}</div>
            </div>
            <div className="theme-elevated p-2 rounded">
              <div className="theme-text-secondary">Total</div>
              <div className="font-semibold theme-text">${pnlData.total_pnl?.toFixed(2) || '0.00'}</div>
            </div>
          </div>
          <ResponsiveContainer width="100%" height={200}>
            <ComposedChart data={pnlData.pnl_over_time}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--chart-grid, #334155)" />
              <XAxis dataKey="ts" stroke="var(--chart-axis, #94a3b8)" fontSize={12} />
              <YAxis stroke="var(--chart-axis, #94a3b8)" fontSize={12} />
              <Tooltip
                contentStyle={{ backgroundColor: 'var(--chart-tooltip-bg, #1e293b)', border: '1px solid var(--chart-tooltip-border, #334155)', borderRadius: '6px', color: 'var(--chart-tooltip-text, #f1f5f9)' }}
                labelStyle={{ color: 'var(--chart-tooltip-text, #f1f5f9)' }}
              />
              <Area
                type="monotone"
                dataKey="realized_pnl"
                stroke="#a3a3a3"
                fill="#a3a3a3"
                fillOpacity={0.2}
                stackId="1"
              />
              <Area
                type="monotone"
                dataKey="unrealized_pnl"
                stroke="#737373"
                fill="#737373"
                fillOpacity={0.2}
                stackId="1"
              />
              <Line
                type="monotone"
                dataKey="total_pnl"
                stroke="#525252"
                strokeWidth={2}
                dot={false}
              />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Market Candles Chart (if available) */}
      {candlesData.length > 0 && (
        <div>
          <h4 className="text-xs font-semibold theme-text-secondary mb-2">Market Candles</h4>
          <ResponsiveContainer width="100%" height={200}>
            <ComposedChart data={candlesData}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--chart-grid, #334155)" />
              <XAxis dataKey="time" stroke="var(--chart-axis, #94a3b8)" fontSize={12} />
              <YAxis stroke="var(--chart-axis, #94a3b8)" fontSize={12} />
              <Tooltip
                contentStyle={{ backgroundColor: 'var(--chart-tooltip-bg, #1e293b)', border: '1px solid var(--chart-tooltip-border, #334155)', borderRadius: '6px', color: 'var(--chart-tooltip-text, #f1f5f9)' }}
                labelStyle={{ color: 'var(--chart-tooltip-text, #f1f5f9)' }}
              />
              <Bar dataKey="high" fill="#a3a3a3" opacity={0.3} />
              <Bar dataKey="low" fill="#737373" opacity={0.3} />
              <Line type="monotone" dataKey="close" stroke="#737373" strokeWidth={2} dot={false} />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
}
