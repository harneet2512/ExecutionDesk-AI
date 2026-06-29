'use client';

import { useEffect, useState, useCallback, useRef } from 'react';
import Link from 'next/link';
import { listClients, refreshClients, ClientProfile } from '@/lib/api';
import { fmtCurrency, fmtTimeAgo, fmtNumber } from '@/lib/format';
import PageSkeleton from '@/components/PageSkeleton';

const HEALTH_COLORS: Record<string, string> = {
  healthy: 'var(--color-gain)',
  good: '#2563eb',
  at_risk: '#ea580c',
  churning: 'var(--color-loss)',
  inactive: 'var(--color-text-muted)',
};

type SortKey = 'health_score' | 'total_runs' | 'total_volume_usd' | 'last_activity_at' | 'tenant_id';

export default function ClientsPage() {
  const [clients, setClients] = useState<ClientProfile[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [sortKey, setSortKey] = useState<SortKey>('health_score');
  const [sortAsc, setSortAsc] = useState(false);
  const [filterClass, setFilterClass] = useState<string>('');
  const [autoRefreshing, setAutoRefreshing] = useState(false);
  const autoRefreshAttempted = useRef(false);

  const loadClients = useCallback(async () => {
    try {
      const data = await listClients(filterClass || undefined);
      setClients(data.clients);
      setError(null);
      return data.clients;
    } catch (e: any) {
      setError(e.message || 'Failed to load clients');
      return [];
    } finally {
      setLoading(false);
    }
  }, [filterClass]);

  useEffect(() => {
    let cancelled = false;
    async function initialLoad() {
      const result = await loadClients();
      if (cancelled) return;
      if (result.length === 0 && !filterClass && !autoRefreshAttempted.current) {
        autoRefreshAttempted.current = true;
        setAutoRefreshing(true);
        try {
          await refreshClients();
          if (!cancelled) await loadClients();
        } catch {} finally {
          if (!cancelled) setAutoRefreshing(false);
        }
      }
    }
    initialLoad();
    return () => { cancelled = true; };
  }, [loadClients, filterClass]);

  const handleRefresh = async () => {
    setRefreshing(true);
    try {
      await refreshClients();
      await loadClients();
    } catch (e: any) {
      setError(e.message || 'Refresh failed');
    } finally {
      setRefreshing(false);
    }
  };

  const toggleSort = (key: SortKey) => {
    if (sortKey === key) setSortAsc(!sortAsc);
    else { setSortKey(key); setSortAsc(false); }
  };

  const sortIndicator = (key: SortKey) =>
    sortKey === key ? (sortAsc ? ' ▲' : ' ▼') : '';

  const sorted = [...clients].sort((a, b) => {
    let av: any = (a as any)[sortKey];
    let bv: any = (b as any)[sortKey];
    if (typeof av === 'string') av = av || '';
    if (typeof bv === 'string') bv = bv || '';
    const cmp = av < bv ? -1 : av > bv ? 1 : 0;
    return sortAsc ? cmp : -cmp;
  });

  const classCounts = clients.reduce<Record<string, number>>((acc, c) => {
    const cls = c.health_classification || 'inactive';
    acc[cls] = (acc[cls] || 0) + 1;
    return acc;
  }, {});

  if (loading || autoRefreshing) return <PageSkeleton title="Clients" />;

  if (error) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <div className="text-center">
          <p className="text-sm loss mb-3">{error}</p>
          <button onClick={() => { setLoading(true); loadClients(); }} className="btn-primary text-sm px-4 py-2 rounded-lg">Retry</button>
        </div>
      </div>
    );
  }

  return (
    <div className="flex-1 overflow-y-auto p-6 lg:p-8 max-w-7xl mx-auto page-enter">
      {/* Header */}
      <div className="flex items-baseline justify-between mb-6">
        <div>
          <h1 className="text-xl font-semibold theme-text">Clients</h1>
          <p className="text-sm theme-text-muted mt-0.5">
            {clients.length} total
            {classCounts.at_risk ? ` · ${classCounts.at_risk} at risk` : ''}
            {classCounts.churning ? ` · ${classCounts.churning} churning` : ''}
          </p>
        </div>
        <div className="flex gap-2">
          <select
            value={filterClass}
            onChange={(e) => { setFilterClass(e.target.value); setLoading(true); }}
            className="text-xs px-2.5 py-1.5 rounded-md border theme-border theme-surface theme-text"
          >
            <option value="">All</option>
            {['healthy', 'good', 'at_risk', 'churning', 'inactive'].map(cls => (
              <option key={cls} value={cls}>{cls.replace('_', ' ')} ({classCounts[cls] || 0})</option>
            ))}
          </select>
          <button
            onClick={handleRefresh}
            disabled={refreshing}
            className="btn-ghost text-xs px-3 py-1.5 rounded-md border theme-border"
          >
            {refreshing ? 'Refreshing...' : 'Refresh'}
          </button>
        </div>
      </div>

      {/* Health distribution */}
      <div className="grid grid-cols-5 gap-3 mb-6">
        {['healthy', 'good', 'at_risk', 'churning', 'inactive'].map(cls => (
          <button
            key={cls}
            onClick={() => setFilterClass(filterClass === cls ? '' : cls)}
            className={`metric-card !p-3 transition-all ${filterClass === cls ? 'ring-1 ring-[var(--color-focus-ring)]' : ''}`}
          >
            <div className="text-[10px] uppercase tracking-wider theme-text-muted">{cls.replace('_', ' ')}</div>
            <div className="text-xl font-bold tabular-nums" style={{ color: HEALTH_COLORS[cls] }}>
              {classCounts[cls] || 0}
            </div>
          </button>
        ))}
      </div>

      {/* Table */}
      {sorted.length === 0 ? (
        <div className="text-center py-16">
          <p className="theme-text-muted text-sm mb-3">
            {clients.length === 0
              ? 'No client profiles yet. Scores are computed from activity.'
              : 'No clients match the selected filter.'}
          </p>
          {clients.length === 0 && (
            <button onClick={handleRefresh} disabled={refreshing} className="btn-primary text-sm px-4 py-2 rounded-lg">
              {refreshing ? 'Computing...' : 'Compute Health'}
            </button>
          )}
        </div>
      ) : (
        <div className="border theme-border rounded-lg overflow-hidden">
          <table className="data-table">
            <thead>
              <tr>
                <th className="sortable" onClick={() => toggleSort('tenant_id')}>Client{sortIndicator('tenant_id')}</th>
                <th className="sortable" onClick={() => toggleSort('health_score')}>Health{sortIndicator('health_score')}</th>
                <th>Status</th>
                <th className="sortable num" onClick={() => toggleSort('total_runs')}>Runs{sortIndicator('total_runs')}</th>
                <th className="sortable num" onClick={() => toggleSort('total_volume_usd')}>Volume{sortIndicator('total_volume_usd')}</th>
                <th className="sortable" onClick={() => toggleSort('last_activity_at')}>Last Active{sortIndicator('last_activity_at')}</th>
              </tr>
            </thead>
            <tbody>
              {sorted.map((c) => {
                const color = HEALTH_COLORS[c.health_classification] || HEALTH_COLORS.inactive;
                return (
                  <tr key={c.tenant_id}>
                    <td>
                      <Link href={`/clients/${c.tenant_id}`} className="text-sm font-medium text-[var(--color-link)] hover:underline">
                        {c.display_name || c.tenant_id}
                      </Link>
                    </td>
                    <td>
                      <div className="flex items-center gap-2">
                        <div className="w-16 h-1.5 rounded-full" style={{ backgroundColor: 'var(--color-border)' }}>
                          <div
                            className="h-1.5 rounded-full transition-all"
                            style={{ width: `${Math.min(100, c.health_score)}%`, backgroundColor: color }}
                          />
                        </div>
                        <span className="text-xs font-semibold tabular-nums" style={{ color }}>
                          {typeof c.health_score === 'number' && isFinite(c.health_score) ? c.health_score.toFixed(0) : '—'}
                        </span>
                      </div>
                    </td>
                    <td>
                      <span className="text-[10px] font-semibold uppercase tracking-wider px-1.5 py-0.5 rounded" style={{
                        color,
                        backgroundColor: `color-mix(in srgb, ${color} 12%, transparent)`,
                      }}>
                        {c.health_classification}
                      </span>
                    </td>
                    <td className="num tabular-nums">
                      {fmtNumber(c.total_runs)}
                      {c.failed_runs > 0 && (
                        <span className="loss ml-1 text-[10px]">({c.failed_runs} fail)</span>
                      )}
                    </td>
                    <td className="num tabular-nums">{fmtCurrency(c.total_volume_usd)}</td>
                    <td className="tabular-nums theme-text-muted text-xs">
                      {c.last_activity_at ? fmtTimeAgo(c.last_activity_at) : 'Never'}
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
