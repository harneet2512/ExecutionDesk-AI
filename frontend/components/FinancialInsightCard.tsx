'use client';

import { useEffect, useState } from 'react';
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
    news_outcome?: {
        queries?: string[];
        lookback?: string;
        sources?: string[];
        status?: 'ok' | 'empty' | 'error';
        reason?: string;
        items?: number;
    };
    impact_summary?: string;
    current_step_asset?: string;
    queued_steps_notice?: string;
    market_headlines?: Array<string | { title: string; sentiment?: string; confidence?: number; driver?: string; rationale?: string; source?: string; url?: string; published_at?: string }>;
    asset_news_evidence?: EvidencePayload;
    market_news_evidence?: EvidencePayload | null;
}

interface EvidencePayload {
    assets?: string[];
    queries: string[];
    lookback: string;
    sources: string[];
    status: 'ok' | 'empty' | 'error';
    items: Array<{ title?: string; source?: string; published_at?: string; url?: string; snippet?: string }>;
    reason_if_empty_or_error?: string;
    rationale?: string;
    artifact_id?: string;
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
    marketHeadlines: Headline[];
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

    const marketHeadlines: Headline[] = [];
    if (raw.market_headlines) {
        for (const h of raw.market_headlines.slice(0, 5)) {
            if (typeof h === 'string') {
                marketHeadlines.push({ title: h, sentiment: 'neutral', confidence: 0, driver: 'none', rationale: '', source: 'Unknown' });
            } else {
                marketHeadlines.push({
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
        marketHeadlines,
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

function safeHref(url?: string): string | null {
    if (!url || typeof url !== 'string') return null;
    try {
        const parsed = new URL(url);
        if (parsed.protocol === 'http:' || parsed.protocol === 'https:') return parsed.toString();
        return null;
    } catch {
        return null;
    }
}

function normalizeEvidencePayload(payload: unknown): EvidencePayload | null {
    if (!payload || typeof payload !== 'object') return null;
    const p = payload as Partial<EvidencePayload>;
    if (!Array.isArray(p.queries) || !Array.isArray(p.sources) || !Array.isArray(p.items) || typeof p.lookback !== 'string' || typeof p.status !== 'string') {
        return null;
    }
    const status = (p.status === 'ok' || p.status === 'empty' || p.status === 'error') ? p.status : 'error';
    return {
        assets: Array.isArray(p.assets) ? p.assets : undefined,
        queries: p.queries.map(v => String(v)),
        lookback: p.lookback,
        sources: p.sources.map(v => String(v)),
        status,
        items: p.items.map((item) => ({
            title: typeof item?.title === 'string' ? item.title : undefined,
            source: typeof item?.source === 'string' ? item.source : undefined,
            published_at: typeof item?.published_at === 'string' ? item.published_at : undefined,
            url: safeHref(item?.url) ?? undefined,
            snippet: typeof item?.snippet === 'string' ? item.snippet : undefined,
        })),
        reason_if_empty_or_error: typeof p.reason_if_empty_or_error === 'string' ? p.reason_if_empty_or_error : '',
        rationale: typeof p.rationale === 'string' ? p.rationale : '',
        artifact_id: typeof p.artifact_id === 'string' ? p.artifact_id : undefined,
    };
}

// ─── Component ───────────────────────────────────────────────────────────────
interface FinancialInsightCardProps {
    insight: FinancialInsightRaw | null;
    newsEnabled?: boolean;
}

export default function FinancialInsightCard({ insight, newsEnabled = true }: FinancialInsightCardProps) {
    const [showTooltip, setShowTooltip] = useState(false);
    const [showAll, setShowAll] = useState(false);
    const [activeEvidence, setActiveEvidence] = useState<'asset' | 'market' | null>(null);

    if (!insight) {
        if (!newsEnabled) return null;
        return (
            <div className="mt-3 p-3 rounded-lg border theme-surface theme-border text-sm">
                <div className="flex items-center gap-2 theme-text-secondary">
                    <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4 text-[var(--color-status-warning)]" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                    </svg>
                    <span>Market insight data unavailable. Confirm or cancel at your discretion.</span>
                </div>
            </div>
        );
    }

    const vm = mapInsightToViewModel(insight);
    const newsOutcome = insight.news_outcome;
    const assetEvidence = normalizeEvidencePayload(insight.asset_news_evidence);
    const marketEvidence = normalizeEvidencePayload(insight.market_news_evidence);
    const headlineLimit = showAll ? 5 : 3;
    const assetLabel = insight.current_step_asset || ((assetEvidence?.assets && assetEvidence.assets[0]) || 'Asset');
    const coverageSources = (newsOutcome?.sources || assetEvidence?.sources || []).join(' + ');
    const coverageQueries = (newsOutcome?.queries || assetEvidence?.queries || []).join(', ');
    const coverageLookback = newsOutcome?.lookback || assetEvidence?.lookback || '';
    const messageLookback = coverageLookback || '24h';
    const coverageItems = typeof newsOutcome?.items === 'number'
        ? newsOutcome.items
        : ((assetEvidence?.items || []).length);
    const coverageMissingReason = [
        !coverageSources ? 'sources unavailable' : '',
        !coverageLookback ? 'lookback unavailable' : '',
        !coverageQueries ? 'queries unavailable' : '',
    ].filter(Boolean).join('; ');
    const debugPreconfirmNews = process.env.NEXT_PUBLIC_DEBUG_PRECONFIRM_NEWS === '1';

    useEffect(() => {
        if (!debugPreconfirmNews) return;
        console.info('[PRECONFIRM_NEWS][FinancialInsightCard]', {
            hasInsight: !!insight,
            newsEnabled,
            hasNewsOutcome: !!insight?.news_outcome,
            hasAssetEvidence: !!assetEvidence,
            hasMarketEvidence: !!marketEvidence,
            currentStepAsset: insight?.current_step_asset,
            assetEvidenceKeys: assetEvidence ? Object.keys(assetEvidence) : [],
            marketEvidenceKeys: marketEvidence ? Object.keys(marketEvidence) : [],
        });
    }, [debugPreconfirmNews, insight, newsEnabled, assetEvidence, marketEvidence]);

    const renderHeadlines = (items: Headline[]) => (
        <div className="space-y-2">
            {items.slice(0, headlineLimit).map((h, i) => (
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
                            {safeHref(h.url) ? (
                                <a
                                    href={safeHref(h.url) || undefined}
                                    target="_blank"
                                    rel="noopener noreferrer"
                                    className="text-[#4a7bc8] hover:text-[#6b9ae8] hover:underline focus:outline-none focus:ring-2 focus:ring-[var(--color-focus-ring)] focus:ring-offset-1 rounded inline-flex items-center gap-1 dark:text-[#7ba3f5] dark:hover:text-[#9bb8f8]"
                                    title={h.title}
                                >
                                    {h.title}
                                    <span className="opacity-70 text-[10px]" aria-hidden>↗</span>
                                </a>
                            ) : (
                                <span className="theme-text">{h.title}</span>
                            )}
                        </div>
                        <div className="text-xs theme-text-muted flex items-center gap-1 flex-wrap">
                            <span>{h.source}{h.timeAgo ? ` \u00b7 ${h.timeAgo}` : ''}</span>
                        </div>
                    </div>
                </div>
            ))}
        </div>
    );

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
            {newsEnabled && (vm.headlines.length > 0 || vm.marketHeadlines.length > 0) && (
                <div className="border-t theme-border px-3 py-2">
                    <div className="flex items-center gap-2 flex-wrap">
                        <span className="text-xs font-medium theme-text-muted">News Pulse</span>
                        {(() => {
                            const combined = [...vm.headlines, ...vm.marketHeadlines];
                            const bullish = combined.filter(h => h.sentiment === 'bullish').length;
                            const bearish = combined.filter(h => h.sentiment === 'bearish').length;
                            const neutral = combined.filter(h => h.sentiment === 'neutral').length;
                            const net = bullish > bearish ? 'Bullish' : bearish > bullish ? 'Bearish' : 'Mixed';
                            const netColor = net === 'Bullish' ? 'text-[var(--color-status-success)]' : net === 'Bearish' ? 'text-[var(--color-status-error)]' : 'theme-text-muted';
                            // Dominant driver: most common non-neutral sentiment
                            const dominant = bullish >= bearish ? (bullish > 0 ? 'bullish momentum' : 'neutral tone') : 'bearish pressure';
                            return (
                                <div className="flex items-center gap-2 text-xs flex-wrap">
                                    <span className={`font-semibold ${netColor}`}>{net}</span>
                                    <span className="theme-text-muted">({bullish}&#8593; {bearish}&#8595; {neutral}&#8212;)</span>
                                    <span className="theme-text-muted">{combined.length} source{combined.length !== 1 ? 's' : ''}</span>
                                    <span className="theme-text-muted">&#183; {vm.confidencePct}% conf</span>
                                    <span className="theme-text-muted">&#183; driver: {dominant}</span>
                                </div>
                            );
                        })()}
                    </div>
                </div>
            )}

            {/* Smart pre-confirm news section */}
            {newsEnabled && (
                <div className="border-t theme-border px-3 py-2">
                    <div className="text-xs font-medium theme-text-muted mb-2">{`News (${assetLabel})`}</div>
                    {vm.headlines.length > 0 ? (
                        renderHeadlines(vm.headlines)
                    ) : (
                        <div className="space-y-2">
                            <div className="text-xs theme-text-secondary flex items-start gap-2">
                                <span>&#9888;</span>
                                <span>
                                    {newsOutcome?.status === 'error'
                                        ? `News unavailable for ${assetLabel} right now (provider error).`
                                        : `No relevant news found for ${assetLabel} in the last ${messageLookback}.`}
                                </span>
                            </div>
                            {newsOutcome?.reason && (
                                <div className="text-xs theme-text-muted pl-5">
                                    {newsOutcome.reason}
                                </div>
                            )}
                        </div>
                    )}

                    {vm.marketHeadlines.length > 0 || marketEvidence ? (
                        <div className="mt-3 border-t theme-border pt-2">
                            <div className="text-xs font-medium theme-text-muted mb-1">General market news</div>
                            <div className="text-xs theme-text-secondary mb-2">
                                {marketEvidence?.rationale || `No asset-specific headlines returned, so I'm showing broader market headlines most likely to impact ${assetLabel}.`}
                            </div>
                            {vm.marketHeadlines.length > 0 ? (
                                renderHeadlines(vm.marketHeadlines)
                            ) : (
                                <div className="text-xs theme-text-muted">Market news unavailable right now. Please retry shortly.</div>
                            )}
                        </div>
                    ) : null}

                    <div className="mt-3 text-xs theme-text-secondary">
                        <span className="font-medium">Impact summary:</span> {insight.impact_summary || 'No headline signal found; decision is based on price/portfolio checks only.'}
                    </div>
                    {insight.queued_steps_notice && (
                        <div className="mt-1 text-xs theme-text-muted">{insight.queued_steps_notice}</div>
                    )}
                    <div className="mt-1 text-xs theme-text-muted">
                        {`Sources: ${coverageSources || 'unavailable'} · Lookback: ${coverageLookback || 'unavailable'} · Queries: ${coverageQueries || 'unavailable'} · Items: ${coverageItems}`}
                        {coverageMissingReason ? ` (${coverageMissingReason})` : ''}
                    </div>
                    <div className="mt-2 flex items-center gap-2">
                        <button
                            type="button"
                            disabled={!assetEvidence}
                            title={assetEvidence ? 'Open asset evidence' : 'Evidence unavailable'}
                            onClick={() => setActiveEvidence('asset')}
                            className={`px-2 py-1 rounded-lg text-xs border ${assetEvidence ? 'theme-elevated theme-text border theme-border' : 'theme-elevated theme-text-muted border theme-border opacity-60 cursor-not-allowed'}`}
                        >
                            {`News evidence (${assetLabel}, ${messageLookback})`}
                        </button>
                        <button
                            type="button"
                            disabled={!marketEvidence || (!marketEvidence.artifact_id && marketEvidence.items.length === 0)}
                            title={marketEvidence ? 'Open market fallback evidence' : 'Evidence unavailable'}
                            onClick={() => setActiveEvidence('market')}
                            className={`px-2 py-1 rounded-lg text-xs border ${marketEvidence && (marketEvidence.artifact_id || marketEvidence.items.length > 0) ? 'theme-elevated theme-text border theme-border' : 'theme-elevated theme-text-muted border theme-border opacity-60 cursor-not-allowed'}`}
                        >
                            {`Market news evidence (${messageLookback})`}
                        </button>
                        <button
                            type="button"
                            onClick={() => setShowAll(v => !v)}
                            className="px-2 py-1 rounded-lg text-xs border theme-border theme-elevated theme-text"
                        >
                            {showAll ? 'View less' : 'View details'}
                        </button>
                    </div>
                </div>
            )}

            {!newsEnabled && (
                <div className="border-t theme-border px-3 py-2">
                    <div className="text-xs theme-text-muted">
                        News toggle is OFF — headline analysis disabled
                    </div>
                </div>
            )}

            {activeEvidence && (
                <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
                    <div className="w-[90vw] max-w-3xl rounded-xl border theme-border theme-surface p-4">
                        <div className="flex items-center justify-between mb-2">
                            <div className="text-sm font-medium theme-text">
                                {activeEvidence === 'asset' ? 'Asset news evidence' : 'Market fallback evidence'}
                            </div>
                            <button
                                type="button"
                                className="text-xs px-2 py-1 rounded-lg border theme-border theme-elevated theme-text"
                                onClick={() => setActiveEvidence(null)}
                            >
                                Close
                            </button>
                        </div>
                        <pre className="text-xs overflow-auto max-h-[50vh] p-2 rounded-lg theme-elevated theme-text-secondary border theme-border">
                            {JSON.stringify((activeEvidence === 'asset' ? assetEvidence : marketEvidence) || { error: 'Evidence unavailable' }, null, 2)}
                        </pre>
                        <div className="mt-2 space-y-1 text-xs">
                            {((activeEvidence === 'asset' ? assetEvidence?.items : marketEvidence?.items) || [])
                                .filter(i => !!safeHref(i.url))
                                .map((item, idx) => (
                                    <a
                                        key={idx}
                                        href={safeHref(item.url) || undefined}
                                        target="_blank"
                                        rel="noopener noreferrer"
                                        className="block text-[#4a7bc8] hover:underline dark:text-[#7ba3f5]"
                                    >
                                        {item.title || item.url}
                                    </a>
                                ))}
                            {((activeEvidence === 'asset' ? assetEvidence?.items : marketEvidence?.items) || [])
                                .filter(i => !safeHref(i.url))
                                .map((item, idx) => (
                                    <div key={`nolink-${idx}`} className="theme-text-secondary">
                                        {item.title || 'Untitled evidence item'}
                                    </div>
                                ))}
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
}
