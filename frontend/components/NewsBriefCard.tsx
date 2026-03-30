'use client';

import { useState } from 'react';

interface NewsItem {
    headline: string;
    source: string;
    published_at: string;
    retrieved_at?: string;
    url?: string;
    cluster_id?: string;
    severity?: 'info' | 'warning' | 'critical';
    tag?: string;
    symbol?: string;
}

interface NewsBrief {
    items: NewsItem[];
    blockers?: Array<{
        symbol: string;
        reason: string;
        tag: string;
        severity: string;
    }>;
    summary?: string;
    fetched_at?: string;
    source_count?: number;
}

interface NewsBriefCardProps {
    brief: NewsBrief;
    isSkipped?: boolean;
    skipReason?: string;
}

/**
 * Displays news brief with expandable items and severity badges.
 * Shows blockers prominently if any symbols have critical news.
 */
export default function NewsBriefCard({ brief, isSkipped, skipReason }: NewsBriefCardProps) {
    const [expanded, setExpanded] = useState(false);
    const hasBlockers = brief.blockers && brief.blockers.length > 0;
    const itemCount = brief.items?.length || 0;

    if (isSkipped) {
        return (
            <div className="theme-surface rounded-xl p-4 border theme-border">
                <div className="flex items-center gap-2 theme-text-secondary">
                    <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                            d="M18.364 18.364A9 9 0 005.636 5.636m12.728 12.728A9 9 0 015.636 5.636m12.728 12.728L5.636 5.636" />
                    </svg>
                    <span className="text-sm font-medium">News Analysis Skipped</span>
                </div>
                {skipReason && (
                    <p className="text-xs theme-text-muted mt-1">{skipReason}</p>
                )}
            </div>
        );
    }

    // No headlines available — show diagnostic message
    if (itemCount === 0 && !hasBlockers) {
        return (
            <div className="theme-surface rounded-xl p-4 border theme-border">
                <div className="flex items-center gap-2 theme-text-secondary">
                    <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                            d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4c-.77-.833-1.964-.833-2.732 0L4.082 16.5c-.77.833.192 2.5 1.732 2.5z" />
                    </svg>
                    <span className="text-sm font-medium">News Temporarily Unavailable</span>
                </div>
                <p className="text-xs theme-text-muted mt-1">
                    No headlines retrieved from news providers. Market data and fees are still available.
                    {brief.fetched_at && (
                        <> Last successful fetch: {new Date(brief.fetched_at).toLocaleString()}</>
                    )}
                </p>
            </div>
        );
    }

    return (
        <div className={`
      rounded-xl p-4 border transition-all duration-200
      ${hasBlockers
                ? 'bg-[var(--color-status-error-bg)] border-[var(--color-status-error)]/20'
                : 'theme-surface theme-border'
            }
    `}>
            {/* Header */}
            <div className="flex items-center justify-between mb-3">
                <div className="flex items-center gap-2">
                    <svg className="w-5 h-5 theme-text-secondary" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                            d="M19 20H5a2 2 0 01-2-2V6a2 2 0 012-2h10a2 2 0 012 2v1m2 13a2 2 0 01-2-2V7m2 13a2 2 0 002-2V9a2 2 0 00-2-2h-2m-4-3H9M7 16h6M7 8h6v4H7V8z" />
                    </svg>
                    <span className="font-medium theme-text">
                        News Brief
                    </span>
                    <span className="text-xs theme-text-secondary">
                        {itemCount} item{itemCount !== 1 ? 's' : ''}
                    </span>
                </div>

                <button
                    onClick={() => setExpanded(!expanded)}
                    className="text-xs theme-text-secondary hover:underline"
                >
                    {expanded ? 'Collapse' : 'Expand'}
                </button>
            </div>

            {/* Blockers Warning */}
            {hasBlockers && (
                <div className="mb-3 p-3 bg-[var(--color-status-error-bg)] rounded-lg">
                    <div className="flex items-center gap-2 text-[var(--color-status-error)] font-medium mb-2">
                        <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                                d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
                        </svg>
                        <span>Trade Blockers Detected</span>
                    </div>
                    <ul className="space-y-1">
                        {brief.blockers?.map((blocker, idx) => (
                            <li key={idx} className="text-sm text-[var(--color-status-error)]">
                                <span className="font-mono">{blocker.symbol}</span>: {blocker.reason}
                                <span className="ml-2 px-2 py-1 bg-[var(--color-status-error-bg)] text-[var(--color-status-error)] rounded-lg text-xs">
                                    {blocker.tag}
                                </span>
                            </li>
                        ))}
                    </ul>
                </div>
            )}

            {/* Summary */}
            {brief.summary && (
                <p className="text-sm theme-text-secondary mb-3">
                    {brief.summary}
                </p>
            )}

            {/* Expandable Items */}
            {expanded && brief.items && brief.items.length > 0 && (
                <div className="space-y-2 mt-3 pt-3 border-t theme-border">
                    {brief.items.map((item, idx) => (
                        <div key={idx} className="flex items-start gap-2 text-sm">
                            <SeverityBadge severity={item.severity} />
                            <div className="flex-1 min-w-0">
                                <p className="font-medium theme-text truncate">
                                    {item.headline}
                                </p>
                                <div className="flex items-center gap-2 text-xs theme-text-secondary">
                                    <span>{item.source}</span>
                                    <span>•</span>
                                    <span>{formatTime(item.published_at)}</span>
                                    {item.symbol && (
                                        <>
                                            <span>•</span>
                                            <span className="font-mono">{item.symbol}</span>
                                        </>
                                    )}
                                </div>
                            </div>
                            {item.url && (
                                <a
                                    href={item.url}
                                    target="_blank"
                                    rel="noopener noreferrer"
                                    className="theme-text-secondary hover:underline text-xs"
                                >
                                    Link
                                </a>
                            )}
                        </div>
                    ))}
                </div>
            )}

            {/* Footer */}
            {brief.fetched_at && (
                <div className="mt-3 pt-2 border-t theme-border text-xs theme-text-muted">
                    Fetched: {formatTime(brief.fetched_at)}
                    {brief.source_count && ` • ${brief.source_count} sources`}
                </div>
            )}
        </div>
    );
}

function SeverityBadge({ severity }: { severity?: string }) {
    const colorClass = 'theme-elevated theme-text-secondary';

    return (
        <span className={`px-2 py-1 rounded-lg text-xs font-medium ${colorClass}`}>
            {severity || 'info'}
        </span>
    );
}

function formatTime(isoString: string): string {
    try {
        const date = new Date(isoString);
        return date.toLocaleString('en-US', {
            month: 'short',
            day: 'numeric',
            hour: '2-digit',
            minute: '2-digit',
        });
    } catch {
        return isoString;
    }
}
