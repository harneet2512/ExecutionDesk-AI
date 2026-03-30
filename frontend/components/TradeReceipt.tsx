'use client';

import { useState, useEffect, useRef, useCallback } from 'react';
import { apiFetchSafe } from '@/lib/api';
import { formatTradeOutcome, formatOrderId } from '@/lib/tradeFormatters';

// ---------------------------------------------------------------------------
// Card-scoped confetti (no external library – pure CSS animation)
// ---------------------------------------------------------------------------
const CONFETTI_COLORS = ['#22c55e', '#16a34a', '#4ade80', '#86efac', '#ffffff', '#a3e635'];
const CONFETTI_COUNT = 28;

function injectConfettiKeyframes() {
    const id = 'trade-receipt-confetti-kf';
    if (typeof document === 'undefined' || document.getElementById(id)) return;
    const s = document.createElement('style');
    s.id = id;
    s.textContent = `@keyframes confetti-fall{0%{transform:translateY(-8px) rotate(0deg);opacity:1}100%{transform:translateY(320px) rotate(720deg);opacity:0}}`;
    document.head.appendChild(s);
}

function CardConfetti() {
    const particles = useRef(
        Array.from({ length: CONFETTI_COUNT }, (_, i) => ({
            left: `${(i * 3.7 + Math.random() * 4) % 100}%`,
            color: CONFETTI_COLORS[i % CONFETTI_COLORS.length],
            delay: `${(i * 0.07).toFixed(2)}s`,
            dur: `${(0.75 + (i % 5) * 0.12).toFixed(2)}s`,
            size: i % 3 === 0 ? 5 : 7,
            round: i % 4 === 0,
        }))
    ).current;

    useEffect(() => { injectConfettiKeyframes(); }, []);

    return (
        <div className="absolute inset-0 pointer-events-none overflow-hidden" aria-hidden="true">
            {particles.map((p, i) => (
                <span key={i} style={{
                    position: 'absolute', top: '-8px', left: p.left,
                    width: p.size, height: p.size,
                    borderRadius: p.round ? '50%' : '2px',
                    backgroundColor: p.color,
                    animation: `confetti-fall ${p.dur} ${p.delay} ease-in forwards`,
                }} />
            ))}
        </div>
    );
}

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
    status_updated_at?: string;
    mode?: string;
    error?: string;
    reason_code?: string;
    venue?: {
        name?: string;
        execution_mode?: string;
        order_type?: string;
    };
}

function parsePositiveMs(value: string | undefined, fallback: number): number {
    if (!value) return fallback;
    const parsed = Number(value);
    if (!Number.isFinite(parsed) || parsed <= 0) return fallback;
    return parsed;
}

