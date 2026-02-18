'use client';

import { useState } from 'react';
import { normalizeAssistantText } from '@/lib/normalizeAssistantText';

// ─── Backend payload shape ───────────────────────────────────────────────────
interface FinancialInsightRaw {
    headline: string;
    why_it_matters: string;
    key_facts: string[];
    risk_flags: string[];
    confidence: number;
    sources: {
        price_source?: string;
        headlines?: Array<string | { title: string; sentiment?: string; confidence?: number; driver?: string; rationale?: string; source?: string; url?: string; published_at?: string }>;
    };
    generated_by: 'template' | 'llm' | 'hybrid' | 'fallback';
    request_id?: string;
}

// ─── InsightViewModel ────────────────────────────────────────────────────────
interface Headline {
    title: string;
    sentiment: 'bullish' | 'bearish' | 'neutral';
    confidence: number;
    driver: string;
    rationale: string;
    source: string;
    url?: string;
    timeAgo?: string;
}

interface MetricChip {
    label: string;
    value: string;
    color: 'green' | 'red' | 'amber' | 'slate' | 'blue';
}

interface InsightViewModel {
    title: string;
    summary: string;
    whyItMatters: string;
    metrics: MetricChip[];
    riskFlags: Array<{ label: string; color: string }>;
    headlines: Headline[];
    confidence: number;
    confidencePct: number;
    confidenceExplanation: string;
    generatedBy: string;
    dataMissing: Array<{ label: string; reason: string }>;
    isUnavailable: boolean;
}

