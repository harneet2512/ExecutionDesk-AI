'use client';

import React, { useState, useEffect, useCallback } from 'react';
import { apiFetchSafe } from '@/lib/api';
import {
  AreaChart, Area, ComposedChart, Line, Bar,
  XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer,
  ReferenceDot,
} from 'recharts';

interface RunChartsProps {
  runId: string;
}

interface TradeMarker {
  ts: string;
  side: string;
  notional_usd: number;
  symbol: string;
  filled_qty?: number;
  avg_fill_price?: number;
  status?: string;
}

const fmtCurrency = (v: unknown): string => {
  if (typeof v !== 'number' || !isFinite(v)) return '\u2014';
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(v);
};

const fmtTs = (v: unknown): string => {
  if (!v) return '\u2014';
  try {
    return new Intl.DateTimeFormat('en-US', {
      month: 'short', day: 'numeric',
      hour: '2-digit', minute: '2-digit',
    }).format(new Date(String(v)));
  } catch { return String(v); }
};

const tooltipStyle = {
  backgroundColor: 'var(--chart-tooltip-bg, #1e293b)',
  border: '1px solid var(--chart-tooltip-border, #334155)',
  borderRadius: '6px',
  color: 'var(--chart-tooltip-text, #f1f5f9)',
};

// ---------------------------------------------------------------------------
// Rich tooltip that shows trade marker details when hovering near a marker
// ---------------------------------------------------------------------------
function PortfolioTooltip({ active, payload, label, markers }: any) {
  if (!active || !payload?.length) return null;
  const value = payload.find((p: any) => p.dataKey === 'value')?.value;
  const cash = payload.find((p: any) => p.dataKey === 'cash')?.value;

  // Find any marker within 60s of this point
  const labelTs = label ? new Date(label).getTime() : 0;
  const nearMarker = markers.find((m: TradeMarker) => {
    const diff = Math.abs(new Date(m.ts).getTime() - labelTs);
    return diff < 60_000;
  });

  return (
    <div style={{ ...tooltipStyle, padding: '10px 14px', fontSize: 12, minWidth: 180 }}>
      <p style={{ marginBottom: 6, fontWeight: 600, color: 'var(--chart-tooltip-text, #f1f5f9)' }}>{fmtTs(label)}</p>
      {typeof value === 'number' && isFinite(value) && (
        <p style={{ margin: '2px 0', color: '#a3a3a3' }}>Portfolio: <strong style={{ color: '#f1f5f9' }}>{fmtCurrency(value)}</strong></p>
      )}
      {typeof cash === 'number' && isFinite(cash) && (
        <p style={{ margin: '2px 0', color: '#737373' }}>Cash: {fmtCurrency(cash)}</p>
      )}
      {nearMarker && (
        <div style={{ marginTop: 8, paddingTop: 6, borderTop: '1px solid #334155' }}>
          <p style={{ margin: '2px 0', fontWeight: 600, color: nearMarker.side === 'BUY' ? '#22c55e' : '#ef4444' }}>
            {nearMarker.side} {nearMarker.symbol}
          </p>
          <p style={{ margin: '2px 0', color: '#94a3b8' }}>Notional: {fmtCurrency(nearMarker.notional_usd)}</p>
          {nearMarker.filled_qty != null && nearMarker.filled_qty > 0 && (
            <p style={{ margin: '2px 0', color: '#94a3b8' }}>
              Filled: {nearMarker.filled_qty.toFixed(8)} @ {fmtCurrency(nearMarker.avg_fill_price)}
            </p>
          )}
          {nearMarker.status && (
            <p style={{ margin: '2px 0', color: nearMarker.status === 'FILLED' ? '#22c55e' : '#f59e0b' }}>
              Status: {nearMarker.status}
            </p>
          )}
        </div>
      )}
    </div>
  );
}

class ChartErrorBoundary extends React.Component<
  { children: React.ReactNode },
  { error: Error | null }
> {
  state = { error: null as Error | null };
  static getDerivedStateFromError(error: Error) { return { error }; }
  render() {
    if (this.state.error) {
      return (
        <div className="flex items-center justify-center theme-text-secondary" style={{ minHeight: 220 }}>
          <p className="text-sm">Chart unavailable: rendering error — {this.state.error.message}</p>
        </div>
      );
    }
    return this.props.children;
  }
}

function EmptyState({ title, message }: { title: string; message: string }) {
  return (
    <div className="flex items-center justify-center theme-text-secondary" style={{ minHeight: 220 }}>
      <div className="text-center px-4">
        <p className="text-sm font-medium mb-1">{title}</p>
        <p className="text-xs opacity-75">{message}</p>
      </div>
    </div>
  );
}