export default function TradeReceipt({ runId, status: parentStatus }: TradeReceiptProps) {
    const [tradeResult, setTradeResult] = useState<TradeResult | null>(null);
    const [newsBrief, setNewsBrief] = useState<{ headline?: string; trend?: string } | null>(null);
    const [loading, setLoading] = useState(true);
    const [copied, setCopied] = useState(false);
    const [fillWatchTimedOut, setFillWatchTimedOut] = useState(false);
    const [showConfetti, setShowConfetti] = useState(false);
    const [refreshing, setRefreshing] = useState(false);
    const [lastCheckedAt, setLastCheckedAt] = useState<Date | null>(null);
    const prevStatusRef = useRef<string>('');
    const fillPollTimeoutMs = parsePositiveMs(process.env.NEXT_PUBLIC_FILL_POLL_TIMEOUT_MS, 60000);
    const fillPollIntervalMs = parsePositiveMs(process.env.NEXT_PUBLIC_FILL_POLL_INTERVAL_MS, 5000);

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
                    result.status_updated_at = order.status_updated_at || undefined;

                    // CRITICAL: Use order-level status to determine actual trade outcome
                    // Don't show "COMPLETED" if order wasn't actually filled
                    if (order.status === 'FILLED') {
                        result.status = 'FILLED';
                    } else if (order.status === 'REJECTED' || order.status === 'FAILED') {
                        result.status = order.status;
                        result.error = order.status_reason || 'Order was rejected by the exchange';
                    } else if (order.status === 'SUBMITTED' || order.status === 'PENDING' || order.status === 'OPEN') {
                        result.status = 'SUBMITTED';
                        result.error = 'Order submitted. You can confirm fill in your Coinbase app.';
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

                        // Extract venue from trade_receipt artifact
                        if (trace?.trade_receipt?.venue) {
                            result.venue = trace.trade_receipt.venue;
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

    useEffect(() => {
        if (!tradeResult?.order_id) return;
        const statusUpper = (tradeResult.status || '').toUpperCase();
        const isPendingStatus = ['SUBMITTED', 'PENDING', 'OPEN', 'PENDING_FILL', 'PARTIALLY_FILLED'].includes(statusUpper);
        if (!isPendingStatus) return;
        if ((tradeResult.mode || '').toUpperCase() !== 'LIVE') return;

        let active = true;
        let polls = 0;
        const maxPolls = Math.max(1, Math.ceil(fillPollTimeoutMs / fillPollIntervalMs));

        const pollFillStatus = async () => {
            if (!active || !tradeResult.order_id) return;
            try {
                const data = await apiFetchSafe(`/api/v1/orders/${tradeResult.order_id}/fill-status`);
                if (!active || !data) return;

                const nextStatus = String(data.status || tradeResult.status || '').toUpperCase();
                setLastCheckedAt(new Date());
                setTradeResult(prev => {
                    if (!prev) return prev;
                    return {
                        ...prev,
                        status: nextStatus || prev.status,
                        filled_qty: typeof data.filled_qty === 'number' ? data.filled_qty : prev.filled_qty,
                        avg_fill_price: typeof data.avg_fill_price === 'number' ? data.avg_fill_price : prev.avg_fill_price,
                        error: data.fill_confirmed
                            ? undefined
                            : 'Order submitted. You can confirm fill in your Coinbase app.',
                    };
                });

                if (nextStatus === 'FILLED') {
                    active = false;
                    setFillWatchTimedOut(false);
                }
            } catch {
                // Best-effort watcher; keep current receipt state if refresh fails.
            }
        };

        const interval = setInterval(() => {
            polls += 1;
            if (!active) {
                clearInterval(interval);
                return;
            }
            if (polls > maxPolls) {
                clearInterval(interval);
                setFillWatchTimedOut(true);
                setTradeResult(prev => {
                    if (!prev) return prev;
                    return {
                        ...prev,
                        // Keep status pending/open/submitted; never mark timeout as failed.
                        status: ['SUBMITTED', 'PENDING', 'OPEN', 'PENDING_FILL', 'PARTIALLY_FILLED'].includes(
                            String(prev.status || '').toUpperCase()
                        )
                            ? prev.status
                            : 'SUBMITTED',
                        error: 'Order submitted; fill not confirmed within 60s. Check Coinbase app for final status.',
                    };
                });
                return;
            }
            pollFillStatus();
        }, fillPollIntervalMs);

        // Start immediately rather than waiting first 5 seconds.
        pollFillStatus();

        return () => {
            active = false;
            clearInterval(interval);
        };
    }, [tradeResult?.order_id, tradeResult?.status, tradeResult?.mode, fillPollTimeoutMs, fillPollIntervalMs]);

    // Detect FILLED transition → trigger card-scoped confetti (once per fill, idempotent)
    useEffect(() => {
        const current = (tradeResult?.status || '').toUpperCase();
        if (current === 'FILLED' && prevStatusRef.current !== 'FILLED') {
            setShowConfetti(true);
            const t = setTimeout(() => setShowConfetti(false), 3200);
            prevStatusRef.current = current;
            return () => clearTimeout(t);
        }
        prevStatusRef.current = current;
    }, [tradeResult?.status]);

    // Manual "Refresh status" – one-shot fill-status call for LIVE pending orders
    const handleRefreshStatus = useCallback(async () => {
        if (!tradeResult?.order_id || refreshing) return;
        setRefreshing(true);
        try {
            const data = await apiFetchSafe(`/api/v1/orders/${tradeResult.order_id}/fill-status`);
            if (data) {
                const nextStatus = String(data.status || tradeResult.status || '').toUpperCase();
                setLastCheckedAt(new Date());
                setTradeResult(prev => prev ? {
                    ...prev,
                    status: nextStatus || prev.status,
                    filled_qty: typeof data.filled_qty === 'number' ? data.filled_qty : prev.filled_qty,
                    avg_fill_price: typeof data.avg_fill_price === 'number' ? data.avg_fill_price : prev.avg_fill_price,
                    error: data.fill_confirmed ? undefined : prev.error,
                } : prev);
                if (nextStatus === 'FILLED') setFillWatchTimedOut(false);
            }
        } catch { /* best-effort */ }
        finally { setRefreshing(false); }
    }, [tradeResult?.order_id, tradeResult?.status, refreshing]);

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
        return (
            <div className="mt-3 p-3 rounded-lg border theme-surface theme-border text-sm theme-text-secondary animate-pulse">
                Loading trade result...
            </div>
        );
    }

    if (!tradeResult) {
        return (
            <div className="mt-3 p-3 rounded-lg border theme-surface theme-border text-sm theme-text-secondary">
                Trade result unavailable. Check the run details for more information.
            </div>
        );
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

    // Truth-model banner: run COMPLETED but order not yet filled
    const runIsCompleted = (parentStatus || '').toUpperCase() === 'COMPLETED';
    const orderNotFilled = tradeResult.status
        ? !['FILLED'].includes(tradeResult.status.toUpperCase()) && tradeResult.order_id
        : false;
    const showRunCompletedOrderPendingBanner = runIsCompleted && orderNotFilled && isPending;

    // Show refresh button for LIVE non-terminal pending orders
    const canRefresh = (tradeResult.mode || '').toUpperCase() === 'LIVE' && isPending && !!tradeResult.order_id;

    return (
        <div className="mt-3 p-3 rounded-lg border theme-surface theme-border relative overflow-hidden">
            {/* Card-scoped confetti – only fires when order transitions to FILLED */}
            {showConfetti && <CardConfetti />}

            {/* Truth-model banner: explicit message when run done but fill pending */}
            {showRunCompletedOrderPendingBanner && (
                <div className="mb-3 p-2 bg-[var(--color-status-warning-bg)] border border-[var(--color-status-warning)]/30 rounded text-xs text-[var(--color-status-warning)] flex items-start gap-2">
                    <span className="mt-0.5">&#9432;</span>
                    <span>
                        <strong>Run completed</strong> — workflow finished and order submitted to venue.
                        Fill not confirmed yet. Check your Coinbase app or use Refresh below.
                    </span>
                </div>
            )}

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

            {/* Order Lifecycle Bar */}
            <div className="mb-3 flex items-center gap-1 text-xs">
                {(() => {
                    const steps = [
                        { label: 'Submitted', key: 'SUBMITTED', ts: tradeResult.created_at },
                        { label: 'Pending', key: 'PENDING', ts: undefined },
                        { label: isSuccess ? 'Filled' : isFailed ? 'Failed' : isCanceled ? 'Canceled' : 'Awaiting',
                          key: isSuccess ? 'FILLED' : isFailed ? 'FAILED' : isCanceled ? 'CANCELED' : 'AWAITING',
                          ts: tradeResult.status_updated_at },
                    ];
                    const statusUpper = (tradeResult.status || '').toUpperCase();
                    const currentIdx = statusUpper === 'FILLED' ? 2
                        : ['FAILED', 'REJECTED'].includes(statusUpper) ? 2
                        : ['CANCELED', 'EXPIRED'].includes(statusUpper) ? 2
                        : ['PENDING', 'OPEN', 'PENDING_FILL'].includes(statusUpper) ? 1
                        : 0;
                    return steps.map((step, i) => {
                        const reached = i <= currentIdx;
                        const isCurrent = i === currentIdx;
                        const failedTerminal = isCurrent && (isFailed || isCanceled);
                        const color = failedTerminal ? 'bg-[var(--color-status-error)]'
                            : reached ? 'bg-[var(--color-status-success)]'
                            : 'bg-neutral-300 dark:bg-neutral-700';
                        const textColor = failedTerminal ? 'text-[var(--color-status-error)]'
                            : reached ? 'theme-text' : 'theme-text-secondary';
                        return (
                            <div key={step.key} className="flex items-center gap-1">
                                {i > 0 && <div className={`w-8 h-0.5 ${reached ? (failedTerminal ? 'bg-[var(--color-status-error)]' : 'bg-[var(--color-status-success)]') : 'bg-neutral-300 dark:bg-neutral-700'}`} />}
                                <div className="flex flex-col items-center">
                                    <div className={`w-3 h-3 rounded-full ${color}`} />
                                    <span className={`mt-0.5 ${textColor} whitespace-nowrap`}>{step.label}</span>
                                    {step.ts && (
                                        <span className="theme-text-secondary text-[10px]">
                                            {(() => { try { return new Date(step.ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }); } catch { return ''; } })()}
                                        </span>
                                    )}
                                </div>
                            </div>
                        );
                    });
                })()}
            </div>

            {/* Requested vs Filled Summary */}
            {(tradeResult.notional_usd || tradeResult.filled_qty) && (
                <div className="mb-3 p-2 theme-elevated rounded text-xs flex flex-wrap gap-x-4 gap-y-1">
                    {tradeResult.notional_usd !== undefined && (
                        <span>Requested: <strong>{typeof tradeResult.notional_usd === 'number' && isFinite(tradeResult.notional_usd)
                            ? `$${tradeResult.notional_usd.toFixed(2)}` : 'Not available: order was not executed'}</strong></span>
                    )}
                    {tradeResult.filled_qty !== undefined && typeof tradeResult.filled_qty === 'number' && tradeResult.filled_qty > 0 && (
                        <span>Filled: <strong>{tradeResult.filled_qty.toFixed(8)} {tradeResult.symbol?.replace('-USD', '') || ''}</strong>
                            {tradeResult.avg_fill_price !== undefined && typeof tradeResult.avg_fill_price === 'number' && isFinite(tradeResult.avg_fill_price) && (
                                <> @ <strong>${tradeResult.avg_fill_price.toFixed(2)}</strong></>
                            )}
                        </span>
                    )}
                    {tradeResult.fees !== undefined && typeof tradeResult.fees === 'number' && isFinite(tradeResult.fees) && (
                        <span>Fees: <strong>${tradeResult.fees.toFixed(4)}</strong></span>
                    )}
                </div>
            )}

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
                        <span className="theme-text-secondary">Requested</span>
                        <span className="font-medium theme-text">
                            {typeof tradeResult.notional_usd === 'number' && isFinite(tradeResult.notional_usd)
                                ? `$${tradeResult.notional_usd.toFixed(2)}` : 'Not available: order was not executed'}
                        </span>
                    </>
                )}

                {tradeResult.filled_qty !== undefined && (
                    <>
                        <span className="theme-text-secondary">Filled</span>
                        <span className="font-medium theme-text">
                            {isPending && (!tradeResult.filled_qty || tradeResult.filled_qty === 0)
                                ? 'Pending fill'
                                : typeof tradeResult.filled_qty === 'number' && isFinite(tradeResult.filled_qty)
                                ? `${tradeResult.filled_qty.toFixed(8)} ${tradeResult.symbol?.replace('-USD', '') || ''}`
                                : '\u2014'}
                        </span>
                    </>
                )}

                {tradeResult.avg_fill_price !== undefined && (
                    <>
                        <span className="theme-text-secondary">Avg Price</span>
                        <span className="font-medium theme-text">
                            {isPending && (!tradeResult.avg_fill_price || tradeResult.avg_fill_price === 0)
                                ? 'Pending fill'
                                : typeof tradeResult.avg_fill_price === 'number' && isFinite(tradeResult.avg_fill_price)
                                ? `$${tradeResult.avg_fill_price.toFixed(2)}`
                                : '\u2014'}
                        </span>
                    </>
                )}

                {tradeResult.fees !== undefined && (
                    <>
                        <span className="theme-text-secondary">Fees</span>
                        <span className="font-medium theme-text">
                            {typeof tradeResult.fees === 'number' && isFinite(tradeResult.fees)
                                ? `$${tradeResult.fees.toFixed(4)}`
                                : isFailed || isCanceled ? 'Not available: order did not fill' : 'Pending fill confirmation'}
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

                {tradeResult.venue?.name && (
                    <>
                        <span className="theme-text-secondary">Venue</span>
                        <span className="font-medium theme-text">{tradeResult.venue.name}</span>
                    </>
                )}

                {tradeResult.created_at && (
                    <>
                        <span className="theme-text-secondary">Submitted</span>
                        <span className="font-medium theme-text text-xs">
                            {(() => { try { return new Date(tradeResult.created_at).toLocaleString(); } catch { return '\u2014'; } })()}
                        </span>
                    </>
                )}

                {tradeResult.status_updated_at && (
                    <>
                        <span className="theme-text-secondary">Last Updated</span>
                        <span className="font-medium theme-text text-xs">
                            {(() => { try { return new Date(tradeResult.status_updated_at).toLocaleString(); } catch { return '\u2014'; } })()}
                        </span>
                    </>
                )}

                {lastCheckedAt && (
                    <>
                        <span className="theme-text-secondary">Last checked</span>
                        <span className="font-medium theme-text text-xs">
                            {lastCheckedAt.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
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

            {/* Warning message for pending orders + Refresh button */}
            {isPending && (
                <div className="mt-3 p-2 bg-[var(--color-status-warning-bg)] rounded text-sm text-[var(--color-status-warning)] border border-[var(--color-status-warning)]/20">
                    <div className="flex items-start justify-between gap-2">
                        <div>
                            <span className="font-medium">Order submitted; fill pending.</span>{' '}
                            {fillWatchTimedOut
                                ? 'Not confirmed within 60s. Check Coinbase app for final status.'
                                : 'Check Coinbase app too.'}
                        </div>
                        {canRefresh && (
                            <button
                                onClick={handleRefreshStatus}
                                disabled={refreshing}
                                className="flex-shrink-0 px-2 py-1 text-xs font-medium rounded border border-[var(--color-status-warning)]/50 hover:bg-[var(--color-status-warning)]/10 transition-colors disabled:opacity-50"
                                title="Check fill status from Coinbase"
                            >
                                {refreshing ? 'Checking...' : 'Refresh status'}
                            </button>
                        )}
                    </div>
                </div>
            )}

            {/* Paper trade footnote */}
            {isPaper && (
                <div className="mt-2 pt-2 border-t theme-border text-xs theme-text-secondary">
                    Paper trade -- no real funds used. Fills are simulated at market price.
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