// ─── Mapping function ────────────────────────────────────────────────────────
function mapInsightToViewModel(raw: FinancialInsightRaw): InsightViewModel {
    const isUnavailable = raw.generated_by === 'fallback' ||
        raw.headline === 'Market insight unavailable' ||
        raw.headline === 'Market insight temporarily unavailable';

    const confidencePct = typeof raw.confidence === 'number' && isFinite(raw.confidence)
        ? Math.round(raw.confidence * 100) : 0;

    // Parse metrics from key_facts
    const metrics: MetricChip[] = [];
    const remainingFacts: string[] = [];
    const dataMissing: Array<{ label: string; reason: string }> = [];

    for (const fact of (raw.key_facts || [])) {
        const lower = fact.toLowerCase();
        // Price
        const priceMatch = fact.match(/(?:price|current)[:\s]*\$?([\d,]+\.?\d*)/i);
        if (priceMatch) {
            metrics.push({ label: 'Price', value: `$${priceMatch[1]}`, color: 'blue' });
            continue;
        }
        // 24h change
        const change24Match = fact.match(/24h?\s*(?:change|return)[:\s]*([+-]?[\d.]+%?)/i);
        if (change24Match) {
            const val = change24Match[1];
            const isNeg = val.startsWith('-');
            metrics.push({ label: '24h', value: val.includes('%') ? val : `${val}%`, color: isNeg ? 'red' : 'green' });
            continue;
        }
        // 7d change
        const change7dMatch = fact.match(/7d?\s*(?:change|return)[:\s]*([+-]?[\d.]+%?)/i);
        if (change7dMatch) {
            const val = change7dMatch[1];
            const isNeg = val.startsWith('-');
            metrics.push({ label: '7d', value: val.includes('%') ? val : `${val}%`, color: isNeg ? 'red' : 'green' });
            continue;
        }
        // Volatility
        if (lower.includes('volatility')) {
            const volMatch = fact.match(/(low|medium|high|extreme)[\s-]*(?:volatility)?/i) ||
                             fact.match(/volatility[:\s]*(low|medium|high|extreme)/i);
            if (volMatch) {
                const level = volMatch[1].toLowerCase();
                const color = level === 'high' || level === 'extreme' ? 'red' as const : level === 'medium' ? 'amber' as const : 'green' as const;
                metrics.push({ label: 'Volatility', value: level.charAt(0).toUpperCase() + level.slice(1), color });
                continue;
            }
        }
        // Fee
        const feeMatch = fact.match(/fee[s]?[:\s]*\$?([\d.]+%?)/i);
        if (feeMatch) {
            metrics.push({ label: 'Fee', value: feeMatch[1].includes('%') ? feeMatch[1] : `$${feeMatch[1]}`, color: 'amber' });
            continue;
        }
        // Size
        const sizeMatch = fact.match(/(?:size|notional)[:\s]*\$?([\d.,]+)/i);
        if (sizeMatch) {
            metrics.push({ label: 'Size', value: `$${sizeMatch[1]}`, color: 'slate' });
            continue;
        }
        // Trend
        const trendMatch = fact.match(/trend[:\s]*(bullish|bearish|flat|up|down|sideways|neutral)/i);
        if (trendMatch) {
            const t = trendMatch[1].toLowerCase();
            const color = (t === 'bullish' || t === 'up') ? 'green' as const : (t === 'bearish' || t === 'down') ? 'red' as const : 'slate' as const;
            metrics.push({ label: 'Trend', value: t.charAt(0).toUpperCase() + t.slice(1), color });
            continue;
        }
        remainingFacts.push(fact);
    }

    // Parse headlines
    const headlines: Headline[] = [];
    if (raw.sources?.headlines) {
        for (const h of raw.sources.headlines.slice(0, 5)) {
            if (typeof h === 'string') {
                headlines.push({ title: h, sentiment: 'neutral', confidence: 0, driver: 'none', rationale: '', source: 'Unknown' });
            } else {
                headlines.push({
                    title: h.title || '',
                    sentiment: (h.sentiment === 'bullish' || h.sentiment === 'bearish') ? h.sentiment : 'neutral',
                    confidence: typeof h.confidence === 'number' ? h.confidence : 0,
                    driver: h.driver || 'none',
                    rationale: h.rationale || '',
                    source: h.source || 'Unknown',
                    url: h.url,
                    timeAgo: h.published_at ? formatTimeAgo(h.published_at) : undefined,
                });
            }
        }
    }

    // Data missing detection
    if (raw.risk_flags?.includes('no_candle_data')) {
        dataMissing.push({ label: 'Trend data', reason: 'Candle feed not configured or unavailable' });
    }
    if (raw.risk_flags?.includes('price_unavailable')) {
        dataMissing.push({ label: 'Price', reason: 'Market data provider returned no price' });
    }
    if (raw.risk_flags?.includes('news_empty')) {
        dataMissing.push({ label: 'Headlines', reason: 'No recent news found — check RSS/GDELT feed config' });
    }
    if (raw.risk_flags?.includes('headlines_fetch_failed')) {
        dataMissing.push({ label: 'Headlines', reason: 'News fetch failed — check feed configuration' });
    }

    // Parse risk flags
    const riskFlags = (raw.risk_flags || [])
        .filter(f => !['no_candle_data', 'price_unavailable', 'news_empty', 'headlines_fetch_failed'].includes(f))
        .map(flag => {
            const cfg = RISK_FLAG_CONFIG[flag];
            return cfg || { label: flag.replace(/_/g, ' '), color: 'theme-elevated theme-text-secondary border theme-border' };
        });

    // Confidence explanation
    let confidenceExplanation = '';
    if (confidencePct >= 80) confidenceExplanation = 'High confidence: Price data, trend, and market context all available';
    else if (confidencePct >= 60) confidenceExplanation = 'Good confidence: Most data available, some gaps';
    else if (confidencePct >= 30) confidenceExplanation = 'Low confidence: Significant data gaps — proceed with caution';
    else confidenceExplanation = 'Very low confidence: Minimal market data available';

    // Build summary from remaining facts
    const summary = remainingFacts.length > 0
        ? remainingFacts.slice(0, 3).join('. ').replace(/\.\./g, '.') + (remainingFacts.length > 3 ? '.' : '')
        : '';

    return {
        title: raw.headline,
        summary,
        whyItMatters: raw.why_it_matters,
        metrics,
        riskFlags,
        headlines,
        confidence: raw.confidence,
        confidencePct,
        confidenceExplanation,
        generatedBy: raw.generated_by === 'hybrid' || raw.generated_by === 'llm' ? 'AI-Enhanced' : 'Auto-Generated',
        dataMissing,
        isUnavailable,
    };
}

