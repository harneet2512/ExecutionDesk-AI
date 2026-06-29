'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { apiFetchSafe, listRuns, Run } from '@/lib/api';
import { fmtCurrency, fmtTimeAgo, fmtCompact, gainLossClass } from '@/lib/format';
import { getStatusClasses, getStatusLabel } from '@/lib/statusColors';
import PageSkeleton from '@/components/PageSkeleton';

interface Position {
  symbol: string;
  side: string;
  notional_usd: number;
  created_at: string;
  run_id: string;
  order_id: string;
  status: string;
}

interface PortfolioSnapshot {
  total_value_usd: number;
  ts: string;
  holdings?: Record<string, number>;
}

export default function PositionsPage() {
  const [positions, setPositions] = useState<Position[]>([]);
  const [snapshot, setSnapshot] = useState<PortfolioSnapshot | null>(null);
  const [runs, setRuns] = useState<Run[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    loadData();
  }, []);

  async function loadData() {
    try {
      const [perf, runsData] = await Promise.allSettled([
        apiFetchSafe('/api/v1/analytics/performance?window=30d'),
        listRuns(),
      ]);

      if (perf.status === 'fulfilled' && perf.value) {
        const trades = perf.value.trades || [];
        setPositions(trades.map((t: any) => ({
          symbol: t.symbol,
          side: t.side,
          notional_usd: t.notional_usd,
          created_at: t.created_at,
          run_id: t.run_id,
          order_id: t.order_id,
          status: 'FILLED',
        })));

        if (perf.value.summary) {
          setSnapshot({
            total_value_usd: perf.value.summary.total_pnl || 0,
            ts: new Date().toISOString(),
          });
        }
      }

      if (runsData.status === 'fulfilled' && Array.isArray(runsData.value)) {
        setRuns(runsData.value.filter((r: Run) => r.status === 'COMPLETED'));
      }
    } catch {} finally {
      setLoading(false);
    }
  }

  const symbols = Array.from(new Set(positions.map(p => p.symbol)));
  const symbolSummary = symbols.map(sym => {
    const trades = positions.filter(p => p.symbol === sym);
    const buys = trades.filter(t => t.side?.toUpperCase() === 'BUY');
    const sells = trades.filter(t => t.side?.toUpperCase() === 'SELL');
    const buyTotal = buys.reduce((s, t) => s + (t.notional_usd || 0), 0);
    const sellTotal = sells.reduce((s, t) => s + (t.notional_usd || 0), 0);
    return {
      symbol: sym,
      trades: trades.length,
      buyTotal,
      sellTotal,
      net: buyTotal - sellTotal,
      lastTrade: trades[0]?.created_at,
    };
  });

  if (loading) return <PageSkeleton title="Positions" />;

  return (
    <div className="flex-1 overflow-y-auto p-6 lg:p-8 max-w-7xl mx-auto page-enter">
      {/* Header */}
      <div className="flex items-baseline justify-between mb-6">
        <div>
          <h1 className="text-xl font-semibold theme-text">Positions</h1>
          <p className="text-sm theme-text-muted mt-0.5">
            {positions.length} trades across {symbols.length} assets
          </p>
        </div>
      </div>

      {/* Portfolio summary */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-6 stagger-enter">
        <div className="metric-card">
          <div className="metric-label">Net P&L</div>
          <div className={`metric-value tabular-nums ${gainLossClass(snapshot?.total_value_usd)}`}>
            {fmtCurrency(snapshot?.total_value_usd)}
          </div>
        </div>
        <div className="metric-card">
          <div className="metric-label">Total Trades</div>
          <div className="metric-value tabular-nums">{positions.length}</div>
        </div>
        <div className="metric-card">
          <div className="metric-label">Assets</div>
          <div className="metric-value tabular-nums">{symbols.length}</div>
        </div>
        <div className="metric-card">
          <div className="metric-label">Completed Runs</div>
          <div className="metric-value tabular-nums">{runs.length}</div>
        </div>
      </div>

      {/* Position summary by symbol */}
      {symbolSummary.length > 0 && (
        <div className="mb-6">
          <div className="section-header">By Asset</div>
          <div className="grid grid-cols-2 lg:grid-cols-3 gap-3">
            {symbolSummary.map(s => (
              <div key={s.symbol} className="metric-card !p-4">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-sm font-semibold theme-text">{s.symbol}</span>
                  <span className="text-[10px] theme-text-muted">{s.trades} trades</span>
                </div>
                <div className="grid grid-cols-2 gap-2 text-xs">
                  <div>
                    <span className="theme-text-muted">Bought</span>
                    <div className="font-semibold tabular-nums gain">{fmtCurrency(s.buyTotal)}</div>
                  </div>
                  <div>
                    <span className="theme-text-muted">Sold</span>
                    <div className="font-semibold tabular-nums loss">{fmtCurrency(s.sellTotal)}</div>
                  </div>
                </div>
                <div className="mt-2 pt-2 border-t" style={{ borderColor: 'var(--color-border-subtle)' }}>
                  <span className="text-[10px] theme-text-muted">Net exposure</span>
                  <div className={`text-sm font-semibold tabular-nums ${gainLossClass(s.net)}`}>
                    {fmtCurrency(s.net)}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Trade history */}
      <div className="border theme-border rounded-lg overflow-hidden">
        <div className="px-4 py-3 theme-elevated">
          <span className="section-header !mb-0">Trade History</span>
        </div>
        {positions.length === 0 ? (
          <div className="px-4 py-10 text-center theme-text-muted text-sm">
            No trades yet. Execute a trade from the chat to see positions here.
          </div>
        ) : (
          <table className="data-table">
            <thead>
              <tr>
                <th>Symbol</th>
                <th>Side</th>
                <th className="num">Notional</th>
                <th>Run</th>
                <th>Time</th>
              </tr>
            </thead>
            <tbody>
              {positions.map((p, i) => (
                <tr key={i}>
                  <td className="font-medium">{p.symbol}</td>
                  <td>
                    <span className={p.side?.toUpperCase() === 'BUY' ? 'gain' : 'loss'}>
                      {(p.side || '').toUpperCase()}
                    </span>
                  </td>
                  <td className="num tabular-nums">{fmtCurrency(p.notional_usd)}</td>
                  <td>
                    <Link href={`/runs/${p.run_id}`} className="font-mono text-xs text-[var(--color-link)] hover:underline">
                      {(p.run_id || '').slice(0, 10)}
                    </Link>
                  </td>
                  <td className="tabular-nums theme-text-muted text-xs">{fmtTimeAgo(p.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
