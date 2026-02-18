'use client';

import { useState, useEffect } from 'react';
import { apiFetchSafe } from '@/lib/api';
import { formatTradeOutcome, formatOrderId } from '@/lib/tradeFormatters';

interface TradeReceiptProps {
    runId: string;
    status?: string;
}

interface TradeResult {
    order_id?: string;
    status?: string;
    side?: string;
    symbol?: string;
    notional_usd?: number;
    filled_qty?: number;
    avg_fill_price?: number;
    fees?: number;
    created_at?: string;
    mode?: string;
    error?: string;
    reason_code?: string;
}

export default function TradeReceipt({ runId, status: parentStatus }: TradeReceiptProps) {
    const [tradeResult, setTradeResult] = useState<TradeResult | null>(null);
    const [newsBrief, setNewsBrief] = useState<{ headline?: string; trend?: string } | null>(null);
    const [loading, setLoading] = useState(true);
    const [copied, setCopied] = useState(false);

    // Determine if the run has reached a terminal state
    const isTerminal = parentStatus
        ? ['COMPLETED', 'FAILED'].includes(parentStatus.toUpperCase())
        : true; // If no status prop, assume terminal (backward compat)

    useEffect(() => {
        async function fetchTradeResult() {
            if (!runId) return;
            // Wait until run is terminal before fetching trade data
            if (!isTerminal) return;

            try {
                // Fetch run details via apiFetchSafe (retries + headers)
                const runData = await apiFetchSafe(`/api/v1/runs/${runId}`);
                if (!runData) {
                    setLoading(false);
                    return;
                }
                // Run detail API returns { run: {...}, orders: [...], fills: [...], ... }
                const run = runData.run || {};
                const orders = runData.orders || [];

                const result: TradeResult = {
                    status: run.status,
                    mode: run.execution_mode,
                };

                // Parse metadata from run (stored as JSON string)
                if (run.metadata_json) {
                    try {
                        const metadata = typeof run.metadata_json === 'string'
                            ? JSON.parse(run.metadata_json) : run.metadata_json;
                        result.side = metadata.side;
                        result.symbol = metadata.asset;
                        result.notional_usd = metadata.amount_usd;
                    } catch {
                        // Ignore malformed metadata
                    }
                }

                // Extract from orders array (primary source of trade data)
                if (orders.length > 0) {
                    const order = orders[0];
                    result.order_id = result.order_id || order.order_id;
                    result.symbol = result.symbol || order.symbol;
                    result.side = result.side || order.side;
                    result.notional_usd = result.notional_usd || order.notional_usd;
                    if (order.filled_qty !== null && order.filled_qty !== undefined) {
                        result.filled_qty = order.filled_qty;
                    }
                    if (order.avg_fill_price !== null && order.avg_fill_price !== undefined) {
                        result.avg_fill_price = order.avg_fill_price;
                    }
                    if (order.total_fees !== null && order.total_fees !== undefined) {
                        result.fees = order.total_fees;
                    }
                    result.created_at = result.created_at || order.created_at;
                    
                    // CRITICAL: Use order-level status to determine actual trade outcome
                    // Don't show "COMPLETED" if order wasn't actually filled
                    if (order.status === 'FILLED') {
                        result.status = 'COMPLETED';
                    } else if (order.status === 'REJECTED' || order.status === 'FAILED') {
                        result.status = order.status;
                        result.error = order.status_reason || 'Order was rejected by the exchange';
                    } else if (order.status === 'SUBMITTED' || order.status === 'PENDING' || order.status === 'OPEN') {
                        // Order was submitted but not yet filled - don't show as COMPLETED
                        result.status = 'PENDING';
                        result.error = 'Order submitted but not filled. Check Coinbase for status.';
                    } else if (order.status === 'CANCELED' || order.status === 'EXPIRED') {
                        result.status = order.status;
                        result.error = order.status_reason || `Order was ${order.status.toLowerCase()}`;
                    }
                }

                // Supplement with trace data (events may have additional details)
                try {
                    const trace = await apiFetchSafe(`/api/v1/runs/${runId}/trace`);

                    if (trace) {

                        // Check for order result in events
                        const recentEvents = trace.recent_events || [];
                        for (const event of recentEvents) {
                            if (event.payload?.order_id && !result.order_id) {
                                result.order_id = event.payload.order_id;
                            }
                            if (event.payload?.filled_qty && !result.filled_qty) {
                                result.filled_qty = event.payload.filled_qty || event.payload.filled_size;
                            }
                            if (event.payload?.avg_fill_price && !result.avg_fill_price) {
                                result.avg_fill_price = event.payload.avg_fill_price || event.payload.average_filled_price;
                            }
                            if (event.payload?.symbol && !result.symbol) {
                                result.symbol = event.payload.symbol;
                            }
                            if (event.payload?.notional_usd && !result.notional_usd) {
                                result.notional_usd = event.payload.notional_usd;
                            }
                        }

                        // Check execution plan for selected order
                        if (trace.plan?.selected_order) {
                            const order = trace.plan.selected_order;
                            result.symbol = result.symbol || order.symbol;
                            result.side = result.side || order.side;
                            result.notional_usd = result.notional_usd || order.notional_usd;
                        }

                        // Extract news brief if available
                        const nb = trace.artifacts?.news_brief;
                        if (nb && (nb.headline || nb.trend)) {
                            setNewsBrief({ headline: nb.headline, trend: nb.trend });
                        }
                    }
                } catch (traceErr) {
                    console.log('Could not fetch trace:', traceErr);
                }

                // Only show if we have meaningful data
                if (result.status || result.order_id) {
                    setTradeResult(result);
                }
            } catch (e) {
                console.error('Failed to fetch trade result:', e);
            } finally {
                setLoading(false);
            }
        }

        fetchTradeResult();
    }, [runId, isTerminal]);

    const handleCopy = async () => {
        if (!tradeResult) return;

        const fmtNum = (v: number | undefined, digits: number) =>
            typeof v === 'number' && isFinite(v) ? v.toFixed(digits) : 'N/A';

        const text = `Trade Receipt
Order ID: ${tradeResult.order_id || 'N/A'}
Status: ${tradeResult.status || 'UNKNOWN'}
Side: ${tradeResult.side?.toUpperCase() || 'N/A'}
Symbol: ${tradeResult.symbol || 'N/A'}
Notional: $${fmtNum(tradeResult.notional_usd, 2)}
Filled: ${fmtNum(tradeResult.filled_qty, 8)}
Avg Price: $${fmtNum(tradeResult.avg_fill_price, 2)}
Fees: $${fmtNum(tradeResult.fees, 4)}
Mode: ${tradeResult.mode || 'N/A'}`;

        try {
            await navigator.clipboard.writeText(text);
            setCopied(true);
            setTimeout(() => setCopied(false), 2000);
        } catch (e) {
            console.error('Failed to copy:', e);
        }
    };

    if (!isTerminal) {
        return (
            <div className="mt-3 p-3 rounded-lg border theme-surface theme-border text-sm theme-text-secondary">
                Fetching trade details...
            </div>
        );
    }

    if (loading) {
        return null; // Don't show loading state - just wait
    }

    if (!tradeResult) {
        return null; // No trade result available
    }

    // Bug 2 fix: Use formatter for consistent status display
    const outcome = formatTradeOutcome(tradeResult.status);
    const isSuccess = outcome.type === 'success';
    const isFailed = outcome.type === 'failed';
    const isPending = outcome.type === 'pending';
    const isCanceled = outcome.type === 'cancelled';
    const isPaper = tradeResult.mode === 'PAPER';
    
    // Bug 4 fix: Format order ID appropriately for PAPER vs LIVE
    const displayOrderId = formatOrderId(tradeResult.order_id, tradeResult.mode);

    return (
        <div className="mt-3 p-3 rounded-lg border theme-surface theme-border">
            {/* Header - Bug 2 fix: More prominent status display with clear visual distinction */}
            <div className="flex items-center justify-between mb-3">
                <div className="flex items-center gap-2">
                    <span className={`text-lg ${
                        isSuccess ? 'text-[var(--color-status-success)]' :
                        isFailed ? 'text-[var(--color-status-error)]' :
                        isPending ? 'text-[var(--color-status-warning)]' :
                        isCanceled ? 'text-[var(--color-status-error)]' : 'theme-text-secondary'
                    }`}>
                        {isSuccess ? '\u2713' : isFailed ? '\u2717' : isPending ? '\u23F3' : isCanceled ? '\u2717' : '\u23F3'}
                    </span>
                    <span className={`font-semibold ${
                        isSuccess ? 'text-[var(--color-status-success)]' :
                        isFailed ? 'text-[var(--color-status-error)]' :
                        isPending ? 'text-[var(--color-status-warning)]' :
                        isCanceled ? 'text-[var(--color-status-error)]' :
                        'theme-text'
                    }`}>
                        {outcome.text}
                    </span>
                    {isPaper && (
                        <span className="px-2 py-0.5 text-xs font-medium theme-elevated theme-text-secondary rounded">
                            PAPER
                        </span>
                    )}
                    {tradeResult.mode === 'LIVE' && (
                        <span className="px-2 py-0.5 text-xs font-medium theme-elevated theme-text rounded">
                            LIVE
                        </span>
                    )}
                </div>
                <button
                    onClick={handleCopy}
                    className="p-1.5 rounded-md hover:bg-[var(--color-fill-ghost-hover)] theme-text-secondary transition-colors"
                    title={copied ? 'Copied!' : 'Copy receipt'}
                >
                    {copied ? (
                        <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4 text-[var(--color-status-success)]" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                        </svg>
                    ) : (
                        <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" />
                        </svg>
                    )}
                </button>
            </div>

            {/* Order Details Grid */}
            <div className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
                {tradeResult.side && (
                    <>
                        <span className="theme-text-secondary">Side</span>
                        <span className={`font-medium ${tradeResult.side.toLowerCase() === 'buy' ? 'text-[var(--color-status-success)]' : 'text-[var(--color-status-error)]'}`}>
                            {tradeResult.side.toUpperCase()}
                        </span>
                    </>
                )}

                {tradeResult.symbol && (
                    <>
                        <span className="theme-text-secondary">Symbol</span>
                        <span className="font-medium theme-text">{tradeResult.symbol}</span>
                    </>
                )}

                {tradeResult.notional_usd !== undefined && (
                    <>
                        <span className="theme-text-secondary">Notional</span>
                        <span className="font-medium theme-text">
                            {typeof tradeResult.notional_usd === 'number' && isFinite(tradeResult.notional_usd)
                                ? `$${tradeResult.notional_usd.toFixed(2)}` : 'N/A'}
                        </span>
                    </>
                )}

                {tradeResult.filled_qty !== undefined && (
                    <>
                        <span className="theme-text-secondary">Filled</span>
                        <span className="font-medium theme-text">
                            {typeof tradeResult.filled_qty === 'number' && isFinite(tradeResult.filled_qty)
                                ? tradeResult.filled_qty.toFixed(8) : 'N/A'}
                        </span>
                    </>
                )}

                {tradeResult.avg_fill_price !== undefined && (
                    <>
                        <span className="theme-text-secondary">Avg Price</span>
                        <span className="font-medium theme-text">
                            {typeof tradeResult.avg_fill_price === 'number' && isFinite(tradeResult.avg_fill_price)
                                ? `$${tradeResult.avg_fill_price.toFixed(2)}` : 'N/A'}
                        </span>
                    </>
                )}

                {tradeResult.fees !== undefined && (
                    <>
                        <span className="theme-text-secondary">Fees</span>
                        <span className="font-medium theme-text">
                            {typeof tradeResult.fees === 'number' && isFinite(tradeResult.fees)
                                ? `$${tradeResult.fees.toFixed(4)}` : 'N/A'}
                        </span>
                    </>
                )}

                {tradeResult.order_id && (
                    <>
                        <span className="theme-text-secondary">Order ID</span>
                        <span className="font-mono text-xs theme-text-secondary truncate" title={tradeResult.order_id}>
                            {displayOrderId}
                            {isPaper && <span className="ml-1 theme-text-muted">(paper)</span>}
                        </span>
                    </>
                )}

                <span className="theme-text-secondary">Status</span>
                <span className={`font-medium ${
                    isSuccess ? 'text-[var(--color-status-success)]' :
                    isFailed ? 'text-[var(--color-status-error)]' :
                    isPending ? 'text-[var(--color-status-warning)]' :
                    isCanceled ? 'text-[var(--color-status-error)]' :
                    'text-[var(--color-status-warning)]'
                }`}>
                    {tradeResult.status || 'UNKNOWN'}
                </span>
            </div>

            {/* Warning message for pending orders */}
            {isPending && (
                <div className="mt-3 p-2 bg-[var(--color-status-warning-bg)] rounded text-sm text-[var(--color-status-warning)] border border-[var(--color-status-warning)]/20">
                    <span className="font-medium">⚠️ Order Pending:</span> Order was submitted but not confirmed filled. Check your Coinbase account for actual status.
                </div>
            )}

            {/* Error message if failed or canceled */}
            {(isFailed || isCanceled) && tradeResult.error && (
                <div className="mt-3 p-2 bg-[var(--color-status-error-bg)] rounded text-sm text-[var(--color-status-error)]">
                    {tradeResult.error}
                </div>
            )}

            {/* Market context from news brief */}
            {newsBrief && (
                <div className="mt-3 p-2 theme-bg rounded border theme-border">
                    <div className="text-xs font-medium theme-text-secondary mb-1">Market Context</div>
                    {newsBrief.headline && (
                        <div className="text-sm theme-text-secondary">{newsBrief.headline}</div>
                    )}
                    {newsBrief.trend && (
                        <div className="text-xs theme-text-secondary mt-0.5">{newsBrief.trend}</div>
                    )}
                </div>
            )}
        </div>
    );
}
