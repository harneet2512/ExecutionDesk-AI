'use client';

import { useEffect, useState, useCallback } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Cell,
} from 'recharts';
import {
  fetchEvalDashboard,
  fetchEvalRuns,
  fetchEvalSummary,
  EvalDashboard,
  EvalRunSummary,
  EvalSummary,
} from '@/lib/api';
import { fmtNumber, fmtPercent, fmtTimeAgo } from '@/lib/format';
import { CHART_COLORS, AXIS_STYLE, GRID_STYLE, TOOLTIP_STYLE } from '@/lib/chartTheme';
import PageSkeleton from '@/components/PageSkeleton';
import ChartBox from '@/components/ChartBox';

function safeStr(v: unknown): string {
  if (typeof v === 'string') return v;
  if (typeof v === 'number' && isFinite(v)) return String(v);
  if (v != null && typeof v === 'object') return JSON.stringify(v);
  return '';
}

const GRADE_COLORS: Record<string, string> = {
  A: '#2563eb',
  B: '#16a34a',
  C: '#ea580c',
  D: '#9333ea',
  F: '#dc2626',
};

const CATEGORY_LABELS: Record<string, string> = {
  rag: 'RAG / Retrieval',
  safety: 'Safety',
  quality: 'Quality',
  compliance: 'Compliance',
  performance: 'Performance',
  data: 'Data Integrity',
};

function fmtScore(v: any, digits: number = 3): string {
  return typeof v === 'number' && isFinite(v) ? v.toFixed(digits) : '—';
}

function GradeBadge({ grade, size = 'md' }: { grade: string; size?: 'sm' | 'md' | 'lg' }) {
  const color = GRADE_COLORS[grade] || '#16a34a';
  const sizeClasses = {
    sm: 'w-5 h-5 text-[10px]',
    md: 'w-7 h-7 text-xs',
    lg: 'w-10 h-10 text-lg',
  };
  return (
    <span
      className={`${sizeClasses[size]} rounded-md font-bold flex items-center justify-center text-white`}
      style={{ backgroundColor: color }}
    >
      {grade}
    </span>
  );
}

function ScoreBar({ score }: { score: number }) {
  const pct = Math.max(0, Math.min(100, score * 100));
  const color = score >= 0.9 ? GRADE_COLORS.A : score >= 0.7 ? GRADE_COLORS.B : score >= 0.5 ? GRADE_COLORS.C : GRADE_COLORS.D;
  return (
    <div className="w-full h-1.5 rounded-full" style={{ backgroundColor: 'var(--color-border)' }}>
      <div className="h-1.5 rounded-full transition-all" style={{ width: `${pct}%`, backgroundColor: color }} />
    </div>
  );
}

