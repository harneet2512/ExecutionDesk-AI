'use client';

import { useState, useEffect } from 'react';
import EvidenceList from './EvidenceList';

interface ArtifactPanelProps {
    runId: string;
    isOpen: boolean;
    onClose: () => void;
}

export default function ArtifactPanel({ runId, isOpen, onClose }: ArtifactPanelProps) {
    const [activeTab, setActiveTab] = useState<'plan' | 'evidence' | 'constraints' | 'decision' | 'thinking'>('plan');
    const [artifacts, setArtifacts] = useState<any[]>([]);
    const [evidence, setEvidence] = useState<any[]>([]);
    const [loading, setLoading] = useState(false);

    useEffect(() => {
        if (isOpen && runId) {
            fetchData();
        }
    }, [isOpen, runId]);

    const fetchData = async () => {
        setLoading(true);
        try {
            // Fetch artifacts
            const artifactsRes = await fetch(`/api/v1/news/runs/${runId}/artifacts`);
            const artifactsData = await artifactsRes.json();
            setArtifacts(artifactsData);

            // Fetch evidence
            const evidenceRes = await fetch(`/api/v1/news/runs/${runId}/evidence`);
            const evidenceData = await evidenceRes.json();
            setEvidence(evidenceData);
        } catch (e) {
            console.error("Failed to fetch artifacts", e);
        } finally {
            setLoading(false);
        }
    };

    if (!isOpen) return null;

    const renderContent = () => {
        if (loading) return <div className="p-4 text-center">Loading artifacts...</div>;

        switch (activeTab) {
            case 'plan':
                const plan = artifacts.find(a => a.artifact_type === 'plan' || a.step_name === 'plan'); // simplified logic
                // If we don't have a plan artifact yet, we might fallback to generic plan text
                return (
                    <div className="p-4">
                        <h3 className="text-lg font-medium mb-2">Execution Plan</h3>
                        <div className="text-sm theme-text-secondary">
                            The execution plan is determined statically by the DAG.
                            {/* TODO: Show static plan or specific plan artifact */}
                        </div>
                    </div>
                );
            case 'evidence':
                return (
                    <div className="p-4">
                        <h3 className="text-lg font-medium mb-4">News Evidence</h3>
                        <EvidenceList evidence={evidence} />
                    </div>
                );
            case 'constraints':
                // Find artifacts with constraints (e.g. decision record)
                const decisionRec = artifacts.find(a => a.artifact_type === 'decision_record');
                const constraints = decisionRec?.artifact_json?.constraints_triggered || [];
                const blockers = decisionRec?.artifact_json?.blockers || [];

                return (
                    <div className="p-4 space-y-4">
                        <h3 className="text-lg font-medium mb-2">Active Constraints</h3>
                        {blockers.length > 0 && (
                            <div className="bg-[var(--color-status-error-bg)] p-3 rounded border border-[var(--color-status-error)]/20">
                                <h4 className="text-[var(--color-status-error)] font-semibold mb-2">Blockers</h4>
                                {blockers.map((b: any, i: number) => (
                                    <div key={i} className="text-sm text-[var(--color-status-error)]">
                                        • {b.reason} ({b.tag})
                                    </div>
                                ))}
                            </div>
                        )}
                        {constraints.length === 0 && blockers.length === 0 && (
                            <div className="text-sm text-[var(--color-status-success)]">
                                No constraints triggered.
                            </div>
                        )}
                    </div>
                );
            case 'decision':
                const decision = artifacts.find(a => a.artifact_type === 'decision_record');
                if (!decision) return <div className="p-4">No decision record found.</div>;
                const d = decision.artifact_json;
                return (
                    <div className="p-4 space-y-4">
                        <h3 className="text-lg font-medium">Final Decision</h3>
                        <div className="p-3 theme-bg rounded border theme-border">
                            <div className="text-sm font-semibold">Selected Asset: {d.selected_asset || 'NONE (Blocked)'}</div>
                            <div className="text-sm mt-1">Action: {d.action}</div>
                            <div className="text-sm mt-2 font-mono theme-elevated p-2 rounded">
                                {d.rationale}
                            </div>
                        </div>
                    </div>
                );
            case 'thinking':
                // Generate thinking on the fly or use stored artifact
                // For now, we construct it from artifacts if no dedicated ui_thinking artifact
                return (
                    <div className="p-4 space-y-4">
                        <h3 className="text-lg font-medium">Reasoning Trace</h3>
                        <div className="space-y-6">
                            {/* Step 1: News */}
                            <div>
                                <h4 className="font-semibold theme-text">1. News Analysis</h4>
                                <p className="text-sm theme-text-secondary mt-1">
                                    Scanned {evidence.length} news items.
                                    {evidence.length > 0 ? " Found relevant signals." : " No significant news found."}
                                </p>
                            </div>
                            {/* Step 2: Decision */}
                            <div>
                                <h4 className="font-semibold theme-text">2. Decision Synthesis</h4>
                                <p className="text-sm theme-text-secondary mt-1">
                                    Synthesized market data and news constraints.
                                </p>
                            </div>
                        </div>
                    </div>
                );
        }
    };

    return (
        <div className="fixed inset-y-0 right-0 w-96 theme-surface shadow-2xl border-l theme-border transform transition-transform duration-300 z-50 flex flex-col">
            {/* Header */}
            <div className="px-4 py-3 border-b theme-border flex items-center justify-between">
                <h2 className="text-sm font-bold theme-text">
                    Run Artifacts
                </h2>
                <button
                    onClick={onClose}
                    className="p-1 rounded hover:bg-[var(--color-fill-ghost-hover)] theme-text-secondary"
                >
                    ✕
                </button>
            </div>

            {/* Tabs */}
            <div className="flex border-b theme-border overflow-x-auto">
                {['plan', 'evidence', 'constraints', 'decision', 'thinking'].map((tab) => (
                    <button
                        key={tab}
                        onClick={() => setActiveTab(tab as any)}
                        className={`px-4 py-2 text-xs font-medium border-b-2 whitespace-nowrap ${activeTab === tab
                                ? 'border-neutral-800 dark:border-neutral-200 theme-text'
                                : 'border-transparent theme-text-secondary hover:opacity-80'
                            }`}
                    >
                        {tab.charAt(0).toUpperCase() + tab.slice(1)}
                    </button>
                ))}
            </div>

            {/* Content */}
            <div className="flex-1 overflow-y-auto theme-surface">
                {renderContent()}
            </div>
        </div>
    );
}
