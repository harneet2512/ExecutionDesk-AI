'use client';

import { useState } from 'react';

interface NewsItem {
    id: string;
    title: string;
    url: string;
    source_name: string;
    published_at: string;
    role: string;
    notes?: string;
    raw_payload_json?: string;
}

interface EvidenceListProps {
    evidence: NewsItem[];
}

export default function EvidenceList({ evidence }: EvidenceListProps) {
    const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set());

    const toggleExpand = (id: string) => {
        const newSet = new Set(expandedIds);
        if (newSet.has(id)) {
            newSet.delete(id);
        } else {
            newSet.add(id);
        }
        setExpandedIds(newSet);
    };

    if (!evidence || evidence.length === 0) {
        return <div className="text-sm theme-text-secondary">No news evidence found for this run.</div>;
    }

    return (
        <div className="space-y-4">
            {evidence.map((item) => (
                <div key={item.id} className="border theme-border rounded-lg p-3 theme-surface">
                    <div className="flex justify-between items-start gap-2">
                        <div>
                            <div className="text-xs font-semibold theme-text-secondary mb-1">
                                {item.source_name || 'Unknown Source'} • {new Date(item.published_at).toLocaleString()}
                            </div>
                            <h4 className="text-sm font-medium theme-text leading-tight">
                                <a href={item.url} target="_blank" rel="noopener noreferrer" className="hover:underline">
                                    {item.title}
                                </a>
                            </h4>
                            {item.role && (
                                <div className="mt-1 text-xs theme-text-secondary">
                                    Role: <span className="font-mono theme-elevated px-1 rounded">{item.role}</span>
                                </div>
                            )}
                        </div>
                        <button
                            onClick={() => toggleExpand(item.id)}
                            className="text-xs theme-text-muted hover:opacity-80 px-2 py-1"
                        >
                            {expandedIds.has(item.id) ? 'Hide' : 'Raw'}
                        </button>
                    </div>

                    {expandedIds.has(item.id) && (
                        <div className="mt-3 pt-3 border-t theme-border">
                            <pre className="text-xs font-mono theme-sunken p-2 rounded overflow-x-auto theme-text-secondary">
                                {JSON.stringify(
                                    Object.fromEntries(
                                        Object.entries(item).filter(
                                            ([k]) => !/(run_id|trace_id|confirmation_id|tenant_id|_id$)/.test(k) || k === 'id'
                                        )
                                    ),
                                    null, 2
                                )}
                            </pre>
                        </div>
                    )}
                </div>
            ))}
        </div>
    );
}
