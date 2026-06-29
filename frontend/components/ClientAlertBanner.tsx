'use client';

import { useState } from 'react';
import { ClientAlert, acknowledgeAlert } from '@/lib/api';

interface ClientAlertBannerProps {
  alerts: ClientAlert[];
  tenantId: string;
  onDismiss?: (alertId: string) => void;
}

const SEVERITY_STYLES: Record<string, { bg: string; border: string; text: string }> = {
  critical: {
    bg: 'bg-red-50 dark:bg-red-950/30',
    border: 'border-red-200 dark:border-red-800',
    text: 'text-red-800 dark:text-red-200',
  },
  warning: {
    bg: 'bg-amber-50 dark:bg-amber-950/30',
    border: 'border-amber-200 dark:border-amber-800',
    text: 'text-amber-800 dark:text-amber-200',
  },
  info: {
    bg: 'bg-blue-50 dark:bg-blue-950/30',
    border: 'border-blue-200 dark:border-blue-800',
    text: 'text-blue-800 dark:text-blue-200',
  },
};

export default function ClientAlertBanner({ alerts, tenantId, onDismiss }: ClientAlertBannerProps) {
  const [dismissed, setDismissed] = useState<Set<string>>(new Set());

  if (!alerts || alerts.length === 0) return null;

  const visible = alerts.filter((a) => !dismissed.has(a.alert_id));
  if (visible.length === 0) return null;

  const handleDismiss = async (alertId: string) => {
    try {
      await acknowledgeAlert(tenantId, alertId);
      setDismissed((prev) => new Set(prev).add(alertId));
      onDismiss?.(alertId);
    } catch {
      // Still dismiss locally even if API fails
      setDismissed((prev) => new Set(prev).add(alertId));
    }
  };

  return (
    <div className="space-y-2 mb-4">
      {visible.map((alert) => {
        const style = SEVERITY_STYLES[alert.severity] || SEVERITY_STYLES.info;
        return (
          <div
            key={alert.alert_id}
            className={`flex items-start justify-between p-3 rounded-lg border ${style.bg} ${style.border}`}
          >
            <div className="flex-1">
              <div className="flex items-center gap-2 mb-1">
                <span className={`text-xs font-semibold uppercase ${style.text}`}>
                  {alert.severity}
                </span>
                <span className="text-xs theme-text-secondary">
                  {alert.alert_type.replace(/_/g, ' ')}
                </span>
              </div>
              <p className={`text-sm ${style.text}`}>{alert.message}</p>
              <p className="text-xs theme-text-secondary mt-1">
                {new Date(alert.created_at).toLocaleString()}
              </p>
            </div>
            <button
              onClick={() => handleDismiss(alert.alert_id)}
              className="ml-3 p-1 theme-text-secondary hover:theme-text transition-colors"
              title="Dismiss"
              aria-label="Dismiss alert"
            >
              <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor" className="w-4 h-4">
                <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>
        );
      })}
    </div>
  );
}
