'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';

interface SuggestedRunbook {
  runbook_id: string;
  title: string;
  slug: string;
  severity: string;
  symptoms: string;
}

interface RunbookSuggestionProps {
  errorCode: string;
}

const SEVERITY_STYLES: Record<string, string> = {
  critical: 'border-red-500 bg-red-50 dark:bg-red-900/10',
  high: 'border-orange-500 bg-orange-50 dark:bg-orange-900/10',
  medium: 'border-yellow-500 bg-yellow-50 dark:bg-yellow-900/10',
  low: 'border-green-500 bg-green-50 dark:bg-green-900/10',
};

/**
 * Inline component that fetches and displays runbook suggestions for a given error code.
 * Renders nothing if no matching runbooks are found.
 */
export default function RunbookSuggestion({ errorCode }: RunbookSuggestionProps) {
  const [suggestions, setSuggestions] = useState<SuggestedRunbook[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!errorCode) {
      setLoading(false);
      return;
    }

    let cancelled = false;
    async function fetchSuggestions() {
      try {
        const res = await fetch(
          `/api/v1/runbooks/suggest?error_code=${encodeURIComponent(errorCode)}`,
          { headers: { 'X-Dev-Tenant': 't_default' } }
        );
        if (!res.ok) return;
        const data = await res.json();
        if (!cancelled) {
          setSuggestions(data.suggestions || []);
        }
      } catch {
        // Silently fail - suggestions are non-critical
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    fetchSuggestions();
    return () => {
      cancelled = true;
    };
  }, [errorCode]);

  if (loading || suggestions.length === 0) return null;

  return (
    <div className="mt-3">
      {suggestions.map((rb) => (
        <Link
          key={rb.slug}
          href={`/ops/runbooks/${rb.slug}`}
          className={`block p-3 rounded-lg border-l-4 ${
            SEVERITY_STYLES[rb.severity] || SEVERITY_STYLES.medium
          } hover:shadow-sm transition-shadow mb-2`}
        >
          <div className="flex items-center gap-2">
            <span className="text-sm font-medium theme-text">Runbook: {rb.title}</span>
          </div>
          <p className="text-xs theme-text-secondary mt-1 truncate">{rb.symptoms}</p>
        </Link>
      ))}
    </div>
  );
}
