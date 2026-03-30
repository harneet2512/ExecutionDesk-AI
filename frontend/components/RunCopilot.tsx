'use client';

import { useState } from 'react';

interface RunCopilotProps {
  runId: string;
  run: any;
  orders: any[];
  evals: any[];
  traceArtifacts?: any;
}

function getWhatHappened(run: any, orders: any[]): string {
  const runStatus = (run?.status || '').toUpperCase();
  if (orders.length === 0) {
    if (runStatus === 'COMPLETED') return 'Run completed with no orders placed (likely a portfolio analysis or analysis-only run).';
    if (runStatus === 'FAILED') return 'Run failed before reaching order placement.';
    return `Run is currently ${runStatus.toLowerCase()}.`;
  }
  const order = orders[0];
  const orderStatus = (order.status || '').toUpperCase();
  const side = (order.side || '').toUpperCase();
  const symbol = order.symbol || 'asset';
  const notional = typeof order.notional_usd === 'number' ? `$${order.notional_usd.toFixed(2)}` : '';
  if (orderStatus === 'FILLED') {
    const filled = typeof order.filled_qty === 'number' ? order.filled_qty.toFixed(8) : '';
    const price = typeof order.avg_fill_price === 'number' ? `$${order.avg_fill_price.toFixed(2)}` : '';
    return `Run completed. ${side} order for ${notional} of ${symbol} was filled: ${filled} units @ ${price}.`;
  }
  if (orderStatus === 'SUBMITTED' || orderStatus === 'PENDING' || orderStatus === 'PENDING_FILL') {
    return `Run completed. ${side} order for ${notional} of ${symbol} was submitted to the venue. Fill not yet confirmed.`;
  }
  if (orderStatus === 'FAILED' || orderStatus === 'REJECTED') {
    return `Run completed. ${side} order for ${notional} of ${symbol} was ${orderStatus.toLowerCase()}. Reason: ${order.status_reason || 'See order details.'}`;
  }
  if (orderStatus === 'CANCELED' || orderStatus === 'EXPIRED') {
    return `Run completed. ${side} order for ${notional} of ${symbol} was ${orderStatus.toLowerCase()}.`;
  }
  return `Run status: ${run.status}. Order status: ${order.status}.`;
}

function getNextSteps(run: any, orders: any[]): string {
  const runStatus = (run?.status || '').toUpperCase();
  if (orders.length === 0) {
    if (runStatus === 'FAILED') return 'Review the Execution Trace tab to identify which node failed. Check backend logs for details.';
    return 'Run a buy or sell command to see order execution and fill confirmation.';
  }
  const order = orders[0];
  const orderStatus = (order.status || '').toUpperCase();
  if (orderStatus === 'FILLED') return 'Order successfully filled. Review PnL & Slippage tab for performance analysis.';
  if (['SUBMITTED', 'PENDING', 'PENDING_FILL', 'OPEN'].includes(orderStatus)) {
    return 'Check fill status or wait for exchange confirmation. Use the Refresh button on the trade receipt to poll the latest status.';
  }
  if (orderStatus === 'FAILED' || orderStatus === 'REJECTED') return 'Review the order status reason. You may retry by submitting a new command.';
  if (orderStatus === 'CANCELED' || orderStatus === 'EXPIRED') return 'Order was canceled or expired. Submit a new command to retry.';
  return 'Review the Orders & Fills tab for details.';
}

export default function RunCopilot({ run, orders, evals, traceArtifacts }: RunCopilotProps) {
  const [open, setOpen] = useState(false);

  const whatHappened = getWhatHappened(run, orders);
  const nextSteps = getNextSteps(run, orders);

  // Top 3 evals by score (skip N/A)
  const scoredEvals = evals
    .filter((ev: any) => typeof ev.score === 'number' && ev.score >= 0)
    .sort((a: any, b: any) => b.score - a.score)
    .slice(0, 3);

  // Evidence chips from trace artifacts
  const rankings = traceArtifacts?.rankings || [];
  const candlesBatches = traceArtifacts?.candles_batches || [];
  const hasEvidence = rankings.length > 0 || candlesBatches.length > 0;

  return (
    <div className="mb-4 border theme-border rounded-lg overflow-hidden">
      <button
        onClick={() => setOpen(v => !v)}
        className="w-full flex items-center gap-2 px-4 py-2.5 theme-elevated hover:bg-[var(--color-fill-ghost-hover)] transition-colors text-sm font-medium theme-text"
      >
        <span className="text-xs">{open ? '▼' : '▶'}</span>
        <span>Run Copilot</span>
        <span className="text-xs theme-text-secondary ml-1">— quick summary</span>
      </button>

      {open && (
        <div className="p-4 theme-surface space-y-4 text-sm">
          {/* What happened */}
          <div>
            <h4 className="text-xs font-semibold theme-text-secondary uppercase tracking-wide mb-1">What happened</h4>
            <p className="theme-text">{whatHappened}</p>
          </div>

          {/* Key drivers */}
          {scoredEvals.length > 0 && (
            <div>
              <h4 className="text-xs font-semibold theme-text-secondary uppercase tracking-wide mb-2">Key drivers (top evals)</h4>
              <div className="space-y-1.5">
                {scoredEvals.map((ev: any, i: number) => {
                  const pct = Math.max(0, Math.min(100, ev.score * 100));
                  const pass = ev.score >= 0.5;
                  return (
                    <div key={i} className="flex items-center gap-2">
                      <span className={`w-2 h-2 rounded-full flex-shrink-0 ${pass ? 'bg-[var(--color-status-success)]' : 'bg-[var(--color-status-error)]'}`} />
                      <span className="theme-text flex-1 truncate">{(ev.eval_name || '').replace(/_/g, ' ')}</span>
                      <div className="w-20 h-1.5 bg-neutral-200 dark:bg-neutral-700 rounded-full flex-shrink-0">
                        <div
                          className={`h-1.5 rounded-full ${pass ? 'bg-[var(--color-status-success)]' : 'bg-[var(--color-status-error)]'}`}
                          style={{ width: `${pct}%` }}
                        />
                      </div>
                      <span className="text-xs font-mono theme-text-secondary w-10 text-right">{ev.score.toFixed(2)}</span>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* Evidence chips */}
          {hasEvidence && (
            <div>
              <h4 className="text-xs font-semibold theme-text-secondary uppercase tracking-wide mb-2">Evidence</h4>
              <div className="flex flex-wrap gap-2">
                {rankings.length > 0 && (
                  <span className="px-2 py-1 theme-elevated rounded text-xs theme-text">
                    Rankings: {rankings.length} assets
                  </span>
                )}
                {candlesBatches.length > 0 && (
                  <span className="px-2 py-1 theme-elevated rounded text-xs theme-text">
                    Candles: {candlesBatches.length} batch{candlesBatches.length > 1 ? 'es' : ''}
                  </span>
                )}
              </div>
            </div>
          )}

          {/* Next steps */}
          <div>
            <h4 className="text-xs font-semibold theme-text-secondary uppercase tracking-wide mb-1">Next steps</h4>
            <p className="theme-text-secondary">{nextSteps}</p>
          </div>
        </div>
      )}
    </div>
  );
}
