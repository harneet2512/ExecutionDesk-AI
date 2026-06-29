'use client';

import { useEffect, useState, useCallback, useMemo, useRef } from 'react';
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ReferenceDot,
  ReferenceLine,
} from 'recharts';
import { AXIS_STYLE } from '@/lib/chartTheme';

interface PricePoint {
  t: number;
  p: number;
}

interface OutcomeHistory {
  outcome: string;
  current_price: number;
  points: PricePoint[];
}

interface ProbabilityChartProps {
  conditionId: string;
}

const INTERVALS = [
  { label: '1H', value: '1h', fidelity: 1 },
  { label: '6H', value: '6h', fidelity: 5 },
  { label: '1D', value: '1d', fidelity: 15 },
  { label: '1W', value: '1w', fidelity: 60 },
  { label: '1M', value: '1m', fidelity: 120 },
  { label: 'ALL', value: 'all', fidelity: 360 },
];

const OUTCOME_COLORS: Record<string, string> = {
  Yes: '#22c55e',
  No: '#ef4444',
};

const MULTI_OUTCOME_COLORS = [
  '#22c55e', '#3b82f6', '#a855f7', '#ef4444', '#f59e0b', '#06b6d4',
  '#ec4899', '#f97316', '#14b8a6', '#7c3aed',
];

function formatTime(ts: number, interval: string): string {
  const d = new Date(ts * 1000);
  if (interval === '1h' || interval === '6h') {
    return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  }
  if (interval === '1d') {
    return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  }
  return d.toLocaleDateString([], { month: 'short', day: 'numeric' });
}

function formatFullTime(ts: number): string {
  const d = new Date(ts * 1000);
  return d.toLocaleDateString([], { month: 'short', day: 'numeric', year: 'numeric' }) +
    ' ' + d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

function CustomTooltip({ active, payload, label }: any) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-lg shadow-xl px-3.5 py-2.5 text-xs backdrop-blur-sm"
         style={{
           backgroundColor: 'rgba(15, 23, 42, 0.92)',
           border: '1px solid rgba(148, 163, 184, 0.2)',
           color: '#f1f5f9',
         }}>
      <div className="text-[10px] mb-1.5 tracking-wide uppercase" style={{ color: '#94a3b8' }}>
        {formatFullTime(label)}
      </div>
      {payload.map((entry: any) => (
        <div key={entry.dataKey} className="flex items-center gap-2.5 py-0.5">
          <span className="w-2.5 h-2.5 rounded-sm inline-block" style={{ backgroundColor: entry.color }} />
          <span className="font-medium text-slate-300">{entry.name}</span>
          <span className="ml-auto tabular-nums font-bold pl-4" style={{ color: entry.color }}>
            {typeof entry.value === 'number' ? `${(entry.value * 100).toFixed(1)}%` : '—'}
          </span>
        </div>
      ))}
    </div>
  );
}

function EndLabel({ viewBox, value, color, name }: any) {
  if (!viewBox) return null;
  const { x, y } = viewBox;
  const pctText = typeof value === 'number' ? `${(value * 100).toFixed(1)}%` : '';
  return (
    <g>
      <circle cx={x} cy={y} r={4} fill={color} />
      <circle cx={x} cy={y} r={7} fill={color} fillOpacity={0.2} />
      <text x={x + 12} y={y + 1} fill={color} fontSize={13} fontWeight={700} dominantBaseline="middle" fontFamily="system-ui, -apple-system, sans-serif">
        {pctText}
      </text>
      <text x={x + 12} y={y + 15} fill={color} fontSize={10} fontWeight={500} fillOpacity={0.7} dominantBaseline="middle" fontFamily="system-ui, -apple-system, sans-serif">
        {name}
      </text>
    </g>
  );
}

