'use client';

interface PredictionMarketCardProps {
  question: string;
  yesPrice: number;  // 0.0 to 1.0
  noPrice: number;
  volume: number;
  slug: string;
  onTrade?: (question: string) => void;
}

function formatVolume(v: number): string {
  if (v >= 1_000_000) return `$${(v / 1_000_000).toFixed(1)}M`;
  if (v >= 1_000) return `$${(v / 1_000).toFixed(1)}K`;
  return `$${v.toFixed(0)}`;
}

export default function PredictionMarketCard({ question, yesPrice, noPrice, volume, slug, onTrade }: PredictionMarketCardProps) {
  const yesPct = typeof yesPrice === 'number' && isFinite(yesPrice) ? (yesPrice * 100).toFixed(1) : '—';
  const noPct = typeof noPrice === 'number' && isFinite(noPrice) ? (noPrice * 100).toFixed(1) : '—';

  return (
    <div className="theme-surface border theme-border rounded-lg p-4 hover:shadow-md transition-shadow">
      <h3 className="font-semibold theme-text text-sm mb-3 line-clamp-2">{question}</h3>

      <div className="flex gap-3 mb-3">
        <div className="flex-1">
          <div className="text-xs theme-text-secondary mb-1">YES</div>
          <div className="flex items-center gap-2">
            <div className="flex-1 h-2 rounded-full bg-gray-200 dark:bg-slate-700 overflow-hidden">
              <div className="h-full rounded-full bg-emerald-500" style={{ width: `${yesPct}%` }} />
            </div>
            <span className="text-sm font-mono text-emerald-600 dark:text-emerald-400 w-14 text-right">{yesPct}%</span>
          </div>
        </div>
        <div className="flex-1">
          <div className="text-xs theme-text-secondary mb-1">NO</div>
          <div className="flex items-center gap-2">
            <div className="flex-1 h-2 rounded-full bg-gray-200 dark:bg-slate-700 overflow-hidden">
              <div className="h-full rounded-full bg-red-500" style={{ width: `${noPct}%` }} />
            </div>
            <span className="text-sm font-mono text-red-600 dark:text-red-400 w-14 text-right">{noPct}%</span>
          </div>
        </div>
      </div>

      <div className="flex items-center justify-between">
        <span className="text-xs theme-text-secondary">Vol: {formatVolume(volume)}</span>
        {onTrade && (
          <button
            onClick={() => onTrade(question)}
            className="px-3 py-1 text-xs btn-primary rounded"
          >
            Trade
          </button>
        )}
      </div>
    </div>
  );
}
