'use client';

import { useEffect, useState, useCallback } from 'react';
import { useParams } from 'next/navigation';
import Link from 'next/link';
import {
  getClientProfile,
  listClientIssues,
  createClientIssue,
  ClientHealth,
  ClientAlert,
  ClientIssue,
} from '@/lib/api';
import PageSkeleton from '@/components/PageSkeleton';
import ClientHealthGauge from '@/components/ClientHealthGauge';
import ClientAlertBanner from '@/components/ClientAlertBanner';
import IssueThread from '@/components/IssueThread';

type TabId = 'overview' | 'issues' | 'alerts';

export default function ClientDetailPage() {
  const params = useParams();
  const tenantId = params.tenantId as string;
  const [health, setHealth] = useState<ClientHealth | null>(null);
  const [alerts, setAlerts] = useState<ClientAlert[]>([]);
  const [issues, setIssues] = useState<ClientIssue[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<TabId>('overview');
  const [showNewIssue, setShowNewIssue] = useState(false);
  const [newIssueTitle, setNewIssueTitle] = useState('');
  const [newIssueDesc, setNewIssueDesc] = useState('');
  const [newIssuePriority, setNewIssuePriority] = useState('medium');

  const loadProfile = useCallback(async () => {
    try {
      const data = await getClientProfile(tenantId);
      setHealth(data.health);
      setAlerts(data.alerts);
      setIssues(data.issues);
      setError(null);
    } catch (e: any) {
      setError(e.message || 'Failed to load client profile');
    } finally {
      setLoading(false);
    }
  }, [tenantId]);

  useEffect(() => {
    loadProfile();
  }, [loadProfile]);

  const handleCreateIssue = async () => {
    if (!newIssueTitle.trim()) return;
    try {
      await createClientIssue(tenantId, {
        title: newIssueTitle.trim(),
        description: newIssueDesc.trim() || undefined,
        priority: newIssuePriority,
      });
      setShowNewIssue(false);
      setNewIssueTitle('');
      setNewIssueDesc('');
      // Reload issues
      const issuesData = await listClientIssues(tenantId);
      setIssues(issuesData.issues);
    } catch {
      // Silently handle
    }
  };

  if (loading) return <PageSkeleton title="Client Detail" rows={6} />;

  if (error) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <div className="text-center">
          <p className="text-[var(--color-status-error)] mb-4">{error}</p>
          <button onClick={() => { setLoading(true); loadProfile(); }} className="btn-primary">Retry</button>
        </div>
      </div>
    );
  }

  if (!health) return null;

  const COMPONENT_LABELS: Record<string, string> = {
    activity: 'Activity (30%)',
    success_rate: 'Success Rate (25%)',
    volume_trend: 'Volume Trend (20%)',
    error_frequency: 'Error Frequency (15%)',
    feature_adoption: 'Feature Adoption (10%)',
  };

  const tabs: { id: TabId; label: string; count?: number }[] = [
    { id: 'overview', label: 'Overview' },
    { id: 'issues', label: 'Issues', count: issues.length },
    { id: 'alerts', label: 'Alerts', count: alerts.length },
  ];

  return (
    <div className="flex-1 overflow-y-auto">
      <div className="p-6 max-w-7xl mx-auto">
        {/* Breadcrumb */}
        <div className="flex items-center gap-2 mb-4 text-sm theme-text-secondary">
          <Link href="/clients" className="hover:underline">Clients</Link>
          <span>/</span>
          <span className="theme-text font-medium">{tenantId}</span>
        </div>

        {/* Header */}
        <div className="flex items-baseline justify-between mb-6">
          <h1 className="text-xl font-semibold theme-text">{tenantId}</h1>
          <button onClick={() => { setLoading(true); loadProfile(); }} className="btn-ghost text-xs px-3 py-1.5 rounded-md border theme-border">Refresh</button>
        </div>

        {/* Alerts */}
        <ClientAlertBanner
          alerts={alerts}
          tenantId={tenantId}
          onDismiss={() => loadProfile()}
        />

        {/* Tabs */}
        <div className="flex gap-1 mb-6 border-b theme-border">
          {tabs.map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
                activeTab === tab.id
                  ? 'border-[var(--color-accent)] theme-text'
                  : 'border-transparent theme-text-secondary hover:theme-text'
              }`}
            >
              {tab.label}
              {tab.count !== undefined && tab.count > 0 && (
                <span className="ml-1.5 px-1.5 py-0.5 text-xs rounded-full theme-elevated">
                  {tab.count}
                </span>
              )}
            </button>
          ))}
        </div>

        {/* Overview Tab */}
        {activeTab === 'overview' && (
          <div className="space-y-6">
            {/* Health gauge + components */}
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
              <div className="p-6 theme-elevated border theme-border rounded-xl flex flex-col items-center justify-center relative">
                <ClientHealthGauge score={health.score} classification={health.classification} size={140} />
              </div>

              <div className="lg:col-span-2 p-6 theme-elevated border theme-border rounded-xl">
                <h3 className="text-sm font-semibold theme-text uppercase tracking-wide mb-4">Health Components</h3>
                <div className="space-y-3">
                  {Object.entries(health.components).map(([key, value]) => (
                    <div key={key}>
                      <div className="flex justify-between text-sm mb-1">
                        <span className="theme-text-secondary">{COMPONENT_LABELS[key] || key}</span>
                        <span className="theme-text font-medium">
                          {typeof value === 'number' && isFinite(value) ? value.toFixed(1) : '—'}
                        </span>
                      </div>
                      <div className="w-full h-2 bg-neutral-200 dark:bg-neutral-700 rounded-full">
                        <div
                          className="h-2 rounded-full transition-all"
                          style={{
                            width: `${Math.min(100, typeof value === 'number' ? value : 0)}%`,
                            backgroundColor: value >= 70 ? 'var(--color-status-success)' : value >= 40 ? 'var(--color-status-warning)' : 'var(--color-status-error)',
                          }}
                        />
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </div>

            {/* Stats grid */}
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              <div className="p-4 theme-elevated border theme-border rounded-xl">
                <p className="text-xs theme-text-secondary uppercase tracking-wide mb-1">Total Runs</p>
                <p className="text-2xl font-bold theme-text">{health.stats.total_runs}</p>
              </div>
              <div className="p-4 theme-elevated border theme-border rounded-xl">
                <p className="text-xs theme-text-secondary uppercase tracking-wide mb-1">Success Rate</p>
                <p className="text-2xl font-bold text-[var(--color-status-success)]">
                  {health.stats.total_runs > 0
                    ? `${((health.stats.successful_runs / health.stats.total_runs) * 100).toFixed(1)}%`
                    : '—'}
                </p>
              </div>
              <div className="p-4 theme-elevated border theme-border rounded-xl">
                <p className="text-xs theme-text-secondary uppercase tracking-wide mb-1">Volume (USD)</p>
                <p className="text-2xl font-bold theme-text">
                  {typeof health.stats.total_volume_usd === 'number' && isFinite(health.stats.total_volume_usd)
                    ? `$${health.stats.total_volume_usd.toLocaleString(undefined, { maximumFractionDigits: 0 })}`
                    : '—'}
                </p>
              </div>
              <div className="p-4 theme-elevated border theme-border rounded-xl">
                <p className="text-xs theme-text-secondary uppercase tracking-wide mb-1">Runs (7d)</p>
                <p className="text-2xl font-bold theme-text">{health.stats.runs_7d}</p>
                {health.stats.errors_7d > 0 && (
                  <p className="text-xs text-[var(--color-status-error)] mt-1">{health.stats.errors_7d} errors</p>
                )}
              </div>
            </div>
          </div>
        )}

        {/* Issues Tab */}
        {activeTab === 'issues' && (
          <div className="space-y-4">
            <div className="flex justify-between items-center">
              <h3 className="text-lg font-semibold theme-text">Issues</h3>
              <button onClick={() => setShowNewIssue(!showNewIssue)} className="btn-primary text-sm">
                {showNewIssue ? 'Cancel' : 'New Issue'}
              </button>
            </div>

            {showNewIssue && (
              <div className="p-4 theme-elevated border theme-border rounded-xl space-y-3">
                <input
                  type="text"
                  value={newIssueTitle}
                  onChange={(e) => setNewIssueTitle(e.target.value)}
                  placeholder="Issue title"
                  className="w-full px-3 py-2 text-sm theme-elevated border theme-border rounded-lg theme-text placeholder:theme-text-secondary"
                />
                <textarea
                  value={newIssueDesc}
                  onChange={(e) => setNewIssueDesc(e.target.value)}
                  placeholder="Description (optional)"
                  rows={3}
                  className="w-full px-3 py-2 text-sm theme-elevated border theme-border rounded-lg theme-text placeholder:theme-text-secondary resize-none"
                />
                <div className="flex items-center gap-3">
                  <select
                    value={newIssuePriority}
                    onChange={(e) => setNewIssuePriority(e.target.value)}
                    className="px-3 py-2 text-sm theme-elevated border theme-border rounded-lg theme-text"
                  >
                    <option value="low">Low Priority</option>
                    <option value="medium">Medium Priority</option>
                    <option value="high">High Priority</option>
                    <option value="critical">Critical</option>
                  </select>
                  <button onClick={handleCreateIssue} disabled={!newIssueTitle.trim()} className="btn-primary text-sm">
                    Create Issue
                  </button>
                </div>
              </div>
            )}

            {issues.length > 0 ? (
              <div className="space-y-4">
                {issues.map((issue) => (
                  <IssueThread
                    key={issue.issue_id}
                    issue={issue}
                    tenantId={tenantId}
                    onUpdate={() => loadProfile()}
                  />
                ))}
              </div>
            ) : (
              <div className="p-8 text-center theme-text-secondary theme-elevated border theme-border rounded-xl">
                No issues found for this client.
              </div>
            )}
          </div>
        )}

        {/* Alerts Tab */}
        {activeTab === 'alerts' && (
          <div>
            {alerts.length > 0 ? (
              <ClientAlertBanner alerts={alerts} tenantId={tenantId} onDismiss={() => loadProfile()} />
            ) : (
              <div className="p-8 text-center theme-text-secondary theme-elevated border theme-border rounded-xl">
                No active alerts for this client.
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
