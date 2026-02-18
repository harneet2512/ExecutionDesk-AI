'use client';

import { useState, useEffect } from 'react';
import { listRuns, type Run } from '@/lib/api';
import { useRouter } from 'next/navigation';

export default function RunsList() {
    const router = useRouter();
    const [runs, setRuns] = useState<Run[]>([]);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        loadRuns();
    }, []);

    const loadRuns = async () => {
        try {
            setLoading(true);
            const runList = await listRuns();
            setRuns(runList);
        } catch (e) {
            console.error('Failed to load runs:', e);
        } finally {
            setLoading(false);
        }
    };

    const getStatusColor = (status: string) => {
        switch (status) {
            case 'COMPLETED':
                return 'bg-[var(--color-status-success-bg)] text-[var(--color-status-success)]';
            case 'FAILED':
                return 'bg-[var(--color-status-error-bg)] text-[var(--color-status-error)]';
            case 'RUNNING':
                return 'theme-elevated theme-text';
            case 'PAUSED':
                return 'theme-elevated theme-text-secondary';
            default:
                return 'theme-elevated theme-text-secondary';
        }
    };

    const getModeColor = (mode: string) => {
        switch (mode) {
            case 'LIVE':
                return 'text-[var(--color-status-error)]';
            case 'PAPER':
                return 'theme-text-secondary';
            case 'REPLAY':
                return 'theme-text-secondary';
            default:
                return 'theme-text-secondary';
        }
    };

    if (loading) {
        return (
            <div className="p-4 space-y-3">
                {[1, 2, 3, 4].map((i) => (
                    <div key={i} className="h-20 theme-elevated rounded-lg animate-pulse" />
                ))}
            </div>
        );
    }

    return (
        <div className="p-3 space-y-2">
            {runs.length === 0 ? (
                <p className="text-sm theme-text-secondary text-center py-8">
                    No trading runs yet.
                </p>
            ) : (
                runs.map((run) => (
                    <button
                        key={run.run_id}
                        onClick={() => router.push(`/runs/${run.run_id}`)}
                        className="w-full text-left p-3 theme-surface hover:bg-neutral-100 dark:hover:bg-neutral-700 rounded-lg border theme-border transition-all shadow-sm hover:shadow"
                    >
                        <div className="flex items-start justify-between gap-2 mb-2">
                            <div className="text-xs font-mono theme-text-secondary truncate">
                                {run.run_id}
                            </div>
                            <span className={`px-2 py-1 rounded-lg text-xs font-medium ${getStatusColor(run.status)}`}>
                                {run.status}
                            </span>
                        </div>
                        <div className="flex items-center gap-2 text-xs">
                            <span className={`font-medium ${getModeColor(run.execution_mode)}`}>
                                {run.execution_mode}
                            </span>
                            <span className="theme-text-muted">&bull;</span>
                            <span className="theme-text-secondary">
                                {new Date(run.created_at).toLocaleString()}
                            </span>
                        </div>
                    </button>
                ))
            )}
        </div>
    );
}
