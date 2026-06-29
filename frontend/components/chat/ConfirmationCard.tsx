import React from 'react';
import SelectionPanel, { type SelectionData } from '@/components/SelectionPanel';
import FinancialInsightCard from '@/components/FinancialInsightCard';
import { type HealthStatus, type Capabilities } from '@/lib/api';

export interface ConfirmationCardProps {
  messageId: string;
  metadata: {
    intent: string;
    confirmation_id?: string;
    pending_trade?: {
      side?: string;
      asset?: string;
      amount_usd?: number;
      mode?: string;
    };
    preconfirm_insight?: any;
    financial_insight?: any;
    selection_result?: SelectionData | null;
    news_enabled?: boolean;
    status?: string;
  };
  onConfirm: (confirmationId: string) => void;
  onCancel: (confirmationId: string) => void;
  confirming: boolean;
  loading: boolean;
  capabilities: Capabilities | null;
  healthStatus: HealthStatus | null;
  newsEnabled: boolean;
}

export default function ConfirmationCard({
  messageId,
  metadata,
  onConfirm,
  onCancel,
  confirming,
  loading,
  capabilities,
  healthStatus,
  newsEnabled,
}: ConfirmationCardProps) {
  const preconfirmInsight = metadata?.preconfirm_insight || metadata?.financial_insight || null;
  const isLiveTrade = metadata?.pending_trade?.mode === 'LIVE';
  const liveBlocked = isLiveTrade && (
    capabilities?.live_trading_enabled === false ||
    healthStatus?.config?.live_execution_allowed === false
  );
  const confirmationId = metadata?.confirmation_id;
  const buttonsDisabled = loading || confirming || !confirmationId;

  return (
    <div className="mt-4 p-4 theme-surface rounded-xl border theme-border-strong shadow-sm">
      <p className="text-sm font-medium mb-3 theme-text">
        Action Required
      </p>

      {/* Selection Panel - shown when asset was auto-selected */}
      {metadata?.selection_result && (
        <div className="mb-3">
          <SelectionPanel selection={metadata.selection_result as SelectionData} />
        </div>
      )}

      {/* Financial Insight Card -- always rendered when news enabled (INV-7). */}
      <div className="mb-3">
        <FinancialInsightCard
          insight={preconfirmInsight}
          newsEnabled={metadata?.news_enabled ?? newsEnabled}
        />
      </div>

      {/* LIVE-disabled defense: block LIVE confirmation entirely */}
      {liveBlocked ? (
        <div className="mb-3 px-3 py-2 bg-[var(--color-status-warning-bg)] border border-[var(--color-status-warning)]/20 rounded-lg">
          <p className="text-xs font-semibold text-[var(--color-status-warning)]">Confirmation required</p>
          <p className="text-sm text-[var(--color-status-warning)] leading-snug">
            To execute this LIVE trade, confirm it in your Coinbase wallet.
          </p>
          <p className="text-xs theme-text-muted leading-snug">
            No funds move until you confirm.
          </p>
        </div>
      ) : (
        <div className="flex gap-3">
          <button
            onClick={() => {
              if (!confirmationId) return;
              onConfirm(confirmationId);
            }}
            disabled={buttonsDisabled}
            className="px-4 py-2 bg-[var(--color-status-success)] hover:opacity-90 text-white rounded-lg text-sm font-medium transition-colors disabled:opacity-50"
          >
            Confirm Trade
          </button>
          <button
            onClick={() => {
              if (!confirmationId) return;
              onCancel(confirmationId);
            }}
            disabled={buttonsDisabled}
            className="px-4 py-2 bg-[var(--color-status-error-bg)] hover:opacity-90 text-[var(--color-status-error)] rounded-lg text-sm font-medium transition-colors disabled:opacity-50"
          >
            Cancel
          </button>
        </div>
      )}

      {!confirmationId && (
        <p className="mt-2 text-xs text-[var(--color-status-error)]">
          Error: Missing confirmation ID. Cannot proceed.
        </p>
      )}
    </div>
  );
}