function formatTimeAgo(dateStr: string): string {
    try {
        const diff = Date.now() - new Date(dateStr).getTime();
        const mins = Math.floor(diff / 60000);
        if (mins < 60) return `${mins}m ago`;
        const hours = Math.floor(mins / 60);
        if (hours < 24) return `${hours}h ago`;
        return `${Math.floor(hours / 24)}d ago`;
    } catch { return ''; }
}

// ─── Risk flag config ────────────────────────────────────────────────────────
const RISK_FLAG_CONFIG: Record<string, { label: string; color: string }> = {
    high_volatility: { label: 'High Volatility', color: 'theme-elevated theme-text border theme-border' },
    thin_notional: { label: 'Small Size', color: 'theme-elevated theme-text border theme-border' },
    paper_mode: { label: 'Paper Mode', color: 'theme-elevated theme-text border theme-border' },
    live_disabled: { label: 'LIVE Disabled', color: 'theme-elevated theme-text border theme-border' },
    high_fee_impact: { label: 'High Fee Impact', color: 'theme-elevated theme-text border theme-border' },
};

// ─── Metric chip colors ──────────────────────────────────────────────────────
const CHIP_COLORS: Record<string, string> = {
    green: 'theme-elevated theme-text border theme-border',
    red: 'theme-elevated theme-text border theme-border',
    amber: 'theme-elevated theme-text border theme-border',
    blue: 'theme-elevated theme-text border theme-border',
    slate: 'theme-elevated theme-text-secondary border theme-border',
};

function confidenceColor(c: number): string {
    if (c > 0.6) return 'theme-elevated font-bold theme-text';
    if (c >= 0.3) return 'theme-elevated font-semibold theme-text';
    return 'theme-elevated theme-text';
}

// ─── Component ───────────────────────────────────────────────────────────────
interface FinancialInsightCardProps {
    insight: FinancialInsightRaw | null;
    newsEnabled?: boolean;
}

