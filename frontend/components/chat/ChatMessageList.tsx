import React from 'react';
import { type Message, type HealthStatus, type Capabilities } from '@/lib/api';
import { type TradeStep } from '@/components/TradeProcessingCard';
import { type Step } from '@/components/StepsDrawer';
import RunSummary from '@/components/RunSummary';
import RunCharts from '@/components/RunCharts';
import TradeReceipt from '@/components/TradeReceipt';
import PortfolioCard from '@/components/PortfolioCard';
import ChatEmptyState from '@/components/ChatEmptyState';
import MarkdownMessage from '@/components/MarkdownMessage';
import NarrativeLines from '@/components/NarrativeLines';
import TradeProcessingCard from '@/components/TradeProcessingCard';
import FinancialInsightCard from '@/components/FinancialInsightCard';
import OrderTicketCard from '@/components/OrderTicketCard';
import ConfirmationCard from '@/components/chat/ConfirmationCard';
import { type TradeTicket } from '@/lib/api';

// Strip run_id / confirmation_id from displayed message content (P3.3)
function stripInternalIds(content: string): string {
  if (!content) return content;
  return content
    .replace(/\brun_[a-zA-Z0-9_-]{8,}\b/g, '')
    .replace(/\bconf_[a-zA-Z0-9_-]{8,}\b/g, '')
    .replace(/[^\S\n]{2,}/g, ' ')
    .trim();
}

function getPortfolioSnapshotCardData(msg: Message): any | null {
  return (
    msg.metadata_json?.portfolio_snapshot_card_data ||
    msg.metadata_json?.portfolio_brief ||
    null
  );
}

export interface ChatMessageListProps {
  messages: Message[];
  runIntents: Record<string, string>;
  completedRuns: Record<string, string>;
  actedConfirmations: Set<string>;
  newsEnabled: boolean;
  loading: boolean;
  currentRunId: string | null;
  currentStepName: string | null;
  elapsedTime: number;
  steps: Step[];
  copiedMessageId: string | null;
  capabilities: Capabilities | null;
  healthStatus: HealthStatus | null;
  currentTicket: TradeTicket | null;
  sseConnected: boolean;
  onSuggestionClick: (text: string) => void;
  onCopyMessage: (messageId: string, content: string) => void;
  onConfirm: (confirmationId: string) => void;
  onCancel: (confirmationId: string) => void;
  onTradeComplete: (completedStatus: string, runId: string) => void;
  onRetry: (messageId: string, messages: Message[]) => void;
  onTicketExecuted: (ticketId: string, receipt: any) => void;
  onTicketCancelled: (ticketId: string) => void;
  confirmingIds: Set<string>;
  messagesEndRef: React.RefObject<HTMLDivElement>;
}

