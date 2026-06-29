'use client';

interface ClientHealthGaugeProps {
  score: number;
  classification: string;
  size?: number;
}

const CLASSIFICATION_COLORS: Record<string, string> = {
  healthy: 'var(--color-status-success)',
  good: 'var(--chart-2)',
  at_risk: 'var(--color-status-warning)',
  churning: 'var(--color-status-error)',
  inactive: 'var(--chart-3)',
};

export default function ClientHealthGauge({ score, classification, size = 120 }: ClientHealthGaugeProps) {
  const radius = (size - 16) / 2;
  const circumference = 2 * Math.PI * radius;
  const pct = Math.min(100, Math.max(0, score));
  const offset = circumference - (pct / 100) * circumference;
  const color = CLASSIFICATION_COLORS[classification] || 'var(--chart-3)';

  return (
    <div className="flex flex-col items-center gap-2">
      <svg width={size} height={size} className="transform -rotate-90">
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke="var(--color-fill-ghost-hover)"
          strokeWidth={8}
        />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke={color}
          strokeWidth={8}
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          strokeLinecap="round"
          className="transition-all duration-700"
        />
      </svg>
      <div className="absolute flex flex-col items-center justify-center" style={{ width: size, height: size }}>
        <span className="text-2xl font-bold theme-text">
          {typeof score === 'number' && isFinite(score) ? Math.round(score) : '—'}
        </span>
        <span className="text-xs theme-text-secondary capitalize">{classification}</span>
      </div>
    </div>
  );
}
