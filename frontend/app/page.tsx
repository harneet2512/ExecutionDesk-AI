'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import { BRAND } from '@/src/config/brand';
import {
  ChartBarIcon, CheckCircleIcon, ArrowTrendingUpIcon,
  BoltIcon, GlobeAltIcon,
} from '@/components/icons';
import PriceTicker from '@/components/PriceTicker';
import { listRuns, fetchEvalDashboard, apiFetchSafe, getPerformance, Run } from '@/lib/api';
import { fmtCurrency, fmtPercent, fmtTimeAgo, fmtCompact, fmtProbability, gainLossClass } from '@/lib/format';
import { getStatusClasses, getStatusLabel } from '@/lib/statusColors';

const TICKER_SYMBOLS = ['BTC-USD', 'ETH-USD', 'SOL-USD'];

interface MarketItem {
  question: string;
  slug?: string;
  yes_price: number;
  volume: number;
  condition_id?: string;
}

export default function Home() {
  const router = useRouter();
  const [runsCount, setRunsCount] = useState<number | null>(null);
  const [recentRuns, setRecentRuns] = useState<Run[]>([]);
  const [evalsCount, setEvalsCount] = useState<number | null>(null);
  const [pnl, setPnl] = useState<number | null>(null);
  const [winRate, setWinRate] = useState<number | null>(null);
  const [markets, setMarkets] = useState<MarketItem[]>([]);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      const [runs, evals, perf, mkts] = await Promise.allSettled([
        listRuns(),
        fetchEvalDashboard(),
        getPerformance('30d'),
        apiFetchSafe('/api/v1/markets/popular?limit=6'),
      ]);
      if (cancelled) return;
      if (runs.status === 'fulfilled' && Array.isArray(runs.value)) {
        setRunsCount(runs.value.length);
        setRecentRuns(runs.value.slice(0, 5));
      }
      if (evals.status === 'fulfilled' && evals.value)
        setEvalsCount(evals.value.total_runs_evaluated ?? 0);
      if (perf.status === 'fulfilled' && perf.value?.summary) {
        setPnl(perf.value.summary.total_pnl);
        setWinRate(perf.value.summary.win_rate);
      }
      if (mkts.status === 'fulfilled' && mkts.value?.markets)
        setMarkets(mkts.value.markets.slice(0, 4));
      setLoaded(true);
    }
    load();
    return () => { cancelled = true; };
  }, []);

  const stats = [
    { label: 'Trading Runs', value: runsCount !== null ? String(runsCount) : '—', href: '/runs', icon: <ChartBarIcon className="w-5 h-5" /> },
    { label: 'Portfolio P&L', value: pnl !== null ? fmtCurrency(pnl) : '—', href: '/performance', icon: <ArrowTrendingUpIcon className="w-5 h-5" />, colorClass: gainLossClass(pnl) },
    { label: 'Win Rate', value: winRate !== null ? fmtPercent(winRate * 100) : '—', href: '/performance', icon: <CheckCircleIcon className="w-5 h-5" /> },
    { label: 'Evaluations', value: evalsCount !== null ? String(evalsCount) : '—', href: '/evals', icon: <CheckCircleIcon className="w-5 h-5" /> },
  ];

  return (
    <div className="flex-1 flex flex-col min-h-0 overflow-y-auto">
      <div className="max-w-6xl mx-auto w-full px-6 lg:px-8 py-8 page-enter">
        {/* Header row */}
        <div className="flex items-center justify-between mb-6">
          <div>
            <h1 className="text-xl font-semibold theme-text">{BRAND.name}</h1>
            <p className="text-sm theme-text-muted">{BRAND.tagline}</p>
          </div>
          <button
            onClick={() => router.push('/chat?suggestion=Buy+%24100+of+BTC')}
            className="flex items-center gap-2 px-4 py-2 btn-primary rounded-lg text-sm font-medium"
          >
            <BoltIcon className="w-4 h-4" />
            New Trade
          </button>
        </div>

        {/* Price ticker */}
        <div className="mb-6">
          <PriceTicker symbols={TICKER_SYMBOLS} />
        </div>

        {/* Stats row */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-6 stagger-enter">
          {stats.map((s) => (
            <Link key={s.label} href={s.href} className="metric-card group hover:border-[var(--color-border-strong)] transition-colors">
              <div className="flex items-center gap-2 mb-1">
                <span className="theme-text-muted group-hover:theme-text transition-colors">{s.icon}</span>
                <span className="metric-label !mb-0">{s.label}</span>
              </div>
              <div className={`text-xl font-bold tabular-nums ${s.colorClass || 'theme-text'} ${!loaded ? 'animate-pulse' : ''}`}>
                {s.value}
              </div>
            </Link>
          ))}
        </div>

        {/* Two-column: recent activity + market movers */}
        <div className="grid grid-cols-1 lg:grid-cols-5 gap-4">
          {/* Recent runs */}
          <div className="lg:col-span-3 border theme-border rounded-lg overflow-hidden">
            <div className="flex items-center justify-between px-4 py-3 theme-elevated">
              <span className="section-header !mb-0">Recent Activity</span>
              {runsCount !== null && runsCount > 0 && (
                <Link href="/runs" className="text-xs text-[var(--color-link)] hover:underline">View all</Link>
              )}
            </div>
            {recentRuns.length > 0 ? (
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Run</th>
                    <th>Status</th>
                    <th>Mode</th>
                    <th>Time</th>
                  </tr>
                </thead>
                <tbody>
                  {recentRuns.map((run) => {
                    const sc = getStatusClasses(run.status);
                    return (
                      <tr key={run.run_id}>
                        <td>
                          <Link href={`/runs/${run.run_id}`} className="font-mono text-xs text-[var(--color-link)] hover:underline">
                            {run.run_id.slice(0, 10)}
                          </Link>
                        </td>
                        <td><span className={`badge ${sc.bg} ${sc.text}`}>{getStatusLabel(run.status)}</span></td>
                        <td className="text-xs theme-text-muted">{run.execution_mode}</td>
                        <td className="text-xs tabular-nums theme-text-muted">{fmtTimeAgo(run.created_at)}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            ) : (
              <div className="px-4 py-10 text-center">
                <p className="text-sm theme-text-muted mb-3">No trading runs yet</p>
                <button
                  onClick={() => router.push('/chat?suggestion=Buy+%24100+of+BTC')}
                  className="text-xs px-3 py-1.5 btn-secondary rounded-md"
                >
                  Start your first trade
                </button>
              </div>
            )}
          </div>

          {/* Market movers */}
          <div className="lg:col-span-2 border theme-border rounded-lg overflow-hidden">
            <div className="flex items-center justify-between px-4 py-3 theme-elevated">
              <span className="section-header !mb-0">
                <span className="flex items-center gap-1.5">
                  <GlobeAltIcon className="w-3.5 h-3.5" />
                  Prediction Markets
                </span>
              </span>
              <Link href="/markets" className="text-xs text-[var(--color-link)] hover:underline">Browse</Link>
            </div>
            {markets.length > 0 ? (
              <div className="divide-y divide-[var(--color-border-subtle)]">
                {markets.map((m, i) => (
                  <button
                    key={i}
                    onClick={() => router.push(`/chat?suggestion=${encodeURIComponent(`What's the probability of: ${m.question}`)}`)}
                    className="w-full px-4 py-3 text-left hover:bg-[var(--color-fill-ghost-hover)] transition-colors"
                  >
                    <p className="text-xs theme-text leading-snug line-clamp-2 mb-1.5">
                      {m.question}
                    </p>
                    <div className="flex items-center gap-3">
                      <div className="flex-1">
                        <div className="prob-bar">
                          <div className="prob-bar-fill" style={{ width: `${(m.yes_price || 0) * 100}%` }} />
                        </div>
                      </div>
                      <span className="text-xs font-semibold tabular-nums" style={{ color: 'var(--color-probability)' }}>
                        {fmtProbability(m.yes_price)}
                      </span>
                      <span className="text-[10px] theme-text-muted tabular-nums">
                        {fmtCompact(m.volume)} vol
                      </span>
                    </div>
                  </button>
                ))}
              </div>
            ) : (
              <div className="px-4 py-10 text-center">
                <p className="text-sm theme-text-muted">Loading markets...</p>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
