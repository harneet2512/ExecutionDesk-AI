'use client';

import { useEffect, useState, useCallback } from 'react';
import Link from 'next/link';
import PageSkeleton from '@/components/PageSkeleton';

interface Runbook {
  runbook_id: string;
  title: string;
  slug: string;
  category: string;
  error_codes: string[];
  symptoms: string;
  severity: string;
  times_used: number;
  last_used_at: string | null;
  updated_at: string;
}

const SEVERITY_STYLES: Record<string, string> = {
  critical: 'bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-300',
  high: 'bg-orange-100 text-orange-800 dark:bg-orange-900/30 dark:text-orange-300',
  medium: 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900/30 dark:text-yellow-300',
  low: 'bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-300',
};

export default function RunbooksPage() {
  const [runbooks, setRunbooks] = useState<Runbook[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [categoryFilter, setCategoryFilter] = useState('');
  const [categories, setCategories] = useState<string[]>([]);

  const loadRunbooks = useCallback(async () => {
    try {
      const params = new URLSearchParams();
      if (search) params.set('q', search);
      if (categoryFilter) params.set('category', categoryFilter);
      const qs = params.toString();
      const url = `/api/v1/runbooks${qs ? '?' + qs : ''}`;
      const res = await fetch(url, {
        headers: { 'X-Dev-Tenant': 't_default' },
      });
      if (!res.ok) throw new Error('Failed to load runbooks');
      const data = await res.json();
      setRunbooks(data.runbooks || []);

      // Extract unique categories from full list (only on initial load)
      if (!categoryFilter && !search) {
        const cats = Array.from(new Set((data.runbooks || []).map((r: Runbook) => r.category))) as string[];
        setCategories(cats.sort());
      }
    } catch (error) {
      if (process.env.NODE_ENV === 'development') console.error('Failed to load runbooks:', error);
    } finally {
      setLoading(false);
    }
  }, [search, categoryFilter]);

  useEffect(() => {
    const timer = setTimeout(() => {
      loadRunbooks();
    }, 300); // debounce search
    return () => clearTimeout(timer);
  }, [loadRunbooks]);

  if (loading) return <PageSkeleton title="Runbooks" />;

  return (
    <div className="p-6 lg:p-8 max-w-7xl mx-auto page-enter">
      <div className="flex items-baseline justify-between mb-6">
        <h1 className="text-xl font-semibold theme-text">Runbooks</h1>
        <span className="text-sm theme-text-secondary">
          {runbooks.length} runbook{runbooks.length !== 1 ? 's' : ''}
        </span>
      </div>

      {/* Search and filter bar */}
      <div className="flex gap-4 mb-6">
        <input
          type="text"
          placeholder="Search runbooks..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="flex-1 px-4 py-2 rounded-lg border theme-elevated theme-text focus:outline-none focus:ring-2 focus:ring-blue-500"
        />
        <select
          value={categoryFilter}
          onChange={(e) => setCategoryFilter(e.target.value)}
          className="px-4 py-2 rounded-lg border theme-elevated theme-text focus:outline-none focus:ring-2 focus:ring-blue-500"
        >
          <option value="">All Categories</option>
          {categories.map((cat) => (
            <option key={cat} value={cat}>
              {cat}
            </option>
          ))}
        </select>
      </div>

      {/* Runbooks list */}
      {runbooks.length === 0 ? (
        <div className="text-center py-12 theme-text-secondary">
          <p className="text-lg">No runbooks found</p>
          <p className="text-sm mt-2">
            {search || categoryFilter
              ? 'Try adjusting your search or filter.'
              : 'No runbooks have been created yet.'}
          </p>
        </div>
      ) : (
        <div className="space-y-3">
          {runbooks.map((rb) => (
            <Link
              key={rb.slug}
              href={`/ops/runbooks/${rb.slug}`}
              className="block p-4 rounded-lg border theme-elevated hover:shadow-md transition-shadow"
            >
              <div className="flex items-start justify-between">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-1">
                    <h3 className="font-semibold theme-text truncate">{rb.title}</h3>
                    <span
                      className={`text-xs px-2 py-0.5 rounded-full font-medium ${
                        SEVERITY_STYLES[rb.severity] || SEVERITY_STYLES.medium
                      }`}
                    >
                      {rb.severity}
                    </span>
                  </div>
                  <p className="text-sm theme-text-secondary truncate">{rb.symptoms}</p>
                  <div className="flex items-center gap-3 mt-2">
                    <span className="text-xs theme-text-secondary px-2 py-0.5 rounded theme-elevated">
                      {rb.category}
                    </span>
                    {rb.error_codes.length > 0 && (
                      <span className="text-xs theme-text-secondary">
                        {rb.error_codes.length} error code{rb.error_codes.length !== 1 ? 's' : ''}
                      </span>
                    )}
                    <span className="text-xs theme-text-secondary">
                      Used {rb.times_used} time{rb.times_used !== 1 ? 's' : ''}
                    </span>
                  </div>
                </div>
              </div>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