export default function FinancialInsightCard({ insight, newsEnabled = true }: FinancialInsightCardProps) {
    const [showTooltip, setShowTooltip] = useState(false);

    if (!insight) return null;

    const vm = mapInsightToViewModel(insight);

    if (vm.isUnavailable) {
        return (
            <div className="p-3 rounded-lg border theme-border theme-surface text-sm theme-text-secondary">
                Market insight temporarily unavailable. Proceed with your own analysis.
            </div>
        );
    }

    return (
        <div className="rounded-lg border theme-border theme-elevated overflow-hidden font-[system-ui] text-[15px] leading-[1.5]">
            {/* Title row */}
            <div className="px-3 pt-3 pb-2 flex items-start justify-between gap-2">
                <p className="text-sm font-medium theme-text leading-snug flex-1">
                    {normalizeAssistantText(vm.title)}
                </p>
                <div className="flex items-center gap-2 shrink-0">
                    {/* Confidence badge with tooltip */}
                    <div className="relative">
                        <button
                            className={`px-2 py-1 rounded-lg text-xs font-medium cursor-help ${confidenceColor(vm.confidence)}`}
                            onMouseEnter={() => setShowTooltip(true)}
                            onMouseLeave={() => setShowTooltip(false)}
                        >
                            {vm.confidencePct}%
                        </button>
                        {showTooltip && (
                            <div className="absolute right-0 top-full mt-1 z-50 w-48 p-2 rounded-lg bg-neutral-900 text-neutral-200 text-xs shadow-xl border border-neutral-700">
                                {vm.confidenceExplanation}
                            </div>
                        )}
                    </div>
                    <span className="px-2 py-1 rounded-lg text-xs theme-elevated theme-text-secondary">
                        {vm.generatedBy}
                    </span>
                </div>
            </div>

            {/* Key Metrics Chips */}
            {vm.metrics.length > 0 && (
                <div className="px-3 pb-2 flex flex-wrap gap-2">
                    {vm.metrics.map((m, i) => (
                        <span
                            key={i}
                            className={`inline-flex items-center gap-1 px-2 py-1 rounded-lg text-xs font-medium border ${CHIP_COLORS[m.color]}`}
                        >
                            <span className="text-xs opacity-70">{m.label}</span>
                            {m.value}
                        </span>
                    ))}
                </div>
            )}

            {/* Why it matters */}
            <div className="px-3 pb-2">
                <p className="text-xs font-medium theme-text-secondary mb-1">Why it matters for this trade</p>
                <p className="text-sm theme-text-secondary leading-relaxed">
                    {normalizeAssistantText(vm.whyItMatters)}
                </p>
            </div>

            {/* Summary (remaining key facts) */}
            {vm.summary && (
                <div className="px-3 pb-2">
                    <p className="text-xs theme-text-secondary leading-relaxed">
                        {normalizeAssistantText(vm.summary)}
                    </p>
                </div>
            )}

            {/* Risk flags */}
            {vm.riskFlags.length > 0 && (
                <div className="px-3 pb-2 flex flex-wrap gap-1">
                    {vm.riskFlags.map((flag, i) => (
                        <span
                            key={i}
                            className={`inline-flex items-center px-2 py-1 rounded-lg text-xs border ${flag.color}`}
                        >
                            {flag.label}
                        </span>
                    ))}
                </div>
            )}

            {/* Data missing warnings */}
            {vm.dataMissing.length > 0 && (
                <div className="px-3 pb-2 space-y-1">
                    {vm.dataMissing.map((dm, i) => (
                        <div key={i} className="flex items-start gap-2 text-xs theme-text-secondary">
                            <span className="shrink-0 mt-1">&#9888;</span>
                            <span><span className="font-medium">{dm.label}:</span> {dm.reason}</span>
                        </div>
                    ))}
                </div>
            )}

            {/* News Pulse summary */}
            {newsEnabled && vm.headlines.length > 0 && (
                <div className="border-t theme-border px-3 py-2">
                    <div className="flex items-center gap-2 flex-wrap">
                        <span className="text-xs font-medium theme-text-muted">News Pulse</span>
                        {(() => {
                            const bullish = vm.headlines.filter(h => h.sentiment === 'bullish').length;
                            const bearish = vm.headlines.filter(h => h.sentiment === 'bearish').length;
                            const neutral = vm.headlines.filter(h => h.sentiment === 'neutral').length;
                            const net = bullish > bearish ? 'Bullish' : bearish > bullish ? 'Bearish' : 'Mixed';
                            const netColor = net === 'Bullish' ? 'text-[var(--color-status-success)]' : net === 'Bearish' ? 'text-[var(--color-status-error)]' : 'theme-text-muted';
                            // Dominant driver: most common non-neutral sentiment
                            const dominant = bullish >= bearish ? (bullish > 0 ? 'bullish momentum' : 'neutral tone') : 'bearish pressure';
                            return (
                                <div className="flex items-center gap-2 text-xs flex-wrap">
                                    <span className={`font-semibold ${netColor}`}>{net}</span>
                                    <span className="theme-text-muted">({bullish}&#8593; {bearish}&#8595; {neutral}&#8212;)</span>
                                    <span className="theme-text-muted">{vm.headlines.length} source{vm.headlines.length !== 1 ? 's' : ''}</span>
                                    <span className="theme-text-muted">&#183; {vm.confidencePct}% conf</span>
                                    <span className="theme-text-muted">&#183; driver: {dominant}</span>
                                </div>
                            );
                        })()}
                    </div>
                </div>
            )}

            {/* Headlines section */}
            {newsEnabled && (
                <div className="border-t theme-border px-3 py-2">
                    <div className="text-xs font-medium theme-text-muted mb-2">Recent Headlines</div>
                    {vm.headlines.length > 0 ? (
                        <div className="space-y-2">
                            {vm.headlines.map((h, i) => (
                                <div key={i} className="flex items-start gap-2">
                                    <span className={`shrink-0 mt-1 px-2 py-1 rounded-lg text-xs ${
                                        h.sentiment === 'bullish' ? 'theme-elevated text-[var(--color-status-success)]' :
                                        h.sentiment === 'bearish' ? 'theme-elevated text-[var(--color-status-error)]' :
                                        'theme-elevated theme-text-muted'
                                    }`}>
                                        {h.sentiment === 'bullish' ? '\u2191' : h.sentiment === 'bearish' ? '\u2193' : '\u2212'}
                                    </span>
                                    <div className="flex-1 min-w-0">
                                        <div className="text-xs leading-snug line-clamp-2">
                                            {h.url ? (
                                                <a
                                                    href={h.url}
                                                    target="_blank"
                                                    rel="noopener noreferrer"
                                                    className="text-[#4a7bc8] hover:text-[#6b9ae8] hover:underline focus:outline-none focus:ring-2 focus:ring-[var(--color-focus-ring)] focus:ring-offset-1 rounded inline-flex items-center gap-1 dark:text-[#7ba3f5] dark:hover:text-[#9bb8f8]"
                                                    title={h.title}
                                                >
                                                    {h.title}
                                                    <span className="opacity-70 text-[10px]" aria-hidden>↗</span>
                                                </a>
                                            ) : (
                                                <a
                                                    href={`https://www.google.com/search?q=${encodeURIComponent(h.title)}`}
                                                    target="_blank"
                                                    rel="noopener noreferrer"
                                                    className="text-[#4a7bc8] hover:text-[#6b9ae8] hover:underline focus:outline-none focus:ring-2 focus:ring-[var(--color-focus-ring)] focus:ring-offset-1 rounded inline-flex items-center gap-1 dark:text-[#7ba3f5] dark:hover:text-[#9bb8f8]"
                                                    title={h.title}
                                                >
                                                    {h.title}
                                                    <span className="opacity-70 text-[10px]" aria-hidden>↗</span>
                                                </a>
                                            )}
                                        </div>
                                        {/* Grounded rationale: quote from headline justifying sentiment */}
                                        {h.rationale ? (
                                            <div className="text-xs theme-text-muted italic">
                                                {h.sentiment !== 'neutral' ? (
                                                    <>{h.sentiment === 'bullish' ? 'Positive signal' : 'Risk signal'}: &ldquo;{h.rationale}&rdquo;</>
                                                ) : (
                                                    <>&ldquo;{h.rationale}&rdquo;</>
                                                )}
                                            </div>
                                        ) : h.title ? (
                                            <div className="text-xs theme-text-muted italic">
                                                &ldquo;{h.title}&rdquo;
                                            </div>
                                        ) : null}
                                        <div className="text-xs theme-text-muted flex items-center gap-1 flex-wrap">
                                            <span>{h.source}{h.timeAgo ? ` \u00b7 ${h.timeAgo}` : ''}</span>
                                            {h.confidence > 0 && (
                                                <span className="px-1 py-1 rounded-lg theme-elevated theme-text-muted">{Math.round(h.confidence * 100)}% conf</span>
                                            )}
                                            {h.driver && h.driver !== 'none' && h.driver !== 'mixed' && (
                                                <span className="px-1 py-1 rounded-lg theme-elevated theme-text-muted">driver: {h.driver}</span>
                                            )}
                                        </div>
                                    </div>
                                </div>
                            ))}
                        </div>
                    ) : (
                        <div className="space-y-2">
                            <div className="text-xs theme-text-secondary flex items-start gap-2">
                                <span>&#9888;</span>
                                <span>No recent headlines found for this asset in the last 48h.</span>
                            </div>
                            {/* Show diagnostic reason from dataMissing / risk_flags */}
                            {vm.dataMissing.filter(dm => dm.label === 'Headlines').map((dm, i) => (
                                <div key={i} className="text-xs theme-text-muted pl-5">
                                    {dm.reason}
                                </div>
                            ))}
                            <div className="text-xs pl-5 flex items-center gap-2 mt-1">
                                <button
                                    onClick={async () => {
                                        try {
                                            await fetch('/api/v1/news/ingest', { method: 'POST', headers: { 'X-Dev-Tenant': 't_default' } });
                                        } catch { /* best-effort */ }
                                    }}
                                    className="btn-primary text-xs px-2 py-1 rounded-lg font-medium transition-colors"
                                >
                                    Refresh News
                                </button>
                                <span className="theme-text-muted">Check RSS/GDELT config or try broader query</span>
                            </div>
                        </div>
                    )}
                </div>
            )}

            {!newsEnabled && (
                <div className="border-t theme-border px-3 py-2">
                    <div className="text-xs theme-text-muted">
                        News toggle is OFF — headline analysis disabled
                    </div>
                </div>
            )}
        </div>
    );
}
