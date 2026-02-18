'use client';

import { useState } from 'react';
import type { EvalDetail } from '@/lib/api';

function safeStr(v: unknown): string {
  if (typeof v === 'string') return v;
  if (typeof v === 'number' && isFinite(v)) return String(v);
  if (v != null && typeof v === 'object') return JSON.stringify(v);
  return '';
}

function fmtPct(v: unknown): string {
  return typeof v === 'number' && isFinite(v) ? `${(v * 100).toFixed(1)}%` : '\u2014';
}

function ScoreBar({ score, threshold, height = 8 }: { score: number; threshold?: number; height?: number }) {
  const pct = Math.max(0, Math.min(100, score * 100));
  const color = score >= 0.9 ? '#525252' : score >= 0.7 ? '#737373' : score >= 0.5 ? '#a3a3a3' : '#d4d4d4';
  const threshPct = typeof threshold === 'number' && isFinite(threshold) ? threshold * 100 : null;

  return (
    <div className="relative w-full theme-elevated rounded-full" style={{ height }}>
      <div
        className="rounded-full transition-all"
        style={{ width: `${pct}%`, height, backgroundColor: color }}
      />
      {threshPct !== null && (
        <div
          className="absolute top-0 w-0.5 bg-neutral-900 dark:bg-white opacity-50"
          style={{ left: `${threshPct}%`, height: height + 4, top: -2 }}
          title={`Threshold: ${threshPct.toFixed(0)}%`}
        />
      )}
    </div>
  );
}

function PassBadge({ pass: isPass }: { pass: boolean }) {
  return (
    <span
      className={`text-xs font-semibold px-2 py-0.5 rounded ${
        isPass
          ? 'bg-[var(--color-status-success-bg)] text-[var(--color-status-success)]'
          : 'bg-[var(--color-status-error-bg)] text-[var(--color-status-error)]'
      }`}
    >
      {isPass ? 'PASS' : 'FAIL'}
    </span>
  );
}

function formatDetailValue(value: unknown): string {
  if (value === null || value === undefined) return '\u2014';
  if (typeof value === 'string') return value;
  if (typeof value === 'number') return isFinite(value) ? String(value) : '\u2014';
  if (typeof value === 'boolean') return value ? 'Yes' : 'No';
  return JSON.stringify(value);
}

interface EvalExplainabilityProps {
  eval: EvalDetail;
}

export default function EvalExplainability({ eval: ev }: EvalExplainabilityProps) {
  const [showRubric, setShowRubric] = useState(false);
  const defn = ev.definition;
  const score = typeof ev.score === 'number' && isFinite(ev.score) ? ev.score : 0;
  const isPass = ev.pass ?? score >= 0.5;
  const threshold = defn?.threshold;

  return (
    <div className="ml-6 mt-2 pl-4 border-l-2 theme-border space-y-3">
      {/* Score bar with threshold marker */}
      <div className="flex items-center gap-2">
        <div className="flex-1">
          <ScoreBar score={score} threshold={threshold} height={6} />
        </div>
        <span className="text-xs font-mono theme-text-secondary w-14 text-right">
          {fmtPct(score)}
        </span>
        <PassBadge pass={isPass} />
      </div>

      {/* What this checks */}
      {defn?.description && (
        <div>
          <p className="text-xs font-medium theme-text-secondary mb-0.5">What this checks</p>
          <p className="text-xs theme-text">{safeStr(defn.description)}</p>
        </div>
      )}

      {/* How it's computed (collapsible) */}
      {defn?.rubric && (
        <div>
          <button
            onClick={() => setShowRubric(!showRubric)}
            className="text-xs font-medium theme-text-secondary hover:opacity-80 flex items-center gap-1"
          >
            <span>{showRubric ? '\u25BC' : '\u25B6'}</span>
            How it&apos;s computed
          </button>
          {showRubric && (
            <p className="text-xs theme-text-secondary mt-1 pl-3 border-l theme-border">
              {safeStr(defn.rubric)}
            </p>
          )}
        </div>
      )}

      {/* Stored explanation (from POST explain) */}
      {ev.explanation && safeStr(ev.explanation).trim() && (
        <div>
          <p className="text-xs font-medium theme-text-secondary mb-1 flex items-center gap-2">
            Explainability
            {ev.explanation_source && (
              <span
                className={`px-1.5 py-0.5 rounded text-[10px] ${
                  ev.explanation_source === 'llm'
                    ? 'bg-[var(--color-status-info-bg)] text-[var(--color-status-info)]'
                    : 'theme-elevated theme-text-secondary'
                }`}
              >
                {ev.explanation_source === 'llm' ? 'LLM-generated' : 'Rule-based'}
              </span>
            )}
          </p>
          <p className="text-xs theme-text">{safeStr(ev.explanation)}</p>
        </div>
      )}

      {/* Why this score (reasons) */}
      {Array.isArray(ev.reasons) && ev.reasons.length > 0 && (
        <div>
          <p className="text-xs font-medium theme-text-secondary mb-1">Why this score</p>
          <ul className="text-xs theme-text-secondary space-y-0.5 list-disc list-inside">
            {ev.reasons.map((r: unknown, ri: number) => (
              <li key={ri}>{safeStr(r)}</li>
            ))}
          </ul>
        </div>
      )}

      {/* How to improve (only for failures) */}
      {!isPass && defn?.how_to_improve && defn.how_to_improve.length > 0 && (
        <div className="bg-[var(--color-status-warning-bg)] border border-[var(--color-status-warning)]/30 rounded-lg p-2">
          <p className="text-xs font-medium text-[var(--color-status-warning)] mb-1">How to improve</p>
          <ul className="text-xs text-[var(--color-status-warning)] space-y-0.5 list-disc list-inside">
            {defn.how_to_improve.map((tip: string, i: number) => (
              <li key={i}>{safeStr(tip)}</li>
            ))}
          </ul>
        </div>
      )}

      {/* Evidence (details) */}
      {ev.details != null && typeof ev.details === 'object' && Object.keys(ev.details).length > 0 && (
        <div>
          <p className="text-xs font-medium theme-text-secondary mb-1">Evidence</p>
          <div className="text-xs theme-text-secondary theme-sunken rounded p-2 space-y-1 max-h-48 overflow-y-auto">
            {Object.entries(ev.details).map(([key, value]) => {
              const isComplex = value !== null && typeof value === 'object';
              return (
                <div key={key}>
                  <span className="font-medium theme-text">
                    {key.replace(/_/g, ' ')}:
                  </span>{' '}
                  {isComplex ? (
                    <pre className="inline-block ml-2 overflow-x-auto text-xs">
                      {JSON.stringify(value, null, 2)}
                    </pre>
                  ) : (
                    <span>{formatDetailValue(value)}</span>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Evaluator type badge */}
      {ev.evaluator_type && ev.evaluator_type !== 'default' && (
        <div className="flex items-center gap-2">
          <span className="text-xs px-1.5 py-0.5 theme-elevated theme-text-secondary rounded">
            {safeStr(ev.evaluator_type)}
          </span>
          {threshold != null && (
            <span className="text-xs theme-text-muted">
              threshold: {fmtPct(threshold)}
            </span>
          )}
        </div>
      )}
    </div>
  );
}
