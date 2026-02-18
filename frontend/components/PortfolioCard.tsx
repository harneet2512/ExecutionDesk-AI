'use client';

import { useState, useEffect } from 'react';
import Link from 'next/link';
import { apiFetchSafe } from '@/lib/api';

interface Holding {
    asset_symbol: string;
    qty: number;
    usd_value: number;
    current_price?: number;
}

interface AllocationRow {
    asset_symbol: string;
    pct: number;
    usd_value: number;
}

interface Risk {
    concentration_pct_top1?: number;
    concentration_pct_top3?: number;
    risk_level?: string;
    diversification_score?: number;
}

interface Recommendation {
    title: string;
    description?: string;
    priority?: string;
}

interface EvidenceRefs {
    accounts_call_id?: string;
    prices_call_ids?: string[];
    orders_call_id?: string;
}

interface PortfolioBrief {
    as_of?: string;
    mode?: string;
    total_value_usd?: number;
    cash_usd?: number;
    holdings?: Holding[];
    allocation?: AllocationRow[];
    risk?: Risk;
    recommendations?: Recommendation[];
    warnings?: string[];
    evidence_refs?: EvidenceRefs;
}

interface PortfolioCardProps {
    runId: string;
    brief?: PortfolioBrief;
}

export default function PortfolioCard({ runId, brief }: PortfolioCardProps) {
    const [data, setData] = useState<PortfolioBrief | null>(brief || null);
    const [loading, setLoading] = useState(!brief);
    const [error, setError] = useState<string | null>(null);
    const [showEvidence, setShowEvidence] = useState(false);

    useEffect(() => {
        if (brief) {
            setData(brief);
            return;
        }

        async function fetchPortfolio() {
            try {
                const trace = await apiFetchSafe(`/api/v1/runs/${runId}/trace`);
                if (!trace) throw new Error('Failed to fetch');
                // Extract portfolio_brief from trace artifacts
                if (trace.portfolio_brief) {
                    setData(trace.portfolio_brief);
                }
            } catch (e: any) {
                setError(e.message);
            } finally {
                setLoading(false);
            }
        }

        fetchPortfolio();
    }, [runId, brief]);

    if (loading) {
        return (
            <div className="p-4 theme-elevated rounded-lg animate-pulse">
                <div className="h-4 bg-neutral-200 dark:bg-neutral-700 rounded w-1/3 mb-3"></div>
                <div className="h-3 bg-neutral-200 dark:bg-neutral-700 rounded w-1/2"></div>
            </div>
        );
    }

    if (error) {
        return (
            <div className="p-4 bg-[var(--color-status-error-bg)] border border-[var(--color-status-error)]/20 rounded-lg">
                <p className="text-sm text-[var(--color-status-error)]">Portfolio data unavailable: {error}</p>
            </div>
        );
    }

    if (!data) {
        return null;
    }

    // Format mode
    const modeStr = (data.mode || 'UNKNOWN').toString().replace('ExecutionMode.', '').toUpperCase();

    // Format timestamp
    let timestamp = data.as_of || '';
    try {
        const ts = new Date(timestamp);
        timestamp = ts.toLocaleString('en-US', {
            month: 'short', day: 'numeric', year: 'numeric',
            hour: '2-digit', minute: '2-digit'
        });
    } catch { }

    // Risk level styling
    const riskColors: Record<string, string> = {
        'LOW': 'theme-text-secondary theme-elevated',
        'MEDIUM': 'theme-text-secondary theme-elevated',
        'HIGH': 'theme-text theme-elevated',
        'VERY_HIGH': 'theme-text theme-elevated',
        'UNKNOWN': 'theme-text-muted theme-elevated'
    };

    const riskLevel = data.risk?.risk_level || 'UNKNOWN';
    const riskClass = riskColors[riskLevel] || riskColors['UNKNOWN'];

    // Count evidence
    const evidenceCount = (data.evidence_refs?.accounts_call_id ? 1 : 0) +
        (data.evidence_refs?.prices_call_ids?.length || 0) +
        (data.evidence_refs?.orders_call_id ? 1 : 0);

    return (
        <div className="theme-surface border theme-border rounded-lg overflow-hidden">
            {/* Header */}
            <div className="px-4 py-3 theme-elevated border-b theme-border flex items-center justify-between">
                <div className="flex items-center gap-2">
                    <span className="text-lg font-semibold theme-text">Portfolio Snapshot</span>
                    <span className={`px-2 py-0.5 text-xs font-medium rounded ${modeStr === 'LIVE' ? 'theme-elevated theme-text' : 'theme-elevated theme-text-secondary'}`}>
                        {modeStr}
                    </span>
                </div>
                <span className="text-xs theme-text-secondary">{timestamp}</span>
            </div>

            {/* Key Metrics */}
            <div className="px-4 py-3 grid grid-cols-2 gap-4 border-b theme-border">
                <div>
                    <div className="text-xs theme-text-secondary uppercase tracking-wide">Total Value</div>
                    <div className="text-xl font-bold theme-text">
                        ${(data.total_value_usd || 0).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                    </div>
                </div>
                <div>
                    <div className="text-xs theme-text-secondary uppercase tracking-wide">Cash</div>
                    <div className="text-xl font-bold theme-text">
                        ${(data.cash_usd || 0).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                    </div>
                </div>
            </div>

            {/* Holdings Table */}
            {data.holdings && data.holdings.length > 0 && (
                <div className="px-4 py-3 border-b theme-border">
                    <div className="text-sm font-medium theme-text-secondary mb-2">Holdings</div>
                    <table className="w-full text-sm">
                        <thead>
                            <tr className="text-xs theme-text-secondary uppercase tracking-wide">
                                <th className="text-left py-1">Asset</th>
                                <th className="text-right py-1">Qty</th>
                                <th className="text-right py-1">Value</th>
                                <th className="text-right py-1">Price</th>
                            </tr>
                        </thead>
                        <tbody>
                            {data.holdings.slice(0, 5).map((h, i) => (
                                <tr key={i} className="border-t theme-border">
                                    <td className="py-1.5 font-medium theme-text">{h.asset_symbol}</td>
                                    <td className="py-1.5 text-right theme-text-secondary">{typeof h.qty === 'number' ? h.qty.toFixed(6) : '\u2014'}</td>
                                    <td className="py-1.5 text-right theme-text">${typeof h.usd_value === 'number' ? h.usd_value.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : '\u2014'}</td>
                                    <td className="py-1.5 text-right theme-text-secondary">
                                        {h.current_price ? `$${h.current_price.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}` : '-'}
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                    {data.holdings.length > 5 && (
                        <div className="text-xs theme-text-secondary mt-1">
                            + {data.holdings.length - 5} more
                        </div>
                    )}
                </div>
            )}

            {/* Risk Summary - Enhanced */}
            {data.risk && (
                <div className="px-4 py-3 border-b theme-border">
                    <div className="flex items-center justify-between mb-2">
                        <div className="text-sm font-medium theme-text-secondary">Risk Assessment</div>
                        <span className={`px-2 py-1 text-xs font-medium rounded ${riskClass}`}>
                            {riskLevel.replace('_', ' ')}
                        </span>
                    </div>
                    <ul className="space-y-1 text-sm">
                        {/* Top position concentration */}
                        {data.risk.concentration_pct_top1 && data.risk.concentration_pct_top1 > 0 && (
                            <li className="theme-text-secondary">
                                Top position: {data.risk.concentration_pct_top1.toFixed(0)}% of portfolio
                            </li>
                        )}
                        {/* Diversification score */}
                        {typeof data.risk.diversification_score === 'number' && (
                            <li className="theme-text-secondary">
                                Diversification: {data.risk.diversification_score.toFixed(2)}/1.00
                            </li>
                        )}
                        {/* Crypto volatility warning */}
                        {data.holdings && data.holdings.some(h =>
                            ['BTC', 'ETH', 'SOL', 'AVAX', 'MATIC'].includes(h.asset_symbol.toUpperCase())
                        ) && (
                                <li className="text-[var(--color-status-warning)]">
                                    Crypto exposure: high volatility asset class
                                </li>
                            )}
                        {/* Small portfolio note */}
                        {(data.total_value_usd || 0) < 50 && (
                            <li className="theme-text-muted italic">
                                Note: Small portfolio - metrics sensitive to minor changes
                            </li>
                        )}
                        {/* High crypto concentration warning */}
                        {(() => {
                            if (!data.allocation) return null;
                            const cryptoSymbols = ['BTC', 'ETH', 'SOL', 'AVAX', 'MATIC', 'DOGE', 'XRP', 'ADA', 'DOT', 'LINK'];
                            const cryptoPct = data.allocation
                                .filter(a => cryptoSymbols.includes(a.asset_symbol.toUpperCase()))
                                .reduce((sum, a) => sum + (a.pct || 0), 0);
                            if (cryptoPct > 25) {
                                return (
                                    <li className="text-[var(--color-status-warning)]">
                                        Caution: {cryptoPct.toFixed(0)}% crypto allocation (higher volatility)
                                    </li>
                                );
                            }
                            return null;
                        })()}
                    </ul>
                </div>
            )}

            {/* Recommendations */}
            {data.recommendations && data.recommendations.length > 0 && (
                <div className="px-4 py-3 border-b theme-border">
                    <div className="text-sm font-medium theme-text-secondary mb-2">Recommendations</div>
                    <ul className="space-y-1">
                        {data.recommendations.slice(0, 3).map((rec, i) => (
                            <li key={i} className="text-sm theme-text-secondary">
                                <span className="font-medium theme-text">{rec.title}</span>
                                {rec.description && <span> - {rec.description}</span>}
                            </li>
                        ))}
                    </ul>
                </div>
            )}

            {/* Evidence Link */}
            {evidenceCount > 0 && (
                <div className="px-4 py-3 flex items-center justify-between">
                    <button
                        onClick={() => setShowEvidence(!showEvidence)}
                        className="text-sm theme-text-secondary hover:underline"
                    >
                        {showEvidence ? 'Hide evidence' : `View evidence (${evidenceCount} sources)`}
                    </button>
                    <Link
                        href={`/runs/${runId}`}
                        className="text-sm theme-text-secondary hover:underline"
                    >
                        Full run details
                    </Link>
                </div>
            )}

            {/* Evidence Panel */}
            {showEvidence && (
                <div className="px-4 py-3 theme-bg border-t theme-border">
                    <div className="text-sm theme-text-secondary font-medium mb-2">Sources of data:</div>
                    <div className="flex flex-wrap gap-2">
                        {data.evidence_refs?.accounts_call_id && (
                            <span className="inline-flex items-center gap-1 px-2.5 py-1 text-xs font-medium rounded-md theme-elevated theme-text-secondary hover:bg-[var(--color-fill-ghost-hover)] transition-colors cursor-default">
                                <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" /></svg>
                                Accounts API
                            </span>
                        )}
                        {data.evidence_refs?.prices_call_ids?.map((id, i) => (
                            <span key={i} className="inline-flex items-center gap-1 px-2.5 py-1 text-xs font-medium rounded-md theme-elevated theme-text-secondary hover:bg-[var(--color-fill-ghost-hover)] transition-colors cursor-default">
                                <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 12l3-3 3 3 4-4M8 21l4-4 4 4M3 4h18M4 4h16v12a1 1 0 01-1 1H5a1 1 0 01-1-1V4z" /></svg>
                                Price Feed {i + 1}
                            </span>
                        ))}
                        {data.evidence_refs?.orders_call_id && (
                            <span className="inline-flex items-center gap-1 px-2.5 py-1 text-xs font-medium rounded-md theme-elevated theme-text-secondary hover:bg-[var(--color-fill-ghost-hover)] transition-colors cursor-default">
                                <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" /></svg>
                                Order History
                            </span>
                        )}
                    </div>
                </div>
            )}
        </div>
    );
}
