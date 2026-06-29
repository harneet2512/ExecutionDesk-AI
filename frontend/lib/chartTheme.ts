export const CHART_COLORS = {
  primary: 'var(--chart-1)',
  positive: 'var(--chart-2)',
  secondary: 'var(--chart-3)',
  tertiary: 'var(--chart-4)',
  comparison: 'var(--chart-5)',
  accent: 'var(--chart-accent)',
  grid: 'var(--chart-grid)',
  gain: 'var(--color-gain)',
  loss: 'var(--color-loss)',
  probability: 'var(--color-probability)',
} as const;

export const AXIS_STYLE = {
  fontSize: 11,
  fill: 'var(--color-text-muted)',
  fontFamily: 'inherit',
} as const;

export const GRID_STYLE = {
  strokeDasharray: '3 3',
  stroke: 'var(--chart-grid)',
} as const;

export const TOOLTIP_STYLE = {
  contentStyle: {
    backgroundColor: 'var(--chart-tooltip-bg)',
    border: '1px solid var(--chart-tooltip-border)',
    borderRadius: '0.5rem',
    fontSize: '0.8125rem',
    color: 'var(--chart-tooltip-text)',
    boxShadow: '0 4px 12px rgba(0,0,0,0.1)',
    padding: '0.5rem 0.75rem',
  },
  itemStyle: {
    color: 'var(--chart-tooltip-text)',
    fontSize: '0.75rem',
    padding: '0.125rem 0',
  },
  labelStyle: {
    color: 'var(--color-text-muted)',
    fontSize: '0.6875rem',
    fontWeight: 600,
    marginBottom: '0.25rem',
  },
} as const;

export const AREA_GRADIENT_ID = 'chartAreaGradient';
