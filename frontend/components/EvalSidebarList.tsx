'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { fetchEvalRuns, EvalRunSummary } from '@/lib/api';

const GRADE_COLORS: Record<string, string> = {
  A: 'bg-[var(--color-status-success)]',
  B: 'bg-neutral-500',
  C: 'bg-[var(--color-status-warning)]',
  D: 'bg-neutral-600',
  F: 'bg-[var(--color-status-error)]',
};

export default function EvalSidebarList() {
  const [runs, setRuns] = useState<EvalRunSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const router = useRouter();

  useEffect(() => {
    loadRuns();
  }, []);

  async function loadRuns() {
    try {
      const data = await fetchEvalRuns(20, 0);
      setRuns(data.runs);
    } catch {
      // silently fail - sidebar is non-critical
    } finally {
      setLoading(false);
    }
  }

  if (loading) {
    return (
      <div className="p-4 text-sm theme-text-secondary text-center">
        Loading evals...
      </div>
    );
  }

  return (
    <div className="flex flex-col">
      {/* Dashboard link */}
      <button
        onClick={() => router.push('/evals')}
        className="mx-3 mt-3 mb-2 px-3 py-2 text-sm font-medium btn-primary rounded-lg transition-colors text-center"
      >
        Open Dashboard
      </button>

      {runs.length === 0 ? (
        <div className="p-4 text-sm theme-text-secondary text-center">
          No evaluated runs yet.
        </div>
      ) : (
        <div className="flex flex-col">
          {runs.map((run) => (
            <button
              key={run.run_id}
              onClick={() => router.push('/evals')}
              className="px-4 py-3 text-left border-b theme-border hover:bg-[var(--color-fill-ghost-hover)] transition-colors"
            >
              <div className="flex items-center gap-2 mb-1">
                <span className={`w-5 h-5 rounded text-xs font-bold text-white flex items-center justify-center ${GRADE_COLORS[run.grade] || 'bg-neutral-500'}`}>
                  {run.grade}
                </span>
                <span className="text-xs font-mono theme-text-secondary truncate">
                  {run.run_id.slice(0, 12)}
                </span>
              </div>
              <p className="text-xs theme-text-secondary truncate">
                {run.command || run.mode}
              </p>
              <div className="flex items-center gap-2 mt-1 text-xs">
                <span className="theme-text-secondary">
                  {typeof run.avg_score === 'number' && isFinite(run.avg_score) ? run.avg_score.toFixed(3) : '\u2014'}
                </span>
                <span className="text-[var(--color-status-success)]">{run.passed}P</span>
                <span className="text-[var(--color-status-error)]">{run.failed}F</span>
              </div>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
