import React from 'react';
import { type HealthStatus, type Capabilities, checkHealth } from '@/lib/api';

export interface ChatBannersProps {
  healthStatus: HealthStatus | null;
  healthChecked: boolean;
  capabilities: Capabilities | null;
  loadMsgCircuitOpen: boolean;
  onRetryLoad: () => void;
  onHealthRecheck: (health: HealthStatus | null) => void;
}

export default function ChatBanners({
  healthStatus,
  healthChecked,
  capabilities,
  loadMsgCircuitOpen,
  onRetryLoad,
  onHealthRecheck,
}: ChatBannersProps) {
  return (
    <>
      {/* LIVE-disabled banner: shown before user can attempt to confirm a LIVE trade */}
      {healthChecked && capabilities && capabilities.live_trading_enabled === false && (
        <div className="px-6 py-2 border-b border-[var(--color-status-warning)]/20 bg-[var(--color-status-warning-bg)] flex items-center gap-2">
          <span className="text-[var(--color-status-warning)] text-sm font-medium">LIVE trading is disabled.</span>
          <span className="text-[var(--color-status-warning)] text-xs">
            {capabilities.remediation || 'Set TRADING_DISABLE_LIVE=false and ENABLE_LIVE_TRADING=true, then restart backend.'}
          </span>
          <span className="text-[var(--color-status-warning)] text-xs ml-auto">PAPER mode is always available.</span>
        </div>
      )}

      {/* Health gate: block UI when backend schema is unhealthy */}
      {healthChecked && healthStatus && !healthStatus.ok && (
        <div className="flex-1 flex items-center justify-center theme-bg">
          <div className="max-w-md mx-auto p-8 theme-surface rounded-xl shadow-lg border border-[var(--color-status-warning)]/20">
            <div className="flex items-center gap-3 mb-4">
              <span className="text-2xl">&#9888;</span>
              <h2 className="text-lg font-semibold theme-text">
                Database Setup Required
              </h2>
            </div>
            <p className="text-sm theme-text-secondary mb-4">
              {healthStatus.message}
            </p>
            {healthStatus.pending_list && healthStatus.pending_list.length > 0 && (
              <div className="mb-4">
                <p className="text-xs font-medium theme-text-secondary mb-2">
                  Pending migrations:
                </p>
                <ul className="text-xs theme-text-muted space-y-1 max-h-32 overflow-y-auto">
                  {healthStatus.pending_list.map((m) => (
                    <li key={m} className="font-mono">{m}</li>
                  ))}
                </ul>
              </div>
            )}
            {healthStatus.migrate_cmd && (
              <div className="mb-4">
                <p className="text-xs font-medium theme-text-secondary mb-2">
                  To apply migrations, restart the backend:
                </p>
                <div className="relative">
                  <pre className="bg-neutral-900 dark:bg-neutral-950 text-neutral-100 px-3 py-2 rounded text-xs overflow-x-auto font-mono">
                    {healthStatus.migrate_cmd}
                  </pre>
                  <button
                    onClick={async () => {
                      try {
                        await navigator.clipboard.writeText(healthStatus.migrate_cmd || '');
                      } catch (e) {
                        if (process.env.NODE_ENV === 'development') console.error('Failed to copy:', e);
                      }
                    }}
                    className="absolute top-2 right-2 p-1 rounded bg-neutral-700 hover:bg-neutral-600 text-neutral-300 transition-colors"
                    title="Copy command"
                  >
                    <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" />
                    </svg>
                  </button>
                </div>
              </div>
            )}
            {process.env.NODE_ENV === 'development' && healthStatus.db_path && (
              <div className="mb-4">
                <p className="text-xs font-medium theme-text-secondary mb-1">
                  Database path:
                </p>
                <p className="text-xs theme-text-muted font-mono break-all">
                  {healthStatus.db_path}
                </p>
              </div>
            )}
            {healthStatus.current_version !== undefined && healthStatus.required_version !== undefined && (
              <div className="mb-4 text-xs theme-text-secondary">
                Migration status: {healthStatus.current_version} / {healthStatus.required_version}
              </div>
            )}
            <button
              onClick={async () => {
                const health = await checkHealth();
                onHealthRecheck(health);
              }}
              className="px-4 py-2 btn-primary rounded-lg text-sm font-medium transition-colors"
            >
              Retry
            </button>
          </div>
        </div>
      )}
    </>
  );
}

/**
 * Circuit breaker retry banner - rendered inside the main content area
 */
export function CircuitBreakerBanner({
  loadMsgCircuitOpen,
  onRetryLoad,
}: Pick<ChatBannersProps, 'loadMsgCircuitOpen' | 'onRetryLoad'>) {
  if (!loadMsgCircuitOpen) return null;
  return (
    <div className="px-6 py-2 bg-[var(--color-status-warning-bg)] border-b border-[var(--color-status-warning)]/20 flex items-center justify-between">
      <span className="text-sm text-[var(--color-status-warning)]">
        Message loading failed repeatedly. Messages may be stale.
      </span>
      <button
        onClick={onRetryLoad}
        className="px-3 py-1 text-xs font-medium btn-primary rounded transition-colors"
      >
        Retry
      </button>
    </div>
  );
}
