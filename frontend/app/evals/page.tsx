'use client';

import { useEffect, useState, useCallback } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell,
} from 'recharts';
import {
  fetchEvalDashboard,
  fetchEvalRuns,
  fetchEvalSummary,
  EvalDashboard,
  EvalRunSummary,
  EvalSummary,
} from '@/lib/api';

/** Coerce any API-origin value to string for safe React rendering (never render objects as children). */
function safeStr(v: unknown): string {
  if (typeof v === 'string') return v;
  if (typeof v === 'number' && isFinite(v)) return String(v);
  if (v != null && typeof v === 'object') return JSON.stringify(v);
  return '';
}

const GRADE_COLORS: Record<string, string> = {
  A: '#525252',
  B: '#737373',
  C: '#a3a3a3',
  D: '#d4d4d4',
  F: '#e5e5e5',
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
  return typeof v === 'number' && isFinite(v) ? v.toFixed(digits) : '\u2014';
}

function GradeBadge({ grade, size = 'md' }: { grade: string; size?: 'sm' | 'md' | 'lg' }) {
  const color = GRADE_COLORS[grade] || '#6b7280';
  const sizeClasses = {
    sm: 'w-6 h-6 text-xs',
    md: 'w-8 h-8 text-sm',
    lg: 'w-12 h-12 text-xl',
  };
  return (
    <span
      className={`${sizeClasses[size]} rounded-lg font-bold flex items-center justify-center text-white`}
      style={{ backgroundColor: color }}
    >
      {grade}
    </span>
  );
}

