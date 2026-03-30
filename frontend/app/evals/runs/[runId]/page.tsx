'use client';

import { useEffect, useState, useCallback, useMemo } from 'react';
import Link from 'next/link';
import { useParams } from 'next/navigation';
import {
  fetchEvalRunDetail,
  fetchEvalRunExplain,
  type EvalRunDetail,
  type EvalDetail,
  type EvalRunExplainResponse,
} from '@/lib/api';
import EvalExplainability from '@/components/EvalExplainability';

function safeStr(v: unknown): string {
  if (typeof v === 'string') return v;
  if (typeof v === 'number' && isFinite(v)) return String(v);
  if (v != null && typeof v === 'object') return JSON.stringify(v);
  return '';
}

function fmtScore(v: unknown, digits = 3): string {
  return typeof v === 'number' && isFinite(v) ? v.toFixed(digits) : '\u2014';
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

function GradeBadge({ grade, size = 'md' }: { grade: string; size?: 'sm' | 'md' | 'lg' }) {
  const color = GRADE_COLORS[grade] || '#6b7280';
  const sizeClasses = { sm: 'w-6 h-6 text-xs', md: 'w-8 h-8 text-sm', lg: 'w-10 h-10 text-base' };
  return (
    <span
      className={`${sizeClasses[size]} rounded-lg font-bold flex items-center justify-center text-white`}
      style={{ backgroundColor: color }}
    >
      {safeStr(grade)}
    </span>
  );
}

/** Flatten all evals from categories for filtering */
function getAllEvals(detail: EvalRunDetail | null): EvalDetail[] {
  if (!detail?.categories) return [];
  const list: EvalDetail[] = [];
  for (const catData of Object.values(detail.categories)) {
    const evals = catData?.evals;
    if (Array.isArray(evals)) {
      for (const ev of evals) {
        if (ev && (typeof ev.eval_name === 'string' || ev.eval_name != null)) list.push(ev);
      }
    }
  }
  return list;
}

export default function EvalRunDetailPage() {
  const params = useParams();
  const runId = typeof params?.runId === 'string' ? params.runId : '';
  const [detail, setDetail] = useState<EvalRunDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [categoryFilter, setCategoryFilter] = useState<string>('');
  const [passFilter, setPassFilter] = useState<'all' | 'pass' | 'fail'>('all');
  const [scopeFilter, setScopeFilter] = useState<'all' | 'run' | 'step' | 'message'>('all');
  const [search, setSearch] = useState('');
  const [expandedEval, setExpandedEval] = useState<string | null>(null);
  const [runExplanation, setRunExplanation] = useState<EvalRunExplainResponse['run_explanation']>(null);
  const [explainLoading, setExplainLoading] = useState(false);
  const [explainError, setExplainError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!runId) {
      setError('Missing run ID');
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const data = await fetchEvalRunDetail(runId);
      setDetail(data);
    } catch (e: unknown) {
      const msg = e && typeof e === 'object' && 'message' in e ? String((e as { message: unknown }).message) : 'Run not found';
      setError(msg);
      setDetail(null);
    } finally {
      setLoading(false);
    }
  }, [runId]);

  useEffect(() => {
    load();
  }, [load]);

  const handleGenerateExplanations = useCallback(async () => {
    if (!runId) return;
    setExplainLoading(true);
    setExplainError(null);
    try {
      const res = await fetchEvalRunExplain(runId);
      setRunExplanation(res.run_explanation ?? null);
      await load();
    } catch (e: unknown) {
      setExplainError(e && typeof e === 'object' && 'message' in e ? String((e as { message: unknown }).message) : 'Failed to generate explanations');
    } finally {
      setExplainLoading(false);
    }
  }, [runId, load]);

  const allEvals = useMemo(() => getAllEvals(detail), [detail]);
  const filteredEvals = useMemo(() => {
    let list = allEvals;
    if (categoryFilter) {
      list = list.filter((ev) => safeStr(ev.category) === categoryFilter);
    }
    if (passFilter === 'pass') list = list.filter((ev) => ev.pass === true);
    if (passFilter === 'fail') list = list.filter((ev) => !ev.pass);
    // Scope filtering: run-level (no step_name), step-level (step_name but no message_id), message-level
    if (scopeFilter === 'run') list = list.filter((ev: any) => !ev.step_name && !ev.message_id);
    if (scopeFilter === 'step') list = list.filter((ev: any) => ev.step_name && !ev.message_id);
    if (scopeFilter === 'message') list = list.filter((ev: any) => ev.message_id);
    if (search.trim()) {
      const q = search.trim().toLowerCase();
      list = list.filter(
        (ev) =>
          safeStr(ev.eval_name).toLowerCase().includes(q) ||
          safeStr(ev.category).toLowerCase().includes(q)
      );
    }
    return list;
  }, [allEvals, categoryFilter, passFilter, scopeFilter, search]);

  const categories = useMemo(() => {
    const set = new Set<string>();
    for (const ev of allEvals) {
      if (ev.category) set.add(safeStr(ev.category));
    }
    return Array.from(set).sort();
  }, [allEvals]);

  if (loading) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <div className="theme-text-secondary">Loading run evaluation...</div>
      </div>
    );
  }

  if (error || !detail) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <div className="text-center">
          <p className="text-[var(--color-status-error)] mb-4">{error || 'Run not found'}</p>
          <Link
            href="/evals"
            className="px-4 py-2 btn-primary rounded-lg transition-colors inline-block"
          >
            Back to Evals
          </Link>
        </div>
      </div>
    );
  }

  const run = detail.run ?? {};
  const summary = detail.summary ?? {};

  return (
    <div className="flex-1 overflow-y-auto">
      <div className="p-6 max-w-6xl mx-auto">
        {/* Breadcrumb */}
        <div className="mb-4 text-sm theme-text-secondary">
          <Link href="/evals" className="hover:theme-text">Evals</Link>
          <span className="mx-2">/</span>
          <span className="font-mono theme-text-secondary">{safeStr(run.run_id).slice(0, 12)}</span>
        </div>

        {/* Run header */}
        <div className="p-4 theme-elevated border theme-border rounded-xl mb-6">
          <div className="flex flex-wrap items-center gap-4">
            <div>
              <p className="text-xs theme-text-secondary uppercase">Run</p>
              <p className="font-mono theme-text">{safeStr(run.run_id)}</p>
            </div>
            <div>
              <p className="text-xs theme-text-secondary uppercase">Command</p>
              <p className="text-sm theme-text-secondary max-w-md truncate" title={safeStr(run.command)}>
                {run.command || '\u2014'}
              </p>
            </div>
            <div>
              <p className="text-xs theme-text-secondary uppercase">Time</p>
              <p className="text-sm theme-text-secondary">
                {run.created_at ? new Date(run.created_at).toLocaleString() : '\u2014'}
              </p>
            </div>
            <div>
              <p className="text-xs theme-text-secondary uppercase">Status</p>
              <p className="text-sm theme-text-secondary">{safeStr(run.status)}</p>
            </div>
            <div className="flex items-center gap-2">
              <GradeBadge grade={summary.grade} size="lg" />
              <div>
                <p className="text-xs theme-text-secondary">Score</p>
                <p className="text-lg font-bold theme-text">{fmtScore(summary.avg_score)}</p>
              </div>
            </div>
            <div>
              <p className="text-xs theme-text-secondary">Pass / Fail</p>
              <p className="text-sm">
                <span className="text-[var(--color-status-success)]">{summary.passed ?? 0}</span>
                <span className="theme-text-muted mx-1">/</span>
                <span className="text-[var(--color-status-error)]">{summary.failed ?? 0}</span>
              </p>
            </div>
            <div className="ml-auto">
              <button
                type="button"
                onClick={handleGenerateExplanations}
                disabled={explainLoading || allEvals.length === 0}
                className="px-4 py-2 text-sm btn-primary rounded-lg disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
              >
                {explainLoading ? 'Generating…' : 'Generate explanations'}
              </button>
              {explainError && (
                <p className="text-xs text-[var(--color-status-error)] mt-1">{explainError}</p>
              )}
            </div>
          </div>
        </div>

        {/* Category breakdown */}
        {detail.categories && Object.keys(detail.categories).length > 0 && (
          <div className="mb-6">
            <h2 className="text-lg font-semibold mb-3 theme-text">Category breakdown</h2>
            <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
              {Object.entries(detail.categories).map(([cat, data]) => (
                <div
                  key={cat}
                  className="p-3 theme-elevated border theme-border rounded-xl"
                >
                  <div className="flex items-center gap-2 mb-1">
                    <GradeBadge grade={data?.grade} size="sm" />
                    <span className="text-xs font-medium theme-text-secondary truncate">
                      {CATEGORY_LABELS[cat] || safeStr(cat)}
                    </span>
                  </div>
                  <p className="text-xs theme-text-secondary">
                    {fmtScore(data?.avg_score)} avg · {data?.total ?? 0} evals
                  </p>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Run-level explanation (from Generate explanations) */}
        {runExplanation && (
          <div className="p-4 theme-elevated border theme-border rounded-xl mb-6 space-y-3">
            <h2 className="text-sm font-semibold theme-text">Run summary (LLM)</h2>
            {runExplanation.main_drivers && runExplanation.main_drivers.length > 0 && (
              <div>
                <p className="text-xs font-medium theme-text-secondary mb-1">Main drivers</p>
                <ul className="text-sm theme-text-secondary list-disc list-inside space-y-0.5">
                  {runExplanation.main_drivers.map((s, i) => (
                    <li key={i}>{safeStr(s)}</li>
                  ))}
                </ul>
              </div>
            )}
            {runExplanation.strongest_areas && runExplanation.strongest_areas.length > 0 && (
              <div>
                <p className="text-xs font-medium theme-text-secondary mb-1">Strongest areas</p>
                <ul className="text-sm theme-text-secondary list-disc list-inside space-y-0.5">
                  {runExplanation.strongest_areas.map((s, i) => (
                    <li key={i}>{safeStr(s)}</li>
                  ))}
                </ul>
              </div>
            )}
            {runExplanation.what_to_fix && runExplanation.what_to_fix.length > 0 && (
              <div>
                <p className="text-xs font-medium text-[var(--color-status-warning)] mb-1">What to fix</p>
                <ul className="text-sm text-[var(--color-status-warning)] list-disc list-inside space-y-0.5">
                  {runExplanation.what_to_fix.map((s, i) => (
                    <li key={i}>{safeStr(s)}</li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}

        {/* Why is my score X? — top negative contributors */}
        {allEvals.length > 0 && (() => {
          const failures = allEvals.filter((e) => !e.pass).slice(0, 5);
          if (failures.length === 0) return null;
          return (
            <div className="p-4 bg-[var(--color-status-warning-bg)] border border-[var(--color-status-warning)]/20 rounded-xl mb-6">
              <h2 className="text-sm font-semibold text-[var(--color-status-warning)] mb-2">Top negative contributors</h2>
              <ul className="text-sm text-[var(--color-status-warning)] space-y-1">
                {failures.map((ev, i) => (
                  <li key={i}>
                    <span className="font-medium">{safeStr(ev.eval_name).replace(/_/g, ' ')}</span>
                    {' — '}
                    {Array.isArray(ev.reasons) && ev.reasons.length > 0
                      ? safeStr(ev.reasons[0])
                      : `Score ${fmtScore(ev.score)} below threshold`}
                  </li>
                ))}
              </ul>
            </div>
          );
        })()}

        {/* Eval list with filters */}
        <div className="mb-4">
          <h2 className="text-lg font-semibold mb-3 theme-text">All evaluations</h2>
          <div className="flex flex-wrap gap-3 mb-3">
            <input
              type="text"
              placeholder="Search by name or category..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="px-3 py-1.5 text-sm border theme-border rounded-lg theme-surface theme-text min-w-[200px]"
            />
            <select
              value={categoryFilter}
              onChange={(e) => setCategoryFilter(e.target.value)}
              className="px-3 py-1.5 text-sm border theme-border rounded-lg theme-surface theme-text"
            >
              <option value="">All categories</option>
              {categories.map((c) => (
                <option key={c} value={c}>{CATEGORY_LABELS[c] || c}</option>
              ))}
            </select>
            <select
              value={passFilter}
              onChange={(e) => setPassFilter(e.target.value as 'all' | 'pass' | 'fail')}
              className="px-3 py-1.5 text-sm border theme-border rounded-lg theme-surface theme-text"
            >
              <option value="all">All</option>
              <option value="pass">Pass only</option>
              <option value="fail">Fail only</option>
            </select>
            <select
              value={scopeFilter}
              onChange={(e) => setScopeFilter(e.target.value as 'all' | 'run' | 'step' | 'message')}
              className="px-3 py-1.5 text-sm border theme-border rounded-lg theme-surface theme-text"
            >
              <option value="all">All scopes</option>
              <option value="run">Run-level</option>
              <option value="step">Step-level</option>
              <option value="message">Message-level</option>
            </select>
          </div>
          <p className="text-xs theme-text-secondary">
            Showing {filteredEvals.length} of {allEvals.length} evals
          </p>
        </div>

        <div className="space-y-2">
          {filteredEvals.length === 0 ? (
            <div className="p-6 text-center theme-text-secondary theme-elevated rounded-xl">
              No evaluations match the filters.
            </div>
          ) : (
            filteredEvals.map((ev, idx) => {
              const score = typeof ev.score === 'number' && isFinite(ev.score) ? ev.score : 0;
              const name = safeStr(ev.eval_name);
              const key = `${ev.eval_name ?? idx}-${idx}`;
              const isExpanded = expandedEval === key;

              return (
                <div
                  key={key}
                  className="border theme-border rounded-xl overflow-hidden theme-surface"
                >
                  <button
                    type="button"
                    onClick={() => setExpandedEval(isExpanded ? null : key)}
                    className="w-full px-4 py-3 flex items-center gap-3 text-left hover:bg-[var(--color-fill-ghost-hover)] transition-colors"
                  >
                    <span className="theme-text-muted">{isExpanded ? '\u25BC' : '\u25B6'}</span>
                    <span
                      className={`w-2.5 h-2.5 rounded-full flex-shrink-0 ${
                        ev.pass ? 'bg-[var(--color-status-success)]' : 'bg-[var(--color-status-error)]'
                      }`}
                    />
                    <span className="text-sm font-medium theme-text truncate flex-1">
                      {name || 'Invalid record'}
                    </span>
                    <span className="text-xs px-2 py-0.5 theme-elevated theme-text-secondary rounded">
                      {CATEGORY_LABELS[ev.category] || safeStr(ev.category)}
                    </span>
                    <span className="text-sm font-mono theme-text-secondary w-14 text-right">
                      {fmtScore(ev.score)}
                    </span>
                    <span
                      className={`text-xs font-semibold px-2 py-0.5 rounded ${
                        ev.pass
                          ? 'bg-[var(--color-status-success-bg)] text-[var(--color-status-success)]'
                          : 'bg-[var(--color-status-error-bg)] text-[var(--color-status-error)]'
                      }`}
                    >
                      {ev.pass ? 'PASS' : 'FAIL'}
                    </span>
                  </button>
                  {isExpanded && (
                    <div className="px-4 pb-4 pt-0 border-t theme-border">
                      <EvalExplainability eval={ev} />
                    </div>
                  )}
                </div>
              );
            })
          )}
        </div>

        <div className="mt-6">
          <Link
            href="/evals"
            className="text-sm theme-text-secondary hover:underline"
          >
            ← Back to Evaluation Dashboard
          </Link>
        </div>
      </div>
    </div>
  );
}