export default function ChatMessageList({
  messages,
  runIntents,
  completedRuns,
  actedConfirmations,
  newsEnabled,
  loading,
  currentRunId,
  currentStepName,
  elapsedTime,
  steps,
  copiedMessageId,
  capabilities,
  healthStatus,
  currentTicket,
  sseConnected,
  onSuggestionClick,
  onCopyMessage,
  onConfirm,
  onCancel,
  onTradeComplete,
  onRetry,
  onTicketExecuted,
  onTicketCancelled,
  confirmingIds,
  messagesEndRef,
}: ChatMessageListProps) {
  if (messages.length === 0) {
    return (
      <div className="flex-1 overflow-y-auto px-6 py-6">
        <ChatEmptyState onSelectSuggestion={onSuggestionClick} />
      </div>
    );
  }

  // D2: Pre-compute: for each run_id, find the index of its last message
  const lastIndexByRunId = new Map<string, number>();
  messages.forEach((m, i) => { if (m.run_id) lastIndexByRunId.set(m.run_id, i); });

  return (
    <div className="flex-1 overflow-y-auto px-6 py-6">
      <div className="max-w-4xl mx-auto space-y-6">
        {messages.map((msg, msgIdx) => {
          // Only render the card on the last message for this run_id
          const shouldRenderCard = msg.run_id ? lastIndexByRunId.get(msg.run_id) === msgIdx : true;
          return (
            <div
              key={msg.message_id}
              className={`group flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}
            >
              <div className="relative">
                <div
                  className={`max-w-3xl px-5 py-3.5 rounded-2xl ${msg.role === 'user'
                    ? 'bg-neutral-800 dark:bg-neutral-200 text-white dark:text-neutral-900'
                    : 'theme-elevated theme-text'
                    }`}
                >
                  {msg.role === 'assistant' ? (
                    msg.metadata_json?.narrative_structured ? (
                      <NarrativeLines structured={msg.metadata_json.narrative_structured} fallbackContent={stripInternalIds(msg.content)} className="text-sm" />
                    ) : (
                      <MarkdownMessage content={stripInternalIds(msg.content)} className="text-sm" />
                    )
                  ) : (
                    <div className="whitespace-pre-wrap text-sm leading-relaxed">{msg.content}</div>
                  )}

                  {/* Confirmation Card (hidden after user confirms/cancels) */}
                  {msg.role === 'assistant' && msg.metadata_json?.intent === 'TRADE_CONFIRMATION_PENDING' && !actedConfirmations.has(msg.metadata_json?.confirmation_id) && (
                    <ConfirmationCard
                      messageId={msg.message_id}
                      metadata={msg.metadata_json}
                      onConfirm={onConfirm}
                      onCancel={onCancel}
                      confirming={confirmingIds.has(msg.metadata_json?.confirmation_id)}
                      loading={loading}
                      capabilities={capabilities}
                      healthStatus={healthStatus}
                      newsEnabled={newsEnabled}
                    />
                  )}

                  {/* Portfolio analysis for non-run messages */}
                  {msg.role === 'assistant' && !msg.run_id && (() => {
                    const intent = msg.metadata_json?.intent;
                    const snapshotCardData = getPortfolioSnapshotCardData(msg);
                    const isPortfolioAnalysisResult =
                      intent === 'PORTFOLIO_ANALYSIS' ||
                      (!!snapshotCardData && intent !== 'TRADE_CONFIRMATION_PENDING');
                    if (!isPortfolioAnalysisResult || !snapshotCardData) return null;
                    return (
                      <div className="mt-3 pt-3 border-t theme-border">
                        <PortfolioCard runId={`inline_${msg.message_id}`} brief={snapshotCardData} />
                        {(msg.metadata_json?.preconfirm_insight || msg.metadata_json?.financial_insight) && (
                          <div className="mt-3">
                            <FinancialInsightCard insight={(msg.metadata_json?.preconfirm_insight || msg.metadata_json?.financial_insight)} newsEnabled={newsEnabled} />
                          </div>
                        )}
                      </div>
                    );
                  })()}

                  {/* Run-based artifacts */}
                  {msg.run_id && msg.role === 'assistant' && shouldRenderCard && (() => {
                    // Determine intent from metadata or runIntents state
                    const intent = msg.metadata_json?.intent || runIntents[msg.run_id];
                    const snapshotCardData = getPortfolioSnapshotCardData(msg);
                    const isTradeConfirmationPending = intent === 'TRADE_CONFIRMATION_PENDING';
                    const isPortfolioRun = !isTradeConfirmationPending && (
                      intent === 'PORTFOLIO_ANALYSIS' ||
                      intent === 'PORTFOLIO' ||
                      !!snapshotCardData ||
                      msg.content?.includes('Portfolio Snapshot') ||
                      msg.content?.includes('Total Value:')
                    );
                    const isTradeRun = !isPortfolioRun && (intent === 'TRADE_EXECUTION' ||
                      msg.content?.includes('Executing') ||
                      (msg.content?.includes('SELL') && msg.content?.includes('$')) ||
                      (msg.content?.includes('BUY') && msg.content?.includes('$')));

                    if (isPortfolioRun) {
                      return (
                        <div className="mt-3 pt-3 border-t theme-border">
                          <PortfolioCard runId={msg.run_id} brief={snapshotCardData || undefined} />
                          {(msg.metadata_json?.preconfirm_insight || msg.metadata_json?.financial_insight) && (
                            <div className="mt-3">
                              <FinancialInsightCard insight={(msg.metadata_json?.preconfirm_insight || msg.metadata_json?.financial_insight)} newsEnabled={newsEnabled} />
                            </div>
                          )}
                        </div>
                      );
                    } else if (isTradeRun) {
                      const tradeInfo = msg.metadata_json?.pending_trade || {};
                      const side = tradeInfo.side || '';
                      const symbol = tradeInfo.asset || '';
                      const amount = tradeInfo.amount_usd || 0;
                      const mode = tradeInfo.mode || 'PAPER';

                      return (
                        <div className="mt-3 pt-3 border-t theme-border">
                          {(msg.metadata_json?.preconfirm_insight || msg.metadata_json?.financial_insight) && (
                            <div className="mb-3">
                              <FinancialInsightCard insight={(msg.metadata_json?.preconfirm_insight || msg.metadata_json?.financial_insight)} newsEnabled={newsEnabled} />
                            </div>
                          )}
                          <TradeProcessingCard
                            runId={msg.run_id}
                            side={side}
                            symbol={symbol}
                            notionalUsd={amount}
                            mode={mode}
                            sseConnected={sseConnected && msg.run_id === currentRunId}
                            steps={msg.run_id === currentRunId ? steps.map(s => ({
                              step_id: s.step_id,
                              step_name: s.step_name,
                              status: s.status,
                              description: s.description,
                              summary: s.summary,
                              duration_ms: s.duration_ms,
                              sequence: s.sequence,
                            } as TradeStep)) : []}
                            onComplete={onTradeComplete}
                            onRetry={() => onRetry(msg.message_id, messages)}
                          />
                          <TradeReceipt runId={msg.run_id} status={completedRuns[msg.run_id!]} />
                        </div>
                      );
                    } else {
                      return (
                        <div className="mt-3 pt-3 border-t theme-border">
                          <RunSummary runId={msg.run_id} />
                          <RunCharts runId={msg.run_id} />
                        </div>
                      );
                    }
                  })()}
                </div>

                {/* Copy button - appears on hover */}
                <button
                  onClick={() => onCopyMessage(msg.message_id, msg.content)}
                  className={`absolute ${msg.role === 'user' ? '-left-8' : '-right-8'} top-2 p-1.5 rounded-md transition-all ${copiedMessageId === msg.message_id
                    ? 'opacity-100 bg-[var(--color-status-success-bg)] text-[var(--color-status-success)]'
                    : 'opacity-0 group-hover:opacity-100 hover:bg-neutral-200 dark:hover:bg-neutral-700 theme-text-muted'
                    }`}
                  title={copiedMessageId === msg.message_id ? 'Copied!' : 'Copy message'}
                >
                  {copiedMessageId === msg.message_id ? (
                    <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                    </svg>
                  ) : (
                    <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" />
                    </svg>
                  )}
                </button>
              </div>
            </div>
          );
        })}

        {/* Loading indicator */}
        {loading && !(() => {
          if (!currentRunId) return false;
          const tradeIntent = runIntents[currentRunId];
          return tradeIntent === 'TRADE_EXECUTION' && messages.some(m => m.run_id === currentRunId);
        })() && (
          <div className="flex justify-start">
            <div className="theme-elevated px-5 py-3.5 rounded-2xl">
              <div className="flex items-center gap-3 theme-text-secondary">
                <div className="flex gap-1">
                  <div className="w-2 h-2 bg-neutral-500 rounded-full animate-bounce" style={{ animationDelay: '0ms' }}></div>
                  <div className="w-2 h-2 bg-neutral-500 rounded-full animate-bounce" style={{ animationDelay: '150ms' }}></div>
                  <div className="w-2 h-2 bg-neutral-500 rounded-full animate-bounce" style={{ animationDelay: '300ms' }}></div>
                </div>
                <span className="text-sm font-medium">{currentStepName || 'Processing'}</span>
                <span className="text-xs theme-text-muted">{elapsedTime}s</span>
                {elapsedTime > 30 && currentRunId && (
                  <a
                    href={`/runs/${currentRunId}`}
                    className="text-xs theme-text-secondary hover:underline"
                    target="_blank"
                  >
                    View details
                  </a>
                )}
              </div>
            </div>
          </div>
        )}

        {/* Order Ticket Card for ASSISTED_LIVE stocks */}
        {currentTicket && currentTicket.status === 'PENDING' && (
          <div className="max-w-xl">
            <OrderTicketCard
              ticket={currentTicket}
              liveDisabled={capabilities?.live_trading_enabled === false}
              onMarkExecuted={async (ticketId, receipt) => {
                await onTicketExecuted(ticketId, receipt);
              }}
              onCancel={async (ticketId) => {
                await onTicketCancelled(ticketId);
              }}
            />
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>
    </div>
  );
}