function ScoreBar({ score, height = 8 }: { score: number; height?: number }) {
  const pct = Math.max(0, Math.min(100, score * 100));
  const color = score >= 0.9 ? '#525252' : score >= 0.7 ? '#737373' : score >= 0.5 ? '#a3a3a3' : '#d4d4d4';
  return (
    <div className="w-full bg-neutral-200 dark:bg-neutral-700 rounded-full" style={{ height }}>
      <div className="rounded-full transition-all" style={{ width: `${pct}%`, height, backgroundColor: color }} />
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

  useEffect(() => {
    loadDashboard();
  }, [loadDashboard]);

  if (loading) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <div className="theme-text-secondary">Loading eval dashboard...</div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <div className="text-center">
          <p className="text-[var(--color-status-error)] mb-4">{error}</p>
          <button
            onClick={() => { setLoading(true); loadDashboard(); }}
            className="btn-primary"
          >
            Retry
          </button>
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
    <div className="flex-1 overflow-y-auto">
      <div className="p-6 max-w-7xl mx-auto">
        {/* Header */}
        <div className="flex items-center justify-between mb-6">
          <h1 className="text-2xl font-bold theme-text">
            Evaluation Dashboard
          </h1>
          <button
            onClick={() => { setLoading(true); loadDashboard(); }}
            className="btn-secondary"
          >
            Refresh
          </button>
        </div>

        {/* Top-level metrics */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
          <div className="p-4 theme-elevated border theme-border rounded-xl">
            <p className="text-xs theme-text-secondary uppercase tracking-wide mb-1">Runs Evaluated</p>
            <p className="text-3xl font-bold theme-text">{dashboard.total_runs_evaluated}</p>
          </div>
          <div className="p-4 theme-elevated border theme-border rounded-xl">
            <p className="text-xs theme-text-secondary uppercase tracking-wide mb-1">Avg Score</p>
            <p className="text-3xl font-bold theme-text">{fmtScore(dashboard.overall_avg_score)}</p>
          </div>
          <div className="p-4 theme-elevated border theme-border rounded-xl">
            <p className="text-xs theme-text-secondary uppercase tracking-wide mb-1">Overall Grade</p>
            <div className="mt-1">
              <GradeBadge grade={dashboard.overall_grade} size="lg" />
            </div>
          </div>
          <div className="p-4 theme-elevated border theme-border rounded-xl">
            <p className="text-xs theme-text-secondary uppercase tracking-wide mb-1">Categories</p>
            <p className="text-3xl font-bold theme-text">{categoryEntries.length}</p>
          </div>
        </div>

        {/* Enterprise Summary Tiles */}
        {summary && (
          <div className="mb-6">
            {/* Row 1: Core aggregate metrics */}
            <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-8 gap-3 mb-3">
              <div className="p-3 theme-elevated border theme-border rounded-xl">
                <p className="text-xs theme-text-secondary uppercase tracking-wide">Min Score</p>
                <p className="text-xl font-bold theme-text">
                  {summary.min_score !== null && summary.min_score !== undefined ? fmtScore(summary.min_score) : '\u2014'}
                </p>
              </div>
              <div className="p-3 theme-elevated border theme-border rounded-xl">
                <p className="text-xs theme-text-secondary uppercase tracking-wide">Max Score</p>
                <p className="text-xl font-bold theme-text">
                  {summary.max_score !== null && summary.max_score !== undefined ? fmtScore(summary.max_score) : '\u2014'}
                </p>
              </div>
              <div className="p-3 theme-elevated border theme-border rounded-xl">
                <p className="text-xs theme-text-secondary uppercase tracking-wide">P50 Score</p>
                <p className="text-xl font-bold theme-text">
                  {summary.p50_score !== null && summary.p50_score !== undefined ? fmtScore(summary.p50_score) : '\u2014'}
                </p>
              </div>
              <div className="p-3 theme-elevated border theme-border rounded-xl">
                <p className="text-xs theme-text-secondary uppercase tracking-wide">P95 Score</p>
                <p className="text-xl font-bold theme-text">
                  {summary.p95_score !== null && summary.p95_score !== undefined ? fmtScore(summary.p95_score) : '\u2014'}
                </p>
              </div>
              <div className="p-3 theme-elevated border theme-border rounded-xl">
                <p className="text-xs theme-text-secondary uppercase tracking-wide">Pass Rate</p>
                <p className="text-xl font-bold text-[var(--color-status-success)]">
                  {typeof summary.pass_rate === 'number' && isFinite(summary.pass_rate)
                    ? `${(summary.pass_rate * 100).toFixed(1)}%` : '\u2014'}
                </p>
              </div>
              <div className="p-3 theme-elevated border theme-border rounded-xl">
                <p className="text-xs theme-text-secondary uppercase tracking-wide">Avg Groundedness</p>
                <p className="text-xl font-bold theme-text">
                  {summary.avg_groundedness !== null ? fmtScore(summary.avg_groundedness) : '\u2014'}
                </p>
              </div>
              <div className="p-3 theme-elevated border theme-border rounded-xl">
                <p className="text-xs theme-text-secondary uppercase tracking-wide">Avg Retrieval Rel.</p>
                <p className="text-xl font-bold theme-text">
                  {summary.avg_retrieval_relevance !== null ? fmtScore(summary.avg_retrieval_relevance) : '\u2014'}
                </p>
              </div>
              <div className="p-3 theme-elevated border theme-border rounded-xl">
                <div className="flex gap-1 mb-1">
                  {['24h', '7d'].map(w => (
                    <button
                      key={w}
                      onClick={() => setSummaryWindow(w)}
                      className={`px-2 py-1 text-xs rounded-lg ${summaryWindow === w ? 'btn-primary' : 'btn-secondary'}`}
                    >
                      {w}
                    </button>
                  ))}
                </div>
                <p className="text-xl font-bold theme-text">{summary.total_runs}</p>
                <p className="text-xs theme-text-secondary">runs in window</p>
              </div>
            </div>
            {/* Row 2: Data quality warnings */}
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
              <div className="p-3 theme-elevated border theme-border rounded-xl">
                <p className="text-xs theme-text-secondary uppercase tracking-wide">% Missing Headlines</p>
                <p className="text-xl font-bold text-[var(--color-status-warning)]">
                  {typeof summary.missing_headlines_pct === 'number' && isFinite(summary.missing_headlines_pct)
                    ? `${summary.missing_headlines_pct}%` : '\u2014'}
                </p>
              </div>
              <div className="p-3 theme-elevated border theme-border rounded-xl">
                <p className="text-xs theme-text-secondary uppercase tracking-wide">% Missing Candles</p>
                <p className="text-xl font-bold text-[var(--color-status-warning)]">
                  {typeof summary.missing_candles_pct === 'number' && isFinite(summary.missing_candles_pct)
                    ? `${summary.missing_candles_pct}%` : '\u2014'}
                </p>
              </div>
              <div className="p-3 theme-elevated border theme-border rounded-xl">
                <p className="text-xs theme-text-secondary uppercase tracking-wide">Passed</p>
                <p className="text-xl font-bold text-[var(--color-status-success)]">{summary.passed_count ?? '\u2014'}</p>
              </div>
              <div className="p-3 theme-elevated border theme-border rounded-xl">
                <p className="text-xs theme-text-secondary uppercase tracking-wide">Failed</p>
                <p className="text-xl font-bold text-[var(--color-status-error)]">{summary.failed_count ?? '\u2014'}</p>
              </div>
            </div>
          </div>
        )}

        {/* Category Scores + Grade Distribution */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6">
          {/* Category bar chart */}
          <div className="p-4 theme-elevated border theme-border rounded-xl">
            <h2 className="text-lg font-semibold mb-4 theme-text">Score by Category</h2>
            {categoryChartData.length > 0 ? (
              <ResponsiveContainer width="100%" height={280}>
                <BarChart data={categoryChartData} layout="vertical" margin={{ left: 80 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#525252" />
                  <XAxis type="number" domain={[0, 1]} tick={{ fill: '#a3a3a3' }} />
                  <YAxis type="category" dataKey="category" width={80} tick={{ fill: '#a3a3a3', fontSize: 12 }} />
                  <Tooltip
                    contentStyle={{ backgroundColor: 'var(--chart-tooltip-bg, #1e293b)', border: '1px solid var(--chart-tooltip-border, #334155)', borderRadius: '8px', color: 'var(--chart-tooltip-text, #e2e8f0)' }}
                    labelStyle={{ color: 'var(--chart-tooltip-text, #e2e8f0)' }}
                    itemStyle={{ color: 'var(--chart-tooltip-text, #e2e8f0)' }}
                    formatter={(value: any) => [fmtScore(value), 'Score']}
                  />
                  <Bar dataKey="score" radius={[0, 4, 4, 0]}>
                    {categoryChartData.map((entry, idx) => (
                      <Cell key={idx} fill={GRADE_COLORS[entry.grade] || '#6b7280'} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            ) : (
              <p className="theme-text-secondary">No category data</p>
            )}
          </div>

          {/* Grade distribution */}
          <div className="p-4 theme-elevated border theme-border rounded-xl">
            <h2 className="text-lg font-semibold mb-4 theme-text">Grade Distribution</h2>
            {gradeChartData.length > 0 ? (
              <ResponsiveContainer width="100%" height={280}>
                <BarChart data={gradeChartData}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#525252" />
                  <XAxis dataKey="grade" tick={{ fill: '#a3a3a3' }} />
                  <YAxis allowDecimals={false} tick={{ fill: '#a3a3a3' }} />
                  <Tooltip
                    contentStyle={{ backgroundColor: 'var(--chart-tooltip-bg, #1e293b)', border: '1px solid var(--chart-tooltip-border, #334155)', borderRadius: '8px', color: 'var(--chart-tooltip-text, #e2e8f0)' }}
                    labelStyle={{ color: 'var(--chart-tooltip-text, #e2e8f0)' }}
                    itemStyle={{ color: 'var(--chart-tooltip-text, #e2e8f0)' }}
                  />
                  <Bar dataKey="count" name="Runs">
                    {gradeChartData.map((entry, idx) => (
                      <Cell key={idx} fill={GRADE_COLORS[entry.grade] || '#6b7280'} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            ) : (
              <p className="theme-text-secondary">No grade data</p>
            )}
          </div>
        </div>

        {/* Category Cards */}
        <div className="mb-6">
          <h2 className="text-lg font-semibold mb-4 theme-text">Category Breakdown</h2>
          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
            {categoryEntries.map(([cat, data]) => (
              <div
                key={cat}
                className="p-3 theme-elevated border theme-border rounded-xl"
              >
                <div className="flex items-center gap-2 mb-2">
                  <GradeBadge grade={data.grade} size="sm" />
                  <span className="text-xs font-medium theme-text-secondary truncate">
                    {CATEGORY_LABELS[cat] || cat}
                  </span>
                </div>
                <ScoreBar score={data.avg_score} />
                <p className="text-xs theme-text-secondary mt-1">
                  {fmtScore(data.avg_score)} avg | {data.eval_count} evals
                </p>
                <p className="text-xs theme-text-muted mt-1">
                  {data.min_score != null ? `min ${fmtScore(data.min_score)}` : ''}
                  {data.max_score != null ? ` / max ${fmtScore(data.max_score)}` : ''}
                </p>
                {data.pass_rate != null && (
                  <p className="text-xs text-[var(--color-status-success)] mt-1">
                    {(data.pass_rate * 100).toFixed(0)}% pass rate
                  </p>
                )}
              </div>
            ))}
          </div>
        </div>

        {/* Recent Runs Table */}
        <div className="mb-6">
          <h2 className="text-lg font-semibold mb-4 theme-text">Recent Evaluated Runs</h2>
          <div className="theme-elevated border theme-border rounded-xl overflow-hidden">
            <table className="w-full">
              <thead>
                <tr className="border-b theme-border theme-elevated">
                  <th className="text-left px-4 py-3 text-xs font-medium theme-text-secondary uppercase">Run</th>
                  <th className="text-left px-4 py-3 text-xs font-medium theme-text-secondary uppercase">Command</th>
                  <th className="text-center px-4 py-3 text-xs font-medium theme-text-secondary uppercase">Grade</th>
                  <th className="text-right px-4 py-3 text-xs font-medium theme-text-secondary uppercase">Score</th>
                  <th className="text-right px-4 py-3 text-xs font-medium theme-text-secondary uppercase">Evals</th>
                  <th className="text-right px-4 py-3 text-xs font-medium theme-text-secondary uppercase">Pass/Fail</th>
                  <th className="text-right px-4 py-3 text-xs font-medium theme-text-secondary uppercase">Time</th>
                </tr>
              </thead>
              <tbody>
                {(runs.length > 0 ? runs : dashboard.recent_runs).map((run) => (
                  <tr
                    key={run.run_id}
                    onClick={() => router.push(`/evals/runs/${run.run_id}`)}
                    className="border-b theme-border hover:bg-[var(--color-fill-ghost-hover)] cursor-pointer"
                  >
                    <td className="px-4 py-3">
                      <Link
                        href={`/evals/runs/${run.run_id}`}
                        className="text-xs font-mono theme-text-secondary hover:underline"
                        onClick={(e) => e.stopPropagation()}
                      >
                        {run.run_id.slice(0, 12)}
                      </Link>
                    </td>
                    <td className="px-4 py-3">
                      <span className="text-sm theme-text-secondary truncate block max-w-[200px]">
                        {run.command || '\u2014'}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-center">
                      <GradeBadge grade={run.grade} size="sm" />
                    </td>
                    <td className="px-4 py-3 text-right text-sm font-medium theme-text">
                      {fmtScore(run.avg_score)}
                    </td>
                    <td className="px-4 py-3 text-right text-sm theme-text-secondary">
                      {run.eval_count}
                    </td>
                    <td className="px-4 py-3 text-right">
                      <span className="text-sm">
                        <span className="text-[var(--color-status-success)]">{run.passed}</span>
                        {' / '}
                        <span className="text-[var(--color-status-error)]">{run.failed}</span>
                      </span>
                    </td>
                    <td className="px-4 py-3 text-right text-xs theme-text-secondary">
                      {new Date(run.created_at).toLocaleString()}
                    </td>
                  </tr>
                ))}
                {runs.length === 0 && dashboard.recent_runs.length === 0 && (
                  <tr>
                    <td colSpan={7} className="px-4 py-8 text-center theme-text-secondary">
                      No evaluated runs yet. Run a trade command to generate eval results.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>

      </div>
    </div>
  );
}
