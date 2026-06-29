'use client';

import { useEffect, useState, useCallback } from 'react';
import { useParams, useRouter } from 'next/navigation';
import Link from 'next/link';
import PageSkeleton from '@/components/PageSkeleton';

interface RunbookDetail {
  runbook_id: string;
  title: string;
  slug: string;
  category: string;
  error_codes: string[];
  symptoms: string;
  diagnosis_steps: string;
  resolution: string;
  prevention: string;
  severity: string;
  times_used: number;
  last_used_at: string | null;
  created_by: string | null;
  created_at: string;
  updated_at: string;
}

const SEVERITY_STYLES: Record<string, string> = {
  critical: 'bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-300',
  high: 'bg-orange-100 text-orange-800 dark:bg-orange-900/30 dark:text-orange-300',
  medium: 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900/30 dark:text-yellow-300',
  low: 'bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-300',
};

function ChecklistSection({ title, content }: { title: string; content: string }) {
  const lines = content.split('\n').filter((l) => l.trim());
  const [checked, setChecked] = useState<boolean[]>(new Array(lines.length).fill(false));

  const toggle = (index: number) => {
    setChecked((prev) => {
      const next = [...prev];
      next[index] = !next[index];
      return next;
    });
  };

  const completedCount = checked.filter(Boolean).length;

  return (
    <div className="mb-6">
      <div className="flex items-center justify-between mb-2">
        <h3 className="text-lg font-semibold theme-text">{title}</h3>
        {lines.length > 0 && (
          <span className="text-xs theme-text-secondary">
            {completedCount}/{lines.length} completed
          </span>
        )}
      </div>
      <div className="space-y-1">
        {lines.map((line, i) => {
          // Strip leading bullet/number markers
          const cleanLine = line.replace(/^[-*]\s*/, '').replace(/^\d+\.\s*/, '');
          return (
            <label
              key={i}
              className="flex items-start gap-3 p-2 rounded cursor-pointer hover:bg-black/5 dark:hover:bg-white/5 transition-colors"
            >
              <input
                type="checkbox"
                checked={checked[i]}
                onChange={() => toggle(i)}
                className="mt-1 h-4 w-4 rounded border-gray-300"
              />
              <span
                className={`text-sm ${
                  checked[i]
                    ? 'line-through theme-text-secondary'
                    : 'theme-text'
                }`}
              >
                {cleanLine}
              </span>
            </label>
          );
        })}
      </div>
    </div>
  );
}

export default function RunbookDetailPage() {
  const params = useParams();
  const router = useRouter();
  const slug = params?.slug as string;

  const [runbook, setRunbook] = useState<RunbookDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [markingUsed, setMarkingUsed] = useState(false);

  const loadRunbook = useCallback(async () => {
    if (!slug) return;
    try {
      const res = await fetch(`/api/v1/runbooks/${slug}`, {
        headers: { 'X-Dev-Tenant': 't_default' },
      });
      if (res.status === 404) {
        setError('Runbook not found');
        return;
      }
      if (!res.ok) throw new Error('Failed to load runbook');
      const data = await res.json();
      setRunbook(data);
    } catch (err) {
      setError('Failed to load runbook');
      if (process.env.NODE_ENV === 'development') console.error(err);
    } finally {
      setLoading(false);
    }
  }, [slug]);

  useEffect(() => {
    loadRunbook();
  }, [loadRunbook]);

  const markUsed = async () => {
    if (!slug || markingUsed) return;
    setMarkingUsed(true);
    try {
      const res = await fetch(`/api/v1/runbooks/${slug}/use`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Dev-Tenant': 't_default',
        },
        body: JSON.stringify({ outcome: 'used', notes: '' }),
      });
      if (res.ok) {
        // Reload to get updated times_used
        await loadRunbook();
      }
    } catch (err) {
      if (process.env.NODE_ENV === 'development') console.error('Failed to mark used:', err);
    } finally {
      setMarkingUsed(false);
    }
  };

  if (loading) return <PageSkeleton title="Runbook" />;

  if (error || !runbook) {
    return (
      <div className="p-8 max-w-4xl mx-auto">
        <Link href="/ops/runbooks" className="text-sm text-blue-500 hover:underline mb-4 inline-block">
          Back to Runbooks
        </Link>
        <div className="text-center py-12">
          <p className="text-lg theme-text-secondary">{error || 'Runbook not found'}</p>
        </div>
      </div>
    );
  }

  return (
    <div className="p-8 max-w-4xl mx-auto">
      <Link href="/ops/runbooks" className="text-sm text-blue-500 hover:underline mb-4 inline-block">
        Back to Runbooks
      </Link>

      {/* Header */}
      <div className="flex items-start justify-between mb-6">
        <div>
          <h1 className="text-xl font-semibold theme-text mb-2">{runbook.title}</h1>
          <div className="flex items-center gap-3">
            <span
              className={`text-xs px-2 py-0.5 rounded-full font-medium ${
                SEVERITY_STYLES[runbook.severity] || SEVERITY_STYLES.medium
              }`}
            >
              {runbook.severity}
            </span>
            <span className="text-xs theme-text-secondary px-2 py-0.5 rounded theme-elevated">
              {runbook.category}
            </span>
            <span className="text-xs theme-text-secondary">
              Used {runbook.times_used} time{runbook.times_used !== 1 ? 's' : ''}
            </span>
          </div>
        </div>
        <button
          onClick={markUsed}
          disabled={markingUsed}
          className="px-4 py-2 text-sm rounded-lg bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50 transition-colors"
        >
          {markingUsed ? 'Recording...' : 'Mark as Used'}
        </button>
      </div>

      {/* Error codes */}
      {runbook.error_codes.length > 0 && (
        <div className="mb-6">
          <h3 className="text-sm font-medium theme-text-secondary mb-2">Error Codes</h3>
          <div className="flex flex-wrap gap-2">
            {runbook.error_codes.map((code) => (
              <code
                key={code}
                className="text-xs px-2 py-1 rounded theme-elevated font-mono"
              >
                {code}
              </code>
            ))}
          </div>
        </div>
      )}

      {/* Symptoms */}
      <div className="mb-6 p-4 rounded-lg border theme-elevated">
        <h3 className="text-lg font-semibold theme-text mb-2">Symptoms</h3>
        <p className="text-sm theme-text-secondary whitespace-pre-wrap">{runbook.symptoms}</p>
      </div>

      {/* Diagnosis steps (interactive checklist) */}
      <div className="p-4 rounded-lg border theme-elevated">
        <ChecklistSection title="Diagnosis Steps" content={runbook.diagnosis_steps} />
      </div>

      {/* Resolution */}
      <div className="mt-4 p-4 rounded-lg border theme-elevated">
        <ChecklistSection title="Resolution" content={runbook.resolution} />
      </div>

      {/* Prevention */}
      <div className="mt-4 p-4 rounded-lg border theme-elevated">
        <h3 className="text-lg font-semibold theme-text mb-2">Prevention</h3>
        <p className="text-sm theme-text-secondary whitespace-pre-wrap">{runbook.prevention}</p>
      </div>

      {/* Metadata */}
      <div className="mt-6 text-xs theme-text-secondary flex gap-6">
        {runbook.created_by && <span>Created by: {runbook.created_by}</span>}
        <span>Created: {new Date(runbook.created_at).toLocaleDateString()}</span>
        <span>Updated: {new Date(runbook.updated_at).toLocaleDateString()}</span>
        {runbook.last_used_at && (
          <span>Last used: {new Date(runbook.last_used_at).toLocaleDateString()}</span>
        )}
      </div>
    </div>
  );
}
