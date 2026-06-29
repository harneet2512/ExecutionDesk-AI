'use client';

import { useEffect, useState, useMemo } from 'react';
import Link from 'next/link';
import { listRuns, Run } from '@/lib/api';
import { getStatusClasses, getStatusLabel, getModeClasses } from '@/lib/statusColors';
import { fmtTimeAgo, fmtDateTime } from '@/lib/format';
import PageSkeleton from '@/components/PageSkeleton';

type SortKey = 'created_at' | 'status' | 'execution_mode';

export default function RunsPage() {
  const [runs, setRuns] = useState<Run[]>([]);
  const [loading, setLoading] = useState(true);
  const [sortKey, setSortKey] = useState<SortKey>('created_at');
  const [sortAsc, setSortAsc] = useState(false);
  const [modeFilter, setModeFilter] = useState('');
  const [statusFilter, setStatusFilter] = useState('');

  useEffect(() => { loadRuns(); }, []);

  async function loadRuns() {
    try {
      setRuns(await listRuns());
    } catch (error) {
      if (process.env.NODE_ENV === 'development') console.error('Failed to load runs:', error);
    } finally {
      setLoading(false);
    }
  }

  function toggleSort(key: SortKey) {
    if (sortKey === key) setSortAsc(!sortAsc);
    else { setSortKey(key); setSortAsc(false); }
  }

  const sortIndicator = (key: SortKey) =>
    sortKey === key ? (sortAsc ? ' ▲' : ' ▼') : '';

  const filtered = useMemo(() => {
    let list = [...runs];
    if (modeFilter) list = list.filter(r => r.execution_mode === modeFilter);
    if (statusFilter) list = list.filter(r => r.status === statusFilter);
    list.sort((a, b) => {
      const av = a[sortKey] ?? '';
      const bv = b[sortKey] ?? '';
      const cmp = av < bv ? -1 : av > bv ? 1 : 0;
      return sortAsc ? cmp : -cmp;
    });
    return list;
  }, [runs, sortKey, sortAsc, modeFilter, statusFilter]);

  const statuses = useMemo(() => Array.from(new Set(runs.map(r => r.status))).sort(), [runs]);
  const modes = useMemo(() => Array.from(new Set(runs.map(r => r.execution_mode))).sort(), [runs]);

  const statusCounts = useMemo(() => {
    const counts: Record<string, number> = {};
    runs.forEach(r => { counts[r.status] = (counts[r.status] || 0) + 1; });
    return counts;
  }, [runs]);

  if (loading) return <PageSkeleton title="Trading Runs" />;

  return (
    <div className="p-6 lg:p-8 max-w-7xl mx-auto page-enter">
      {/* Header */}
      <div className="flex items-baseline justify-between mb-6">
        <div>
          <h1 className="text-xl font-semibold theme-text">Trading Runs</h1>
          <p className="text-sm theme-text-muted mt-0.5">
            {runs.length} total{statusCounts['COMPLETED'] ? ` · ${statusCounts['COMPLETED']} completed` : ''}
            {statusCounts['FAILED'] ? ` · ${statusCounts['FAILED']} failed` : ''}
          </p>
        </div>
      </div>

      {/* Filters */}
      {runs.length > 0 && (
        <div className="flex gap-2 mb-4">
          <select
            value={statusFilter}
            onChange={e => setStatusFilter(e.target.value)}
            className="text-xs px-2.5 py-1.5 rounded-md border theme-border theme-surface theme-text"
          >
            <option value="">All statuses</option>
            {statuses.map(s => <option key={s} value={s}>{s} ({statusCounts[s] || 0})</option>)}
          </select>
          <select
            value={modeFilter}
            onChange={e => setModeFilter(e.target.value)}
            className="text-xs px-2.5 py-1.5 rounded-md border theme-border theme-surface theme-text"
          >
            <option value="">All modes</option>
            {modes.map(m => <option key={m} value={m}>{m}</option>)}
          </select>
          {(statusFilter || modeFilter) && (
            <button
              onClick={() => { setStatusFilter(''); setModeFilter(''); }}
              className="text-xs px-2 py-1 btn-ghost rounded"
            >
              Clear
            </button>
          )}
        </div>
      )}

      {/* Table */}
      {filtered.length === 0 ? (
        <div className="text-center py-16">
          <p className="theme-text-secondary text-sm">
            {runs.length === 0
              ? 'No trading runs yet. Start a trade from the chat.'
              : 'No runs match the current filters.'}
          </p>
        </div>
      ) : (
        <div className="border theme-border rounded-lg overflow-hidden">
          <table className="data-table">
            <thead>
              <tr className="theme-elevated">
                <th>Run</th>
                <th className="sortable" onClick={() => toggleSort('status')}>
                  Status{sortIndicator('status')}
                </th>
                <th className="sortable" onClick={() => toggleSort('execution_mode')}>
                  Mode{sortIndicator('execution_mode')}
                </th>
                <th>Command</th>
                <th className="sortable" onClick={() => toggleSort('created_at')}>
                  Time{sortIndicator('created_at')}
                </th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((run) => {
                const sc = getStatusClasses(run.status);
                const mc = getModeClasses(run.execution_mode);
                return (
                  <tr key={run.run_id}>
                    <td>
                      <Link
                        href={`/runs/${run.run_id}`}
                        className="font-mono text-xs text-[var(--color-link)] hover:underline"
                      >
                        {run.run_id.slice(0, 10)}
                      </Link>
                    </td>
                    <td>
                      <span className={`badge ${sc.bg} ${sc.text}`}>
                        {getStatusLabel(run.status)}
                      </span>
                    </td>
                    <td>
                      <span className={`badge ${mc.bg} ${mc.text}`}>
                        {run.execution_mode}
                      </span>
                    </td>
                    <td className="max-w-[240px] truncate theme-text-secondary text-xs">
                      {(run as any).command_text || '—'}
                    </td>
                    <td className="tabular-nums text-xs theme-text-secondary" title={fmtDateTime(run.created_at)}>
                      {fmtTimeAgo(run.created_at)}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