export default function EvalsPage() {
  const router = useRouter();
  const [dashboard, setDashboard] = useState<EvalDashboard | null>(null);
  const [runs, setRuns] = useState<EvalRunSummary[]>([]);
  const [summary, setSummary] = useState<EvalSummary | null>(null);
  const [summaryWindow, setSummaryWindow] = useState<string>('24h');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadDashboard = useCallback(async () => {
    try {
      const [dash, runsData, sum] = await Promise.all([
        fetchEvalDashboard(),
        fetchEvalRuns(50, 0),
        fetchEvalSummary(summaryWindow).catch(() => null),
      ]);
      setDashboard(dash);
      setRuns(runsData.runs);
      if (sum) setSummary(sum);
      setError(null);
    } catch (e: any) {
      setError(e.message || 'Failed to load eval dashboard');
    } finally {
      setLoading(false);
    }
  }, [summaryWindow]);

  useEffect(() => { loadDashboard(); }, [loadDashboard]);

  if (loading) return <PageSkeleton title="Evaluations" />;

  if (error) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <div className="text-center">
          <p className="text-sm loss mb-3">{error}</p>
          <button onClick={() => { setLoading(true); loadDashboard(); }} className="btn-primary text-sm px-4 py-2 rounded-lg">Retry</button>
        </div>
      </div>
    );
  }

  if (!dashboard) return null;

  const categoryEntries = Object.entries(dashboard.category_scores);
  const categoryChartData = categoryEntries.map(([cat, data]) => ({
    category: CATEGORY_LABELS[cat] || safeStr(cat),
    score: typeof data?.avg_score === 'number' && isFinite(data.avg_score) ? data.avg_score : 0,
    grade: safeStr(data?.grade),
    count: typeof data?.eval_count === 'number' && isFinite(data.eval_count) ? data.eval_count : 0,
  }));

  const gradeChartData = Object.entries(dashboard.grade_distribution ?? {})
    .filter(([, count]) => typeof count === 'number' && count > 0)
    .map(([grade, count]) => ({ grade: safeStr(grade), count: Number(count) }));

  return (
    <div className="flex-1 overflow-y-auto p-6 lg:p-8 max-w-7xl mx-auto page-enter">
      {/* Header */}
      <div className="flex items-baseline justify-between mb-6">
        <div>
          <h1 className="text-xl font-semibold theme-text">Evaluations</h1>
          <p className="text-sm theme-text-muted mt-0.5">
            {dashboard.total_runs_evaluated} runs evaluated · Grade {dashboard.overall_grade}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <div className="flex gap-0.5 p-0.5 rounded-lg theme-elevated">
            {['24h', '7d'].map(w => (
              <button
                key={w}
                onClick={() => setSummaryWindow(w)}
                className={`text-xs font-medium px-3 py-1.5 rounded-md transition-colors ${
                  summaryWindow === w
                    ? 'theme-surface shadow-sm theme-text'
                    : 'theme-text-muted hover:theme-text-secondary'
                }`}
              >
                {w}
              </button>
            ))}
          </div>
          <button
            onClick={() => { setLoading(true); loadDashboard(); }}
            className="btn-ghost text-xs px-3 py-1.5 rounded-md border theme-border"
          >
            Refresh
          </button>
        </div>
      </div>

      {/* Top metrics */}
      <div className="grid grid-cols-2 lg:grid-cols-5 gap-3 mb-6 stagger-enter">
        <div className="metric-card">
          <div className="metric-label">Overall Grade</div>
          <div className="flex items-center gap-2 mt-1">
            <GradeBadge grade={dashboard.overall_grade} size="lg" />
          </div>
        </div>
        <div className="metric-card">
          <div className="metric-label">Avg Score</div>
          <div className="metric-value">{fmtScore(dashboard.overall_avg_score)}</div>
        </div>
        <div className="metric-card">
          <div className="metric-label">Pass Rate</div>
          <div className="metric-value" style={{ color: 'var(--color-gain)' }}>
            {summary && typeof summary.pass_rate === 'number'
              ? fmtPercent(summary.pass_rate * 100) : '—'}
          </div>
        </div>
        <div className="metric-card">
          <div className="metric-label">Runs Evaluated</div>
          <div className="metric-value">{fmtNumber(dashboard.total_runs_evaluated)}</div>
        </div>
        <div className="metric-card">
          <div className="metric-label">Categories</div>
          <div className="metric-value">{categoryEntries.length}</div>
        </div>
      </div>

      {/* Summary stats row */}
      {summary && (
        <div className="grid grid-cols-3 lg:grid-cols-6 gap-3 mb-6">
          {[
            { label: 'Min', value: summary.min_score },
            { label: 'P50', value: summary.p50_score },
            { label: 'P95', value: summary.p95_score },
            { label: 'Max', value: summary.max_score },
            { label: 'Passed', value: summary.passed_count, isCount: true, color: 'var(--color-gain)' },
            { label: 'Failed', value: summary.failed_count, isCount: true, color: 'var(--color-loss)' },
          ].map(item => (
            <div key={item.label} className="px-3 py-2 border theme-border rounded-lg">
              <div className="text-[10px] uppercase tracking-wider theme-text-muted">{item.label}</div>
              <div
                className="text-sm font-semibold tabular-nums"
                style={item.color ? { color: item.color } : undefined}
              >
                {item.value != null ? (item.isCount ? item.value : fmtScore(item.value)) : '—'}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Charts */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 mb-6">
        <div className="chart-container">
          <div className="chart-title">Score by Category</div>
          {categoryChartData.length > 0 ? (
            <ChartBox height={240}>
              {(w, h) => (
                <BarChart width={w} height={h} data={categoryChartData} layout="vertical" margin={{ left: 80 }}>
                  <CartesianGrid {...GRID_STYLE} />
                  <XAxis type="number" domain={[0, 1]} tick={AXIS_STYLE} tickLine={false} axisLine={false} />
                  <YAxis type="category" dataKey="category" width={80} tick={{ ...AXIS_STYLE, fontSize: 11 }} tickLine={false} axisLine={false} />
                  <Tooltip {...TOOLTIP_STYLE} formatter={(value: any) => [fmtScore(value), 'Score']} />
                  <Bar dataKey="score" radius={[0, 3, 3, 0]}>
                    {categoryChartData.map((entry, idx) => (
                      <Cell key={idx} fill={GRADE_COLORS[entry.grade] || GRADE_COLORS.B} />
                    ))}
                  </Bar>
                </BarChart>
              )}
            </ChartBox>
          ) : (
            <div className="h-[240px] flex items-center justify-center theme-text-muted text-sm">No category data</div>
          )}
        </div>

        <div className="chart-container">
          <div className="chart-title">Grade Distribution</div>
          {gradeChartData.length > 0 ? (
            <ChartBox height={240}>
              {(w, h) => (
                <BarChart width={w} height={h} data={gradeChartData}>
                  <CartesianGrid {...GRID_STYLE} />
                  <XAxis dataKey="grade" tick={AXIS_STYLE} tickLine={false} axisLine={false} />
                  <YAxis allowDecimals={false} tick={AXIS_STYLE} tickLine={false} axisLine={false} />
                  <Tooltip {...TOOLTIP_STYLE} />
                  <Bar dataKey="count" name="Runs" radius={[3, 3, 0, 0]}>
                    {gradeChartData.map((entry, idx) => (
                      <Cell key={idx} fill={GRADE_COLORS[entry.grade] || GRADE_COLORS.B} />
                    ))}
                  </Bar>
                </BarChart>
              )}
            </ChartBox>
          ) : (
            <div className="h-[240px] flex items-center justify-center theme-text-muted text-sm">No grade data</div>
          )}
        </div>
      </div>

      {/* Category breakdown cards */}
      <div className="mb-6">
        <div className="section-header">Category Breakdown</div>
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
          {categoryEntries.map(([cat, data]) => (
            <div key={cat} className="metric-card !p-3">
              <div className="flex items-center gap-1.5 mb-2">
                <GradeBadge grade={data.grade} size="sm" />
                <span className="text-xs font-medium theme-text-muted truncate">
                  {CATEGORY_LABELS[cat] || cat}
                </span>
              </div>
              <ScoreBar score={data.avg_score} />
              <p className="text-xs tabular-nums theme-text-muted mt-1.5">
                {fmtScore(data.avg_score)} avg · {data.eval_count} evals
              </p>
              {data.pass_rate != null && (
                <p className="text-[10px] tabular-nums mt-0.5" style={{ color: 'var(--color-gain)' }}>
                  {(data.pass_rate * 100).toFixed(0)}% pass
                </p>
              )}
            </div>
          ))}
        </div>
      </div>

      {/* Runs table */}
      <div className="border theme-border rounded-lg overflow-hidden">
        <div className="px-4 py-3 theme-elevated flex items-center justify-between">
          <span className="section-header !mb-0">Recent Evaluated Runs</span>
        </div>
        <table className="data-table">
          <thead>
            <tr>
              <th>Run</th>
              <th>Command</th>
              <th>Grade</th>
              <th className="num">Score</th>
              <th className="num">Evals</th>
              <th className="num">Pass/Fail</th>
              <th>Time</th>
            </tr>
          </thead>
          <tbody>
            {(runs.length > 0 ? runs : dashboard.recent_runs).map((run) => (
              <tr
                key={run.run_id}
                onClick={() => router.push(`/evals/runs/${run.run_id}`)}
                className="cursor-pointer"
              >
                <td>
                  <Link
                    href={`/evals/runs/${run.run_id}`}
                    className="font-mono text-xs text-[var(--color-link)] hover:underline"
                    onClick={(e) => e.stopPropagation()}
                  >
                    {run.run_id.slice(0, 10)}
                  </Link>
                </td>
                <td className="max-w-[180px] truncate theme-text-muted text-xs">{run.command || '—'}</td>
                <td><GradeBadge grade={run.grade} size="sm" /></td>
                <td className="num tabular-nums font-medium">{fmtScore(run.avg_score)}</td>
                <td className="num tabular-nums theme-text-muted">{run.eval_count}</td>
                <td className="num tabular-nums">
                  <span style={{ color: 'var(--color-gain)' }}>{run.passed}</span>
                  {' / '}
                  <span style={{ color: 'var(--color-loss)' }}>{run.failed}</span>
                </td>
                <td className="tabular-nums theme-text-muted text-xs">{fmtTimeAgo(run.created_at)}</td>
              </tr>
            ))}
            {runs.length === 0 && dashboard.recent_runs.length === 0 && (
              <tr>
                <td colSpan={7} className="text-center py-10 theme-text-muted">
                  No evaluated runs yet. Execute a trade to generate eval results.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
