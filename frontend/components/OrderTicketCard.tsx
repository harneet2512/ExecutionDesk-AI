'use client';

import { useState } from 'react';

interface OrderTicket {
    ticket_id: string;
    symbol: string;
    side: 'BUY' | 'SELL';
    notional_usd: number;
    est_qty?: number;
    suggested_limit?: number;
    tif?: string;
    status: string;
    asset_class: string;
    created_at?: string;
    expires_at?: string;
}

interface OrderTicketCardProps {
    ticket: OrderTicket;
    onMarkExecuted?: (ticketId: string, receipt: object) => Promise<void>;
    onCancel?: (ticketId: string) => Promise<void>;
    liveDisabled?: boolean;
}

/**
 * ASSISTED_LIVE order ticket display with copy JSON and Mark Executed flow.
 * Used for stocks where manual brokerage execution is required.
 */
export default function OrderTicketCard({ ticket, onMarkExecuted, onCancel, liveDisabled }: OrderTicketCardProps) {
    const [showReceiptModal, setShowReceiptModal] = useState(false);
    const [receiptJson, setReceiptJson] = useState('');
    const [copied, setCopied] = useState(false);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [showCancelConfirm, setShowCancelConfirm] = useState(false);

    const orderJson = {
        symbol: ticket.symbol,
        side: ticket.side,
        notional_usd: ticket.notional_usd,
        est_qty: ticket.est_qty,
        suggested_limit: ticket.suggested_limit,
        order_type: 'LIMIT',
        tif: ticket.tif || 'DAY',
    };

    const handleCopy = async () => {
        try {
            await navigator.clipboard.writeText(JSON.stringify(orderJson, null, 2));
            setCopied(true);
            setTimeout(() => setCopied(false), 2000);
        } catch {
            setError('Failed to copy to clipboard');
        }
    };

    const handleSubmitReceipt = async () => {
        if (!receiptJson.trim()) {
            setError('Please enter receipt JSON');
            return;
        }

        try {
            setLoading(true);
            setError(null);
            const parsed = JSON.parse(receiptJson);
            await onMarkExecuted?.(ticket.ticket_id, parsed);
            setShowReceiptModal(false);
            setReceiptJson('');
        } catch (e: any) {
            if (e instanceof SyntaxError) {
                setError('Invalid JSON format');
            } else {
                setError(e.message || 'Failed to submit receipt');
            }
        } finally {
            setLoading(false);
        }
    };

    const handleCancelConfirmed = async () => {
        try {
            setLoading(true);
            setShowCancelConfirm(false);
            await onCancel?.(ticket.ticket_id);
        } catch (e: any) {
            setError(e.message || 'Failed to cancel');
        } finally {
            setLoading(false);
        }
    };

    const isPending = ticket.status === 'PENDING';
    const sideColor = ticket.side === 'BUY' ? 'text-[var(--color-status-success)]' : 'text-[var(--color-status-error)]';

    return (
        <>
            <div className="theme-elevated rounded-xl p-5 border theme-border shadow-sm">
                {/* Header */}
                <div className="flex items-center justify-between mb-4">
                    <div className="flex items-center gap-2">
                        <div className="p-2 bg-neutral-200 dark:bg-neutral-800 rounded-lg">
                            <svg className="w-5 h-5 theme-text-secondary" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                                    d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                            </svg>
                        </div>
                        <div>
                            <span className="font-semibold theme-text">
                                Order Ticket
                            </span>
                            <span className="ml-2 px-2 py-0.5 bg-neutral-200 dark:bg-neutral-700 theme-text-secondary text-xs font-medium rounded">
                                {ticket.asset_class}
                            </span>
                        </div>
                    </div>

                    <span className={`
            px-2 py-1 rounded text-xs font-medium
            ${isPending
                            ? 'bg-[var(--color-status-warning-bg)] text-[var(--color-status-warning)]'
                            : ticket.status === 'EXECUTED'
                                ? 'bg-[var(--color-status-success-bg)] text-[var(--color-status-success)]'
                                : 'theme-elevated theme-text-secondary'
                        }
          `}>
                        {ticket.status}
                    </span>
                </div>

                {/* Order Details */}
                <div className="grid grid-cols-2 gap-3 mb-4">
                    <div>
                        <label className="text-xs theme-text-secondary">Symbol</label>
                        <p className="font-mono font-semibold theme-text">
                            {ticket.symbol}
                        </p>
                    </div>
                    <div>
                        <label className="text-xs theme-text-secondary">Side</label>
                        <p className={`font-semibold ${sideColor}`}>
                            {ticket.side}
                        </p>
                    </div>
                    <div>
                        <label className="text-xs theme-text-secondary">Notional</label>
                        <p className="font-semibold theme-text">
                            ${ticket.notional_usd.toLocaleString(undefined, { minimumFractionDigits: 2 })}
                        </p>
                    </div>
                    {ticket.est_qty && (
                        <div>
                            <label className="text-xs theme-text-secondary">Est. Qty</label>
                            <p className="font-mono theme-text-secondary">
                                {ticket.est_qty.toLocaleString(undefined, { maximumFractionDigits: 4 })}
                            </p>
                        </div>
                    )}
                    {ticket.suggested_limit && (
                        <div>
                            <label className="text-xs theme-text-secondary">Suggested Limit</label>
                            <p className="font-mono theme-text-secondary">
                                ${ticket.suggested_limit.toLocaleString(undefined, { minimumFractionDigits: 2 })}
                            </p>
                        </div>
                    )}
                </div>

                {/* JSON Preview */}
                <div className="bg-neutral-900 rounded-lg p-3 mb-4">
                    <pre className="text-xs text-neutral-300 overflow-x-auto">
                        {JSON.stringify(orderJson, null, 2)}
                    </pre>
                </div>

                {/* Instructions */}
                <div className="theme-bg rounded-lg p-3 mb-4 text-sm">
                    <p className="theme-text">
                        <strong>Manual Execution Required:</strong> Copy the order details above and
                        execute in your brokerage (Schwab, Fidelity, etc.), then submit the execution receipt.
                    </p>
                </div>

                {/* LIVE disabled banner */}
                {liveDisabled && isPending && (
                    <div className="mb-3 p-2 bg-[var(--color-status-warning-bg)] border border-[var(--color-status-warning)]/20 rounded-lg text-xs text-[var(--color-status-warning)]">
                        LIVE trading is disabled. Mark Executed is blocked.
                    </div>
                )}

                {/* Actions */}
                {isPending && (
                    <div className="flex gap-2">
                        <button
                            onClick={handleCopy}
                            className="flex-1 px-4 py-2 theme-elevated hover:bg-[var(--color-fill-ghost-hover)] theme-text-secondary rounded-lg text-sm font-medium transition-colors flex items-center justify-center gap-2"
                        >
                            {copied ? (
                                <>
                                    <svg className="w-4 h-4 text-[var(--color-status-success)]" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                                    </svg>
                                    Copied!
                                </>
                            ) : (
                                <>
                                    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                                            d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" />
                                    </svg>
                                    Copy JSON
                                </>
                            )}
                        </button>

                        <button
                            onClick={() => setShowReceiptModal(true)}
                            disabled={loading || liveDisabled}
                            className="flex-1 px-4 py-2 bg-[var(--color-status-success)] hover:opacity-90 text-white rounded-lg text-sm font-medium transition-colors disabled:opacity-50"
                        >
                            Mark Executed
                        </button>

                        <button
                            onClick={() => setShowCancelConfirm(true)}
                            disabled={loading}
                            className="px-4 py-2 bg-[var(--color-status-error-bg)] hover:opacity-80 text-[var(--color-status-error)] rounded-lg text-sm font-medium transition-colors disabled:opacity-50"
                        >
                            Cancel
                        </button>
                    </div>
                )}

                {error && (
                    <p className="mt-2 text-sm text-[var(--color-status-error)]">{error}</p>
                )}

                {/* Ticket ID footer */}
                <div className="mt-3 pt-2 border-t theme-border text-xs theme-text-muted">
                    ID: {ticket.ticket_id}
                    {ticket.created_at && ` • Created: ${new Date(ticket.created_at).toLocaleString()}`}
                </div>
            </div>

            {/* Cancel Confirmation Modal */}
            {showCancelConfirm && (
                <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
                    <div className="theme-surface rounded-xl p-6 max-w-sm w-full shadow-xl">
                        <h3 className="text-lg font-semibold theme-text mb-2">
                            Cancel Order Ticket?
                        </h3>
                        <p className="text-sm theme-text-secondary mb-4">
                            This will cancel the pending order for {ticket.symbol}. This action cannot be undone.
                        </p>
                        <div className="flex justify-end gap-2">
                            <button
                                onClick={() => setShowCancelConfirm(false)}
                                className="px-4 py-2 theme-text-secondary hover:bg-[var(--color-fill-ghost-hover)] rounded-lg text-sm font-medium transition-colors"
                            >
                                Keep Order
                            </button>
                            <button
                                onClick={handleCancelConfirmed}
                                disabled={loading}
                                className="px-4 py-2 bg-[var(--color-status-error)] hover:opacity-90 text-white rounded-lg text-sm font-medium transition-colors disabled:opacity-50"
                            >
                                {loading ? 'Cancelling...' : 'Yes, Cancel'}
                            </button>
                        </div>
                    </div>
                </div>
            )}

            {/* Receipt Modal */}
            {showReceiptModal && (
                <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
                    <div className="theme-surface rounded-xl p-6 max-w-lg w-full shadow-xl">
                        <h3 className="text-lg font-semibold theme-text mb-4">
                            Submit Execution Receipt
                        </h3>

                        <p className="text-sm theme-text-secondary mb-4">
                            Paste the order confirmation from your brokerage as JSON:
                        </p>

                        <textarea
                            value={receiptJson}
                            onChange={(e) => setReceiptJson(e.target.value)}
                            placeholder={`{\n  "order_id": "...",\n  "filled_qty": ...,\n  "avg_price": ...\n}`}
                            className="w-full h-40 px-3 py-2 border theme-border rounded-lg resize-none focus:outline-none focus:ring-2 focus:ring-[var(--color-focus-ring)] theme-surface theme-text font-mono text-sm"
                        />

                        {error && (
                            <p className="mt-2 text-sm text-[var(--color-status-error)]">{error}</p>
                        )}

                        <div className="flex justify-end gap-2 mt-4">
                            <button
                                onClick={() => {
                                    setShowReceiptModal(false);
                                    setError(null);
                                }}
                                className="px-4 py-2 theme-text-secondary hover:bg-[var(--color-fill-ghost-hover)] rounded-lg text-sm font-medium transition-colors"
                            >
                                Cancel
                            </button>
                            <button
                                onClick={handleSubmitReceipt}
                                disabled={loading || !receiptJson.trim()}
                                className="px-4 py-2 bg-[var(--color-status-success)] hover:opacity-90 text-white rounded-lg text-sm font-medium transition-colors disabled:opacity-50"
                            >
                                {loading ? 'Submitting...' : 'Submit Receipt'}
                            </button>
                        </div>
                    </div>
                </div>
            )}
        </>
    );
}
