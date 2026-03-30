'use client';

import { useState, useEffect, useRef } from 'react';

interface RunStatusPillProps {
    status: string;
    startedAt?: string;
    currentStep?: string;
    onRefresh?: () => void;
}

const STATUS_CONFIG: Record<string, { color: string; icon: string; label: string; spinning?: boolean }> = {
    CREATED: { color: 'bg-neutral-500', icon: '○', label: 'Created' },
    QUEUED: { color: 'bg-neutral-500', icon: '◐', label: 'Queued', spinning: true },
    PENDING: { color: 'bg-neutral-400', icon: '◐', label: 'Pending', spinning: true },
    RUNNING: { color: 'bg-neutral-500', icon: '◐', label: 'Executing', spinning: true },
    EXECUTING: { color: 'bg-neutral-500', icon: '◐', label: 'Executing', spinning: true },
    PAUSED: { color: 'bg-neutral-400', icon: '⏸', label: 'Paused' },
    COMPLETED: { color: 'bg-[var(--color-status-success)]', icon: '✓', label: 'Completed' },
    FAILED: { color: 'bg-[var(--color-status-error)]', icon: '✕', label: 'Failed' },
};

export default function RunStatusPill({ status, startedAt, currentStep, onRefresh }: RunStatusPillProps) {
    const [elapsedSeconds, setElapsedSeconds] = useState(0);

    const normalizedStatus = status?.toUpperCase() || 'CREATED';
    const config = STATUS_CONFIG[normalizedStatus] || STATUS_CONFIG.CREATED;
    const isActive = ['RUNNING', 'EXECUTING', 'QUEUED', 'PENDING'].includes(normalizedStatus);
    const isTerminal = ['COMPLETED', 'FAILED'].includes(normalizedStatus);

    // Update elapsed time every second while running
    useEffect(() => {
        if (!isActive || !startedAt) return;

        const updateElapsed = () => {
            try {
                const start = new Date(startedAt).getTime();
                const now = Date.now();
                setElapsedSeconds(Math.floor((now - start) / 1000));
            } catch {
                setElapsedSeconds(0);
            }
        };

        updateElapsed();
        const interval = setInterval(updateElapsed, 1000);
        return () => clearInterval(interval);
    }, [isActive, startedAt]);

    const formatElapsed = (seconds: number) => {
        if (seconds < 60) return `${seconds}s`;
        const mins = Math.floor(seconds / 60);
        const secs = seconds % 60;
        return `${mins}m ${secs}s`;
    };

    return (
        <div className="flex items-center gap-2">
            {/* Status pill */}
            <span className={`inline-flex items-center gap-2 px-3 py-1 rounded-full text-xs font-medium text-white ${config.color}`}>
                {config.spinning ? (
                    <span className="animate-spin inline-block w-3 h-3 border-2 border-white/30 border-t-white rounded-full" />
                ) : (
                    <span className="text-sm">{config.icon}</span>
                )}
                {config.label}
                {isActive && elapsedSeconds > 0 && (
                    <span className="opacity-75 ml-1">{formatElapsed(elapsedSeconds)}</span>
                )}
            </span>

            {/* Current step indicator */}
            {isActive && currentStep && (
                <span className="text-xs theme-text-secondary">
                    {currentStep}
                </span>
            )}

            {/* Refresh button for active runs */}
            {isActive && onRefresh && (
                <button
                    onClick={onRefresh}
                    className="text-xs theme-text-secondary hover:underline"
                >
                    Refresh
                </button>
            )}
        </div>
    );
}

// Export a hook for run status polling
export function useRunStatus(runId: string | null, options?: { pollInterval?: number; enabled?: boolean }) {
    const [status, setStatus] = useState<string>('CREATED');
    const [startedAt, setStartedAt] = useState<string | undefined>();
    const [completedAt, setCompletedAt] = useState<string | undefined>();
    const [currentStep, setCurrentStep] = useState<string | undefined>();
    const [error, setError] = useState<string | null>(null);
    const [isStale, setIsStale] = useState(false);
    const [totalSteps, setTotalSteps] = useState(0);
    const [completedSteps, setCompletedSteps] = useState(0);
    const [lastEventAt, setLastEventAt] = useState<string | undefined>();
    const [executionMode, setExecutionMode] = useState<string | undefined>();

    const pollInterval = options?.pollInterval ?? 1000;
    const enabled = options?.enabled ?? true;

    const fetchStatus = async () => {
        if (!runId) return;

        try {
            // Use lightweight status endpoint (3 queries vs 10+)
            const res = await fetch(`/api/v1/runs/status/${runId}`, {
                headers: { 'X-Dev-Tenant': 't_default' }
            });

            if (!res.ok) {
                setIsStale(true);
                return;
            }

            const data = await res.json();
            setStatus(data.status || 'CREATED');
            setStartedAt(data.started_at);
            setCompletedAt(data.completed_at);
            setCurrentStep(data.current_step);
            setTotalSteps(data.total_steps || 0);
            setCompletedSteps(data.completed_steps || 0);
            setLastEventAt(data.updated_at);
            setError(data.last_error || null);
            setExecutionMode(data.execution_mode);
            setIsStale(false);
        } catch (e) {
            console.error('[useRunStatus] Fetch failed:', e);
            setIsStale(true);
        }
    };

    const isTerminalRef = useRef(false);
    useEffect(() => {
        isTerminalRef.current = ['COMPLETED', 'FAILED'].includes(status.toUpperCase());
    }, [status]);

    useEffect(() => {
        if (!runId || !enabled || isTerminalRef.current) return;

        // P2B: Debug instrumentation for poller deduplication
        const isDebug = typeof window !== 'undefined' && (
            process.env.NEXT_PUBLIC_DEBUG_UI === '1' ||
            (typeof localStorage !== 'undefined' && localStorage.getItem('DEBUG_UI') === '1')
        );
        if (isDebug) {
            console.debug(`[useRunStatus] Starting poller for ${runId} @ ${pollInterval}ms`);
        }

        fetchStatus();

        const interval = setInterval(() => {
            if (isTerminalRef.current) {
                if (isDebug) console.debug(`[useRunStatus] Stopping poller for ${runId} (terminal)`);
                clearInterval(interval);
                return;
            }
            fetchStatus();
        }, pollInterval);
        return () => {
            if (isDebug) console.debug(`[useRunStatus] Cleanup poller for ${runId}`);
            clearInterval(interval);
        };
    }, [runId, enabled, pollInterval]);

    return {
        status,
        startedAt,
        completedAt,
        currentStep,
        error,
        isStale,
        totalSteps,
        completedSteps,
        lastEventAt,
        executionMode,
        refetch: fetchStatus,
        isTerminal: ['COMPLETED', 'FAILED'].includes(status.toUpperCase()),
        isActive: ['RUNNING', 'EXECUTING', 'QUEUED', 'PENDING'].includes(status.toUpperCase())
    };
}