export default function ProbabilityChart({ conditionId }: ProbabilityChartProps) {
  const [data, setData] = useState<OutcomeHistory[]>([]);
  const [loading, setLoading] = useState(true);
  const [activeInterval, setActiveInterval] = useState('1w');
  const [error, setError] = useState<string | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [chartWidth, setChartWidth] = useState(500);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const update = () => setChartWidth(el.clientWidth || 500);
    update();
    const ro = new ResizeObserver(update);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const loadHistory = useCallback(async (interval: string) => {
    setLoading(true);
    setError(null);
    const fidelity = INTERVALS.find(i => i.value === interval)?.fidelity ?? 60;
    try {
      const url = `/api/v1/markets/${conditionId}/price-history?interval=${interval}&fidelity=${fidelity}`;
      const res = await fetch(url, {
        headers: { 'X-Dev-Tenant': 't_default', 'Content-Type': 'application/json' },
      });
      if (!res.ok) {
        setError(`API ${res.status}`);
        setData([]);
        return;
      }
      const json = await res.json();
      setData(json?.history || []);
    } catch {
      setError('Failed to load chart data');
      setData([]);
    } finally {
      setLoading(false);
    }
  }, [conditionId]);

  useEffect(() => {
    loadHistory(activeInterval);
  }, [activeInterval, loadHistory]);

  const bucketSize = useMemo(() => {
    const fidelity = INTERVALS.find(i => i.value === activeInterval)?.fidelity ?? 60;
    return Math.max(fidelity * 60, 60);
  }, [activeInterval]);

  const chartData = useMemo(() => {
    if (!data.length) return [];

    const bucketedOutcomes = data.map(outcome => {
      const buckets = new Map<number, number>();
      for (const p of outcome.points) {
        const key = Math.round(p.t / bucketSize) * bucketSize;
        buckets.set(key, p.p);
      }
      return { outcome: outcome.outcome, buckets };
    });

    const allTimestamps = new Set<number>();
    for (const o of bucketedOutcomes) {
      o.buckets.forEach((_, t) => allTimestamps.add(t));
    }

    const sortedTs = Array.from(allTimestamps).sort((a, b) => a - b);

    return sortedTs.map(t => {
      const row: Record<string, number> = { t };
      for (const o of bucketedOutcomes) {
        const val = o.buckets.get(t);
        if (val !== undefined) row[o.outcome] = val;
      }
      return row;
    });
  }, [data, bucketSize]);

  const outcomeNames = data.map(d => d.outcome);
  const isBinary = outcomeNames.length === 2 &&
    outcomeNames.some(n => n.toLowerCase() === 'yes') &&
    outcomeNames.some(n => n.toLowerCase() === 'no');

  function getColor(outcome: string, index: number): string {
    if (isBinary) return OUTCOME_COLORS[outcome] || MULTI_OUTCOME_COLORS[index];
    return MULTI_OUTCOME_COLORS[index % MULTI_OUTCOME_COLORS.length];
  }

  const yDomain = useMemo(() => {
    if (!chartData.length) return [0, 1];
    let min = 1, max = 0;
    for (const row of chartData) {
      for (const key of Object.keys(row)) {
        if (key === 't') continue;
        const v = row[key];
        if (typeof v === 'number') {
          if (v < min) min = v;
          if (v > max) max = v;
        }
      }
    }
    const pad = (max - min) * 0.15 || 0.05;
    return [
      Math.max(0, Math.floor((min - pad) * 20) / 20),
      Math.min(1, Math.ceil((max + pad) * 20) / 20),
    ];
  }, [chartData]);

  const rightMargin = isBinary ? 60 : Math.max(60, outcomeNames.reduce((m, n) => Math.max(m, n.length * 7 + 50), 0));

  const hasData = chartData.length >= 2;

  return (
    <div>
      <div className="flex items-center justify-end gap-0.5 mb-3">
        {INTERVALS.map(iv => (
          <button
            key={iv.value}
            onClick={() => setActiveInterval(iv.value)}
            className={`px-2.5 py-1 text-[11px] font-semibold rounded-md transition-all ${
              activeInterval === iv.value
                ? 'bg-[var(--color-fill-primary)] text-white shadow-sm'
                : 'theme-text-muted hover:theme-text hover:bg-[var(--color-bg-subtle)]'
            }`}
          >
            {iv.label}
          </button>
        ))}
      </div>

      <div ref={containerRef} className="w-full" style={{ height: 280 }}>
        {loading ? (
          <div className="h-full flex items-center justify-center">
            <div className="w-5 h-5 border-2 border-[var(--color-fill-primary)] border-t-transparent rounded-full animate-spin" />
          </div>
        ) : error ? (
          <div className="h-full flex items-center justify-center text-xs theme-text-muted">{error}</div>
        ) : !hasData ? (
          <div className="h-full flex items-center justify-center text-xs theme-text-muted">
            Not enough data for this time range
          </div>
        ) : (
          <AreaChart width={chartWidth} height={280} data={chartData} margin={{ top: 8, right: rightMargin, bottom: 4, left: -10 }}>
            <defs>
              {data.map((outcome, i) => {
                const color = getColor(outcome.outcome, i);
                return (
                  <linearGradient key={`grad-${outcome.outcome}`} id={`grad-${outcome.outcome}`} x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor={color} stopOpacity={0.25} />
                    <stop offset="60%" stopColor={color} stopOpacity={0.08} />
                    <stop offset="100%" stopColor={color} stopOpacity={0.01} />
                  </linearGradient>
                );
              })}
            </defs>
            <CartesianGrid
              strokeDasharray="3 3"
              stroke="var(--chart-grid)"
              vertical={false}
              strokeOpacity={0.25}
            />
            {isBinary && (
              <ReferenceLine
                y={0.5}
                stroke="var(--chart-grid)"
                strokeDasharray="6 4"
                strokeOpacity={0.5}
                strokeWidth={1}
              />
            )}
            <XAxis
              dataKey="t"
              type="number"
              domain={['dataMin', 'dataMax']}
              tickFormatter={(v) => formatTime(v, activeInterval)}
              {...AXIS_STYLE}
              axisLine={false}
              tickLine={false}
              tickCount={6}
              dy={6}
              fontSize={10}
            />
            <YAxis
              domain={yDomain}
              tickFormatter={(v: number) => `${(v * 100).toFixed(0)}%`}
              {...AXIS_STYLE}
              axisLine={false}
              tickLine={false}
              width={45}
              tickCount={5}
              fontSize={10}
            />
            <Tooltip
              content={<CustomTooltip />}
              cursor={{ stroke: 'var(--color-text-muted)', strokeWidth: 1, strokeDasharray: '4 3', strokeOpacity: 0.4 }}
            />
            {data.map((outcome, i) => {
              const color = getColor(outcome.outcome, i);
              return (
                <Area
                  key={outcome.outcome}
                  type="monotone"
                  dataKey={outcome.outcome}
                  name={outcome.outcome}
                  stroke={color}
                  strokeWidth={2}
                  fill={`url(#grad-${outcome.outcome})`}
                  dot={false}
                  activeDot={{ r: 4, fill: color, strokeWidth: 2, stroke: '#fff' }}
                  connectNulls
                  isAnimationActive={false}
                />
              );
            })}
            {data.map((outcome, i) => {
              const color = getColor(outcome.outcome, i);
              const lastPoint = chartData[chartData.length - 1];
              if (!lastPoint) return null;
              const lastValue = lastPoint[outcome.outcome];
              if (typeof lastValue !== 'number') return null;
              return (
                <ReferenceDot
                  key={`dot-${outcome.outcome}`}
                  x={lastPoint.t}
                  y={lastValue}
                  r={0}
                  label={<EndLabel value={lastValue} color={color} name={outcome.outcome} />}
                />
              );
            })}
          </AreaChart>
        )}
      </div>
    </div>
  );
}
