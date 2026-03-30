'use client';

import { useState } from 'react';
import ArtifactPanel from './ArtifactPanel';

export interface Step {
    step_id: string;
    step_name: string;
    status: 'pending' | 'running' | 'done' | 'failed';
    description?: string;
    summary?: string;
    timestamp?: string;
    started_timestamp?: string;
    duration_ms?: number;
    sequence?: number;
    evidence_refs?: any[];
}

interface StepsDrawerProps {
    steps: Step[];
    isOpen: boolean;
    onClose: () => void;
    runId?: string;
}

export default function StepsDrawer({ steps, isOpen, onClose, runId }: StepsDrawerProps) {
    const [artifactPanelOpen, setArtifactPanelOpen] = useState(false);

    if (!isOpen) return null;

    const getStatusIcon = (status: string) => {
        switch (status) {
            case 'done':
                return '✓';
            case 'running':
                return '⟳';
            case 'failed':
                return '✗';
            default:
                return '○';
        }
    };

    const getStatusColor = (status: string) => {
        switch (status) {
            case 'done':
                return 'text-[var(--color-status-success)]';
            case 'running':
                return 'text-[var(--color-status-info)] animate-spin';
            case 'failed':
                return 'text-[var(--color-status-error)]';
            default:
                return 'theme-text-muted';
        }
    };

    return (
        <>
            <div className="w-96 theme-surface border-l theme-border flex flex-col overflow-hidden shadow-xl z-40">
                {/* Header */}
                <div className="px-4 py-3 border-b theme-border flex items-center justify-between theme-bg">
                    <h2 className="text-sm font-semibold theme-text flex items-center gap-2">
                        Execution Steps
                        {runId && (
                            <span className="text-xs font-normal theme-text-secondary theme-elevated px-1.5 py-0.5 rounded">
                                {runId.slice(-6)}
                            </span>
                        )}
                    </h2>
                    <div className="flex items-center gap-1">
                        {runId && (
                            <button
                                onClick={() => setArtifactPanelOpen(true)}
                                className="text-xs btn-secondary px-2 py-1 rounded transition-colors mr-2"
                            >
                                View Artifacts
                            </button>
                        )}
                        <button
                            onClick={onClose}
                            className="p-1 rounded hover:bg-[var(--color-fill-ghost-hover)] theme-text-secondary"
                        >
                            ✕
                        </button>
                    </div>
                </div>

                {/* Steps List */}
                <div className="flex-1 overflow-y-auto p-4 space-y-3 theme-surface">
                    {steps.length === 0 ? (
                        <div className="flex flex-col items-center justify-center h-40 theme-text-secondary">
                            <p className="text-sm">No steps yet.</p>
                            <p className="text-xs mt-1">Waiting for run to start...</p>
                        </div>
                    ) : (
                        steps
                            .sort((a, b) => (a.sequence || 0) - (b.sequence || 0))
                            .map((step) => (
                                <div
                                    key={step.step_id}
                                    className={`p-3 rounded-lg border transition-all ${step.status === 'running'
                                            ? 'bg-[var(--color-status-info-bg)] border-[var(--color-status-info)]/20 shadow-sm'
                                            : 'theme-surface theme-border'
                                        }`}
                                >
                                    <div className="flex items-start gap-3">
                                        <div className={`mt-0.5 text-lg ${getStatusColor(step.status)}`}>
                                            {getStatusIcon(step.status)}
                                        </div>
                                        <div className="flex-1 min-w-0">
                                            <div className="flex justify-between items-start">
                                                <div className="text-sm font-medium theme-text leading-tight">
                                                    {step.step_name}
                                                </div>
                                                {step.duration_ms && (
                                                    <span className="text-[10px] font-mono theme-text-muted">
                                                        {(step.duration_ms / 1000).toFixed(1)}s
                                                    </span>
                                                )}
                                            </div>

                                            {step.description && (
                                                <div className="text-xs theme-text-secondary mt-1 leading-snug">
                                                    {step.description}
                                                </div>
                                            )}

                                            {step.summary && (
                                                <div className="text-xs theme-text-secondary mt-2 p-2 theme-bg rounded border theme-border font-mono break-words">
                                                    {step.summary}
                                                </div>
                                            )}

                                            {/* Evidence/Artifact Link per step */}
                                            {step.status === 'done' && runId && (
                                                <button
                                                    onClick={() => setArtifactPanelOpen(true)}
                                                    className="mt-2 text-[10px] theme-text hover:opacity-80 font-medium flex items-center gap-1"
                                                >
                                                    View Output →
                                                </button>
                                            )}
                                        </div>
                                    </div>
                                </div>
                            ))
                    )}
                </div>
            </div>

            {/* Artifact Panel Overlay */}
            {runId && (
                <ArtifactPanel
                    runId={runId}
                    isOpen={artifactPanelOpen}
                    onClose={() => setArtifactPanelOpen(false)}
                />
            )}
        </>
    );
}
