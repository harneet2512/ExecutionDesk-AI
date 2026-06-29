const NUM_SAFE = (v: unknown): v is number =>
  typeof v === 'number' && isFinite(v);

export function fmtCurrency(v: unknown, decimals = 2): string {
  if (!NUM_SAFE(v)) return '—';
  const abs = Math.abs(v);
  const sign = v < 0 ? '-' : '';
  if (abs >= 1_000_000) return `${sign}$${(abs / 1_000_000).toFixed(1)}M`;
  if (abs >= 10_000) return `${sign}$${(abs / 1_000).toFixed(1)}K`;
  return `${sign}$${abs.toLocaleString(undefined, { minimumFractionDigits: decimals, maximumFractionDigits: decimals })}`;
}

export function fmtNumber(v: unknown, decimals = 0): string {
  if (!NUM_SAFE(v)) return '—';
  return v.toLocaleString(undefined, { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
}

export function fmtPercent(v: unknown, decimals = 1): string {
  if (!NUM_SAFE(v)) return '—';
  const sign = v > 0 ? '+' : '';
  return `${sign}${v.toFixed(decimals)}%`;
}

export function fmtProbability(v: unknown): string {
  if (!NUM_SAFE(v)) return '—';
  const pct = v <= 1 ? v * 100 : v;
  return `${pct.toFixed(0)}%`;
}

export function fmtCompact(v: unknown): string {
  if (!NUM_SAFE(v)) return '—';
  const abs = Math.abs(v);
  if (abs >= 1_000_000_000) return `${(v / 1_000_000_000).toFixed(1)}B`;
  if (abs >= 1_000_000) return `${(v / 1_000_000).toFixed(1)}M`;
  if (abs >= 1_000) return `${(v / 1_000).toFixed(1)}K`;
  return String(Math.round(v));
}

export function fmtTimeAgo(dateStr: string | null | undefined): string {
  if (!dateStr) return '—';
  const d = new Date(dateStr);
  if (isNaN(d.getTime())) return '—';
  const secs = Math.floor((Date.now() - d.getTime()) / 1000);
  if (secs < 60) return 'just now';
  const mins = Math.floor(secs / 60);
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  if (days < 30) return `${days}d ago`;
  return d.toLocaleDateString();
}

export function fmtDate(dateStr: string | null | undefined): string {
  if (!dateStr) return '—';
  const d = new Date(dateStr);
  if (isNaN(d.getTime())) return '—';
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}

export function fmtDateTime(dateStr: string | null | undefined): string {
  if (!dateStr) return '—';
  const d = new Date(dateStr);
  if (isNaN(d.getTime())) return '—';
  return d.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}

export function gainLossClass(v: unknown): string {
  if (!NUM_SAFE(v)) return '';
  return v >= 0 ? 'gain' : 'loss';
}

export function gainLossBg(v: unknown): string {
  if (!NUM_SAFE(v) || v === 0) return '';
  return v > 0
    ? 'bg-[var(--color-gain-bg)]'
    : 'bg-[var(--color-loss-bg)]';
}
