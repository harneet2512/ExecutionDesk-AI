'use client';

import { useState, useEffect, useCallback, useRef } from 'react';
import RunStatusPill, { useRunStatus } from './RunStatusPill';
import { formatTradeSide, formatTradeTitle, getSideColorClass } from '@/lib/tradeFormatters';

export interface TradeStep {
    step_id: string;
    step_name: string;
    status: 'pending' | 'running' | 'done' | 'failed';
    description?: string;
    summary?: string;
    duration_ms?: number;
    sequence?: number;
}

interface TradeProcessingCardProps {
    runId: string;
    side?: string;
    symbol?: string;
    notionalUsd?: number;
    mode?: string;
    steps?: TradeStep[];
    onComplete?: (status: string, runId: string) => void;
    onRetry?: () => void;
    /** When true, SSE is delivering events so the hook uses a slower fallback interval. */
    sseConnected?: boolean;
}

const STEP_LABELS: Record<string, string> = {
    research: 'Research',
    signals: 'Signals',
    risk: 'Risk',
    news: 'News',
    proposal: 'Proposal',
    policy_check: 'Policy',
    approval: 'Approval',
    execution: 'Execute',
    post_trade: 'Post-Trade',
    eval: 'Eval',
};

export default function TradeProcessingCard({
    runId,
    side = '',  // Bug 1 fix: Don't default to 'BUY' - let formatters handle missing side
    symbol = '',
    notionalUsd = 0,
    mode = 'PAPER',
    steps = [],
    onComplete,
    onRetry,
    sseConnected = false,
}: TradeProcessingCardProps) {
    // Normalize side using formatter (Bug 1 fix)
    const normalizedSide = formatTradeSide(side);
    const tradeTitle = formatTradeTitle({ side, symbol, notional: notionalUsd, mode });

    const fmtUsd = (v: any) => typeof v === 'number' && isFinite(v) && v > 0 ? `$${v.toFixed(2)} ` : '';
    const [showDebug, setShowDebug] = useState(false);
    const [debugCopied, setDebugCopied] = useState(false);
    const [latestOrderStatus, setLatestOrderStatus] = useState<string | null>(null);

    // P2B: When SSE is connected the chat page already receives events.
    // Use a slower fallback interval (5s) to avoid duplicate poll traffic.
    const pollInterval = sseConnected ? 5000 : 1000;

    const {
        status,
        startedAt,
        currentStep,
        error,
        isStale,
        refetch,
        isTerminal,
        isActive,
        totalSteps,
        completedSteps,
        lastEventAt,
        executionMode,
    } = useRunStatus(runId, { pollInterval, enabled: true });

    // Calculate elapsed time
    const [elapsedSeconds, setElapsedSeconds] = useState(0);

    useEffect(() => {
        if (!startedAt || isTerminal) return;

        const updateElapsed = () => {
            try {
                const start = new Date(startedAt).getTime();
                setElapsedSeconds(Math.floor((Date.now() - start) / 1000));
            } catch { setElapsedSeconds(0); }
        };

        updateElapsed();
        const interval = setInterval(updateElapsed, 1000);
        return () => clearInterval(interval);
    }, [startedAt, isTerminal]);

    // Derived terminal state booleans (F8 fix: were previously undefined)
    const isCompleted = status.toUpperCase() === 'COMPLETED';
    const isFailed = status.toUpperCase() === 'FAILED';
    const hasPendingOrder =
        latestOrderStatus !== null &&
        ['SUBMITTED', 'OPEN', 'PENDING', 'PENDING_FILL', 'PARTIALLY_FILLED'].includes(latestOrderStatus);

    useEffect(() => {
        if (!runId) return;
        if (!isCompleted) return;
        let mounted = true;

        const fetchOrderStatus = async () => {
            try {
                const res = await fetch(`/api/v1/runs/${runId}`, {
                    headers: { 'X-Dev-Tenant': 't_default' },
                });
                if (!res.ok || !mounted) return;
                const data = await res.json();
                const orders = Array.isArray(data?.orders) ? data.orders : [];
                const latest = orders[0];
                if (latest?.status && mounted) {
                    setLatestOrderStatus(String(latest.status).toUpperCase());
                }
            } catch {
                // Keep default UI state if order status lookup fails.
            }
        };

        fetchOrderStatus();
        return () => {
            mounted = false;
        };
    }, [runId, isCompleted]);

    // Notify parent when terminal ONCE per run (F4 fix: prevents infinite rerender)
    // Notify parent when terminal ONCE per run (F4 fix: prevents infinite rerender)
    const onCompleteCalledRef = useRef(false);
    const onCompleteRef = useRef(onComplete);

    // Update ref if prop changes
    useEffect(() => {
        onCompleteRef.current = onComplete;
    }, [onComplete]);

    useEffect(() => {
        if (isTerminal && onCompleteRef.current && !onCompleteCalledRef.current) {
            onCompleteCalledRef.current = true;
            onCompleteRef.current(status, runId);
        }
    }, [isTerminal, status, runId]);

    // D1: Deduplicate steps by step_id before rendering
    const dedupedSteps = steps.filter((s, i, arr) =>
        arr.findIndex(x => x.step_id === s.step_id) === i
    );

    // U2: Override stale parent steps when terminal to prevent "running" while "FAILED/COMPLETED"
    const effectiveSteps = isTerminal
        ? dedupedSteps.map(s => ({
            ...s,
            status: s.status === 'done' ? 'done' as const :
                isCompleted ? 'done' as const :
                    isFailed ? 'failed' as const : s.status
        }))
        : dedupedSteps;

    // Stuck detection: no event in 20s while active, or >90s total
    const [secondsSinceLastEvent, setSecondsSinceLastEvent] = useState(0);
    useEffect(() => {
        if (!isActive || !lastEventAt) return;
        const update = () => {
            try {
                const last = new Date(lastEventAt).getTime();
                setSecondsSinceLastEvent(Math.floor((Date.now() - last) / 1000));
            } catch { setSecondsSinceLastEvent(0); }
        };
        update();
        const interval = setInterval(update, 1000);
        return () => clearInterval(interval);
    }, [isActive, lastEventAt]);

    const isStuck = isActive && (secondsSinceLastEvent > 20 || elapsedSeconds > 90);

    // Step-based progress
    const progressPercent = totalSteps > 0
        ? Math.round((completedSteps / totalSteps) * 100)
        : (isActive ? Math.min(elapsedSeconds * 2, 80) : (isTerminal ? 100 : 0));

    const stepLabel = STEP_LABELS[currentStep || ''] || currentStep || 'Processing';

    const handleCopyDebug = useCallback(() => {
        const debug = {
            run_id: runId,
            status,
            current_step: currentStep,
            started_at: startedAt,
            elapsed_seconds: elapsedSeconds,
            total_steps: totalSteps,
            completed_steps: completedSteps,
            last_event_at: lastEventAt,
            seconds_since_last_event: secondsSinceLastEvent,
            is_stale: isStale,
            error,
            steps: effectiveSteps.map(s => ({ name: s.step_name, status: s.status })),
            tenant: 't_default',
            timestamp: new Date().toISOString()
        };
        navigator.clipboard.writeText(JSON.stringify(debug, null, 2));
        setDebugCopied(true);
        setTimeout(() => setDebugCopied(false), 2000);
    }, [runId, status, currentStep, startedAt, elapsedSeconds, totalSteps, completedSteps, lastEventAt, secondsSinceLastEvent, isStale, error, steps]);

    return (
        <div className={`border rounded-lg p-4 space-y-3 ${isCompleted
                ? (hasPendingOrder
                    ? 'bg-[var(--color-status-warning-bg)] border-[var(--color-status-warning)]/20'
                    : 'bg-[var(--color-status-success-bg)] border-[var(--color-status-success)]/20')
                :
                isFailed ? 'bg-[var(--color-status-error-bg)] border-[var(--color-status-error)]/20' :
                    'theme-bg theme-border'
            }`}>
            {/* Header */}
            <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                    <div className={`w-10 h-10 rounded-full flex items-center justify-center ${isCompleted
                            ? (hasPendingOrder
                                ? 'bg-[var(--color-status-warning)]/20'
                                : 'bg-[var(--color-status-success)]/20')
                            :
                            isFailed ? 'bg-[var(--color-status-error)]/20' :
                                getSideColorClass(normalizedSide, 'bg')
                        }`}>
                        <span className="text-lg">
                            {isCompleted ? (hasPendingOrder ? '\u23F3' : '\u2713') : isFailed ? '\u2717' : normalizedSide === 'SELL' ? '\u2193' : normalizedSide === 'BUY' ? '\u2191' : '\u2022'}
                        </span>
                    </div>
                    <div>
                        <div className="font-medium theme-text">
                            {tradeTitle}
                        </div>
                        <div className="text-xs theme-text-muted">
                            {executionMode || mode} Mode
                        </div>
                    </div>
                </div>

                <RunStatusPill
                    status={status}
                    startedAt={startedAt}
                    currentStep={currentStep}
                    onRefresh={refetch}
                />
            </div>

            {/* Step-based progress bar */}
            {(isActive || isTerminal) && (
                <div className="space-y-1">
                    <div className="flex items-center gap-2">
                        <div className="flex-1 h-1.5 bg-neutral-700 dark:bg-neutral-700 rounded-full overflow-hidden">
                            <div
                                className={`h-full rounded-full transition-all duration-500 ${isFailed ? 'bg-[var(--color-status-error)]' :
                                        isCompleted ? 'bg-[var(--color-status-success)]' :
                                            'bg-neutral-400 animate-pulse'
                                    }`}
                                style={{ width: `${progressPercent}%` }}
                            />
                        </div>
                        <span className="text-xs theme-text-muted min-w-[80px] text-right">
                            {isActive ? stepLabel : (isCompleted ? 'Done' : 'Failed')}
                        </span>
                    </div>
                    {totalSteps > 0 && (
                        <div className="text-xs theme-text-secondary text-right">
                            {completedSteps}/{totalSteps} steps
                        </div>
                    )}
                </div>
            )}

            {/* Step Timeline */}
            {effectiveSteps.length > 0 && (
                <div className="flex flex-wrap gap-1 items-center">
                    {effectiveSteps
                        .sort((a, b) => (a.sequence || 0) - (b.sequence || 0))
                        .map((step, i) => {
                            const label = STEP_LABELS[step.step_name] || step.step_name;
                            const isDone = step.status === 'done';
                            const isRunning = step.status === 'running';
                            const isFail = step.status === 'failed';

                            return (
                                <span key={step.step_id} className="flex items-center gap-0.5">
                                    {i > 0 && <span className="text-neutral-600 text-xs mx-0.5">&rarr;</span>}
                                    <span className={`inline-flex items-center gap-1 px-2 py-1 rounded-lg text-xs ${isDone ? 'bg-[var(--color-status-success-bg)] text-[var(--color-status-success)]' :
                                            isRunning ? 'bg-neutral-800/50 theme-text-secondary' :
                                                isFail ? 'bg-[var(--color-status-error-bg)] text-[var(--color-status-error)]' :
                                                    'bg-neutral-800/50 theme-text-muted'
                                        }`}>
                                        {isDone && <span className="text-[var(--color-status-success)]">&#10003;</span>}
                                        {isRunning && <span className="animate-spin inline-block w-2.5 h-2.5 border border-neutral-400/30 border-t-neutral-400 rounded-full" />}
                                        {isFail && <span className="text-[var(--color-status-error)]">&#10007;</span>}
                                        {!isDone && !isRunning && !isFail && <span className="text-neutral-600">&#9675;</span>}
                                        {label}
                                    </span>
                                </span>
                            );
                        })}
                </div>
            )}

            {/* Completion banner */}
            {isCompleted && (
                <div className={`rounded-lg p-3 flex items-center gap-2 text-sm border ${
                    hasPendingOrder
                        ? 'bg-[var(--color-status-warning-bg)] border-[var(--color-status-warning)]/20 text-[var(--color-status-warning)]'
                        : 'bg-[var(--color-status-success-bg)] border-[var(--color-status-success)]/20 text-[var(--color-status-success)]'
                }`}>
                    <span className={`text-base ${
                        hasPendingOrder ? 'text-[var(--color-status-warning)]' : 'text-[var(--color-status-success)]'
                    }`}>
                        {hasPendingOrder ? '\u23F3' : '\u2713'}
                    </span>
                    <span>
                        {hasPendingOrder
                            ? `${executionMode || mode} ${tradeTitle} - Order submitted. You can confirm fill in your Coinbase app.`
                            : `${executionMode || mode} ${tradeTitle} - Order filled. You can also confirm in your Coinbase app.`}
                        {elapsedSeconds > 0 && (
                            <span className="text-xs ml-1">Completed in {elapsedSeconds}s</span>
                        )}
                    </span>
                </div>
            )}

            {/* Failure banner */}
            {isFailed && (
                <div className="bg-[var(--color-status-error-bg)] border border-[var(--color-status-error)]/20 rounded-lg p-3 space-y-2">
                    <div className="flex items-center gap-2 text-[var(--color-status-error)] text-sm">
                        <span className="text-base">&#10007;</span>
                        <span>{error || 'Trade execution failed'}</span>
                    </div>
                    <div className="flex gap-2">
                        {onRetry && (
                            <button
                                onClick={onRetry}
                                className="px-3 py-1 text-xs bg-[var(--color-status-error)] hover:opacity-90 text-white rounded-lg transition-colors"
                            >
                                Retry Trade
                            </button>
                        )}
                        <button
                            onClick={handleCopyDebug}
                            className="px-3 py-1 text-xs bg-neutral-600 hover:bg-neutral-500 text-white rounded-lg transition-colors"
                        >
                            {debugCopied ? 'Copied!' : 'Copy Debug Info'}
                        </button>
                    </div>
                </div>
            )}

            {/* Stuck warning */}
            {isStuck && (
                <div className="bg-[var(--color-status-warning-bg)] border border-[var(--color-status-warning)]/20 rounded-lg p-3 space-y-2">
                    <div className="flex items-center gap-2 text-[var(--color-status-warning)] text-sm">
                        <span>&#9888;</span>
                        <span>
                            {secondsSinceLastEvent > 20
                                ? `No updates for ${secondsSinceLastEvent}s`
                                : `Taking longer than expected (${elapsedSeconds}s)`}
                        </span>
                    </div>
                    <div className="flex gap-2">
                        <a
                            href={`/runs/${runId}`}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="px-3 py-1 text-xs bg-neutral-600 hover:bg-neutral-500 text-white rounded-lg transition-colors inline-block"
                        >
                            View Run Details
                        </a>
                        <button
                            onClick={handleCopyDebug}
                            className="px-3 py-1 text-xs bg-neutral-600 hover:bg-neutral-500 text-white rounded-lg transition-colors"
                        >
                            {debugCopied ? 'Copied!' : 'Copy Debug'}
                        </button>
                    </div>
                </div>
            )}

            {/* Stale connection warning */}
            {isStale && !isStuck && (
                <div className="text-xs text-[var(--color-status-warning)] flex items-center gap-2">
                    <span>&#9888;</span>
                    <span>Connection may be stale</span>
                </div>
            )}

            {/* Actions */}
            <div className="flex items-center gap-3 pt-2 border-t border-neutral-700">
                <a
                    href={`/runs/${runId}`}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-xs theme-text-secondary hover:underline"
                >
                    View Run Details &rarr;
                </a>

                <button
                    onClick={() => setShowDebug(!showDebug)}
                    className="text-xs theme-text-muted hover:theme-text-secondary ml-auto"
                >
                    {showDebug ? 'Hide Debug' : 'Debug'}
                </button>
            </div>

            {/* Debug info */}
            {showDebug && (
                <div className="text-xs font-mono bg-neutral-900/50 p-2 rounded-lg theme-text-muted space-y-1">
                    {process.env.NEXT_PUBLIC_DEBUG_TRADE_DIAGNOSTICS === '1' && (
                        <div data-testid="debug-run-id">run_id: {runId}</div>
                    )}
                    <div>status: {status}</div>
                    <div>step: {currentStep || 'none'}</div>
                    <div>progress: {completedSteps}/{totalSteps} ({progressPercent}%)</div>
                    <div>elapsed: {elapsedSeconds}s</div>
                    <div>last_event: {secondsSinceLastEvent}s ago</div>
                    <div>stale: {isStale ? 'yes' : 'no'}</div>
                    <div>sse_steps: {effectiveSteps.length}</div>
                    {error && <div className="text-[var(--color-status-error)]">error: {error}</div>}
                    <button
                        onClick={handleCopyDebug}
                        className="mt-1 theme-text-secondary hover:underline"
                        title="Copies full debug info (including IDs) to clipboard"
                    >
                        {debugCopied ? 'Copied!' : 'Copy Debug to Clipboard'}
                    </button>
                </div>
            )}
        </div>
    );
}