// BUY/SELL arrow shape renderer
function TradeArrow({ cx, cy, side, status }: { cx?: number; cy?: number; side: string; status?: string }) {
  if (!cx || !cy || !isFinite(cx) || !isFinite(cy)) return null;
  const isBuy = side === 'BUY';
  const color = isBuy ? '#22c55e' : '#ef4444';
  const stroke = isBuy ? '#16a34a' : '#dc2626';
  // Dim markers for orders that are not yet filled
  const opacity = status && !['FILLED', 'PARTIALLY_FILLED'].includes(status.toUpperCase()) ? 0.5 : 1;
  // BUY: triangle pointing up; SELL: triangle pointing down
  const d = isBuy
    ? `M${cx},${cy - 9} L${cx + 7},${cy + 5} L${cx - 7},${cy + 5} Z`
    : `M${cx},${cy + 9} L${cx + 7},${cy - 5} L${cx - 7},${cy - 5} Z`;
  return <path d={d} fill={color} stroke={stroke} strokeWidth={1.5} opacity={opacity} />;
}

export default function RunCharts({ runId }: RunChartsProps) {
  const [portfolioData, setPortfolioData] = useState<any[]>([]);
  const [tradeMarkers, setTradeMarkers] = useState<TradeMarker[]>([]);
  const [pnlSummary, setPnlSummary] = useState<{ realized: number; unrealized: number; total: number } | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [hiddenSeries, setHiddenSeries] = useState<Set<string>>(new Set());

  const toggleSeries = useCallback((e: any) => {
    const key = e?.dataKey;
    if (!key) return;
    setHiddenSeries(prev => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key); else next.add(key);
      return next;
    });
  }, []);

  useEffect(() => {
    async function loadData() {
      if (!runId) return;
      try {
        const [portfolio, pnl, trace] = await Promise.all([
          apiFetchSafe(`/api/v1/portfolio/metrics/value-over-time?run_id=${runId}`),
          apiFetchSafe(`/api/v1/analytics/pnl?run_id=${runId}`),
          apiFetchSafe(`/api/v1/runs/${runId}/trace`),
        ]);

        // Portfolio series
        if (portfolio && Array.isArray(portfolio)) {
          setPortfolioData(portfolio.map((p: any) => ({
            time: p.ts || '',
            value: typeof p.total_value_usd === 'number' ? p.total_value_usd : null,
            cash: typeof p.cash_usd === 'number' ? p.cash_usd : null,
          })).filter((p: any) => p.time));
        }

        // P&L summary numbers (don't need time series)
        if (pnl && typeof pnl.total_pnl === 'number') {
          setPnlSummary({
            realized: typeof pnl.realized_pnl === 'number' ? pnl.realized_pnl : 0,
            unrealized: typeof pnl.unrealized_pnl === 'number' ? pnl.unrealized_pnl : 0,
            total: pnl.total_pnl,
          });
        }

        // Trade markers from orders in trace
        if (trace) {
          const orders: any[] = trace.orders || [];
          if (orders.length > 0) {
            setTradeMarkers(orders
              .filter((o: any) => o.created_at)
              .map((o: any) => ({
                ts: o.created_at,
                side: (o.side || '').toUpperCase(),
                notional_usd: o.notional_usd || 0,
                symbol: o.symbol || '',
                filled_qty: o.filled_qty ?? undefined,
                avg_fill_price: o.avg_fill_price ?? undefined,
                status: o.status || undefined,
              })));
          }
        }
      } catch (e: any) {
        setError(e?.message || 'Failed to load chart data');
      } finally {
        setLoading(false);
      }
    }
    loadData();
  }, [runId]);

  if (loading) {
    return <div className="text-sm theme-text-secondary p-4 animate-pulse">Loading chart...</div>;
  }

  if (error) {
    return (
      <div className="mt-4 p-3 bg-[var(--color-status-error-bg)] border border-[var(--color-status-error)]/20 rounded-lg">
        <p className="text-sm text-[var(--color-status-error)]">Chart data unavailable: {error}</p>
      </div>
    );
  }

  // Determine data coverage info
  const firstTs = portfolioData[0]?.time;
  const lastTs = portfolioData[portfolioData.length - 1]?.time;

  return (
    <div className="mt-4 space-y-3 border-t theme-border pt-4">
      {/* ------------------------------------------------------------------ */}
      {/* ONE primary chart: Portfolio Value & Trade Markers                  */}
      {/* ------------------------------------------------------------------ */}
      <div className="p-4 theme-surface border theme-border rounded">
        <div className="flex items-start justify-between mb-1">
          <div>
            <h4 className="text-sm font-semibold theme-text">Portfolio Value &amp; Trade Events</h4>
            <p className="text-xs theme-text-secondary mt-0.5">
              {portfolioData.length === 0
                ? 'No data \u2014 run a trade to generate snapshots'
                : portfolioData.length === 1
                  ? `1 snapshot recorded \u2014 need \u22652 to render chart`
                  : `${portfolioData.length} snapshots \u00b7 ${fmtTs(firstTs)} \u2013 ${fmtTs(lastTs)}`}
              {tradeMarkers.length > 0 && ` \u00b7 ${tradeMarkers.length} trade marker${tradeMarkers.length > 1 ? 's' : ''}`}
            </p>
          </div>
          {/* P&L summary pills */}
          {pnlSummary && (
            <div className="flex gap-2 text-xs flex-shrink-0 ml-4">
              <div className="theme-elevated px-2 py-1 rounded">
                <span className="theme-text-secondary">Realized </span>
                <span className="font-semibold theme-text">{fmtCurrency(pnlSummary.realized)}</span>
              </div>
              <div className="theme-elevated px-2 py-1 rounded">
                <span className="theme-text-secondary">Total P&L </span>
                <span className={`font-semibold ${pnlSummary.total >= 0 ? 'text-[var(--color-status-success)]' : 'text-[var(--color-status-error)]'}`}>
                  {fmtCurrency(pnlSummary.total)}
                </span>
              </div>
            </div>
          )}
        </div>

        <div style={{ minHeight: 240 }}>
          {portfolioData.length >= 2 ? (
            <ChartErrorBoundary>
              <ResponsiveContainer width="100%" height={280}>
                <AreaChart data={portfolioData} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
                  <defs>
                    <linearGradient id="rcGradPortfolio" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="#6366f1" stopOpacity={0.25} />
                      <stop offset="95%" stopColor="#6366f1" stopOpacity={0} />
                    </linearGradient>
                    <linearGradient id="rcGradCash" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="#94a3b8" stopOpacity={0.18} />
                      <stop offset="95%" stopColor="#94a3b8" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="var(--chart-grid, #334155)" />
                  <XAxis
                    dataKey="time"
                    stroke="var(--chart-axis, #94a3b8)"
                    fontSize={11}
                    tickLine={false}
                    tickFormatter={(v) => {
                      try { return new Date(v).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }); }
                      catch { return String(v); }
                    }}
                  />
                  <YAxis
                    stroke="var(--chart-axis, #94a3b8)"
                    fontSize={11}
                    tickLine={false}
                    width={72}
                    tickFormatter={(v) => typeof v === 'number' ? `$${v >= 1000 ? `${(v / 1000).toFixed(1)}k` : v.toFixed(0)}` : String(v)}
                  />
                  <Tooltip
                    content={<PortfolioTooltip markers={tradeMarkers} />}
                    cursor={{ stroke: 'var(--chart-axis, #94a3b8)', strokeWidth: 1, strokeDasharray: '4 2' }}
                  />
                  <Legend onClick={toggleSeries} wrapperStyle={{ fontSize: 11 }} />
                  <Area
                    type="monotone" dataKey="value"
                    stroke="#6366f1" strokeWidth={2}
                    fillOpacity={1} fill="url(#rcGradPortfolio)"
                    name="Total Value"
                    dot={false}
                    hide={hiddenSeries.has('value')}
                    connectNulls
                  />
                  <Area
                    type="monotone" dataKey="cash"
                    stroke="#94a3b8" strokeWidth={1.5}
                    fillOpacity={1} fill="url(#rcGradCash)"
                    name="Cash"
                    dot={false}
                    hide={hiddenSeries.has('cash')}
                    connectNulls
                  />
                  {/* BUY / SELL markers at exact timestamps */}
                  {tradeMarkers.map((m, i) => {
                    const closest = portfolioData.reduce<{ time: string; value: number; diff: number }>(
                      (best, p) => {
                        const diff = Math.abs(new Date(p.time).getTime() - new Date(m.ts).getTime());
                        return diff < best.diff ? { time: p.time, value: p.value, diff } : best;
                      },
                      { time: '', value: 0, diff: Infinity }
                    );
                    if (!closest.time) return null;
                    return (
                      <ReferenceDot
                        key={`marker-${i}`}
                        x={closest.time}
                        y={closest.value}
                        r={8}
                        fill="transparent"
                        stroke="transparent"
                        shape={(props: any) => <TradeArrow cx={props.cx} cy={props.cy} side={m.side} status={m.status} />}
                      />
                    );
                  })}
                </AreaChart>
              </ResponsiveContainer>
            </ChartErrorBoundary>
          ) : (
            <EmptyState
              title={
                portfolioData.length === 1
                  ? 'Chart unavailable: insufficient data points (\u22652 required, got 1)'
                  : 'Chart unavailable: no portfolio snapshots recorded'
              }
              message={
                portfolioData.length === 1
                  ? 'A second snapshot will be recorded after order execution completes.'
                  : 'Portfolio snapshots are emitted during trade execution. Run a trade to populate this chart.'
              }
            />
          )}
        </div>

        {/* Legend for markers */}
        {tradeMarkers.length > 0 && portfolioData.length >= 2 && (
          <div className="mt-2 flex gap-4 text-xs theme-text-secondary">
            <span className="flex items-center gap-1.5">
              <svg width="12" height="12" viewBox="0 0 12 12">
                <polygon points="6,0 12,12 0,12" fill="#22c55e" />
              </svg>
              BUY
            </span>
            <span className="flex items-center gap-1.5">
              <svg width="12" height="12" viewBox="0 0 12 12">
                <polygon points="6,12 12,0 0,0" fill="#ef4444" />
              </svg>
              SELL
            </span>
          </div>
        )}
      </div>
    </div>
  );
}
