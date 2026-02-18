'use client';

/**
 * SelectionPanel - Displays asset selection results
 * 
 * Shows the selected asset, top candidates, and selection rationale
 * for "most profitable" or criteria-based asset selection queries.
 */

export interface SelectionCandidate {
  symbol: string;
  product_id: string;
  return_pct: number;
  first_price: number;
  last_price: number;
}

export interface SelectionData {
  selected_symbol: string;
  selected_return_pct: number;
  top_candidates: SelectionCandidate[];
  universe_description: string;
  window_description: string;
  why_explanation: string;
  fallback_used: boolean;
  lookback_hours: number;
  universe_size: number;
  evaluated_count: number;
  // Enterprise fields
  data_coverage_pct?: number;
  ranking_confidence?: number;
  exclusions_count?: number;
  exclusion_reasons?: string[];
  time_window?: {
    start_ts_utc: string;
    end_ts_utc: string;
    label: string;
    granularity: string;
    parse_confidence: number;
    parse_notes?: string;
  };
}

interface SelectionPanelProps {
  selection: SelectionData;
  className?: string;
}

function formatPrice(price: number): string {
  if (price >= 1000) {
    return `$${price.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  } else if (price >= 1) {
    return `$${price.toFixed(2)}`;
  } else if (price >= 0.01) {
    return `$${price.toFixed(4)}`;
  } else {
    return `$${price.toFixed(6)}`;
  }
}

function formatReturn(pct: number): { text: string; colorClass: string } {
  const isPositive = pct >= 0;
  const text = `${isPositive ? '+' : ''}${pct.toFixed(2)}%`;
  const colorClass = isPositive
    ? 'text-[var(--color-status-success)]'
    : 'text-[var(--color-status-error)]';
  return { text, colorClass };
}

export default function SelectionPanel({ selection, className = '' }: SelectionPanelProps) {
  const { text: returnText, colorClass: returnColor } = formatReturn(selection.selected_return_pct);
  
  return (
    <div className={`theme-bg border theme-border rounded-lg p-4 ${className}`}>
      {/* Header */}
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-medium theme-text-secondary">
          Asset Selection
        </h3>
        {selection.fallback_used && (
          <span className="text-xs px-2 py-0.5 bg-[var(--color-status-warning-bg)] text-[var(--color-status-warning)] rounded">
            Fallback
          </span>
        )}
      </div>

      {/* Selected Asset */}
      <div className="flex items-center gap-3 mb-4 p-3 theme-surface rounded-lg border theme-border">
        <div className="w-10 h-10 bg-neutral-200 dark:bg-neutral-700 rounded-full flex items-center justify-center">
          <span className="text-lg font-bold theme-text">
            {selection.selected_symbol.charAt(0)}
          </span>
        </div>
        <div className="flex-1">
          <div className="font-semibold theme-text">
            {selection.selected_symbol}
          </div>
          <div className="text-xs theme-text-muted">
            Selected from {selection.universe_description}
          </div>
        </div>
        <div className="text-right">
          <div className={`font-semibold ${returnColor}`}>
            {returnText}
          </div>
          <div className="text-xs theme-text-muted">
            {selection.window_description}
          </div>
        </div>
      </div>

      {/* Top Candidates Table */}
      {selection.top_candidates.length > 0 && (
        <div className="mb-4">
          <div className="text-xs font-medium theme-text-secondary mb-2">
            Top Candidates ({selection.evaluated_count} evaluated)
          </div>
          <div className="space-y-1">
            {selection.top_candidates.map((candidate, idx) => {
              const { text: candReturn, colorClass: candColor } = formatReturn(candidate.return_pct);
              const isSelected = candidate.symbol === selection.selected_symbol;
              
              return (
                <div 
                  key={candidate.product_id}
                  className={`flex items-center justify-between px-2 py-1.5 rounded text-sm ${
                    isSelected
                      ? 'theme-elevated border theme-border-strong'
                      : 'theme-elevated'
                  }`}
                >
                  <div className="flex items-center gap-2">
                    <span className="w-5 theme-text-muted text-xs">{idx + 1}.</span>
                    <span className={`font-medium ${isSelected ? 'theme-text' : 'theme-text-secondary'}`}>
                      {candidate.symbol}
                    </span>
                  </div>
                  <div className="flex items-center gap-4">
                    <span className="text-xs theme-text-muted">
                      {formatPrice(candidate.first_price)} → {formatPrice(candidate.last_price)}
                    </span>
                    <span className={`font-medium ${candColor}`}>
                      {candReturn}
                    </span>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Explanation */}
      <div className="text-xs theme-text-secondary leading-relaxed">
        {selection.why_explanation}
      </div>

      {/* Stats Footer */}
      <div className="mt-3 pt-3 border-t theme-border flex flex-wrap gap-x-4 gap-y-1 text-xs theme-text-muted">
        <span>Universe: {selection.universe_size} assets</span>
        <span>Window: {selection.time_window?.label || (
          selection.lookback_hours < 1 
            ? `${Math.round(selection.lookback_hours * 60)}m` 
            : selection.lookback_hours >= 24 
              ? `${Math.round(selection.lookback_hours / 24)}d`
              : `${selection.lookback_hours}h`
        )}</span>
        {typeof selection.data_coverage_pct === 'number' && (
          <span>Coverage: {selection.data_coverage_pct.toFixed(0)}%</span>
        )}
        {typeof selection.ranking_confidence === 'number' && (
          <span>Confidence: {(selection.ranking_confidence * 100).toFixed(0)}%</span>
        )}
      </div>
      
      {/* Parse notes (if timeframe was defaulted) */}
      {selection.time_window?.parse_notes && (
        <div className="mt-2 text-xs text-[var(--color-status-warning)]">
          Note: {selection.time_window.parse_notes}
        </div>
      )}
    </div>
  );
}
