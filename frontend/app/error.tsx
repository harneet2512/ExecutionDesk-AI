'use client';

import { useEffect } from 'react';
import { useRouter } from 'next/navigation';

/**
 * Route-level error boundary.
 * Catches ChunkLoadError (common with OneDrive-synced workspaces) and
 * offers auto-retry via router.refresh(), or a manual reload fallback.
 */
export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  const router = useRouter();
  const isChunkError =
    error.message?.includes('ChunkLoadError') ||
    error.message?.includes('Loading chunk') ||
    error.message?.includes('Failed to fetch dynamically imported module');

  useEffect(() => {
    console.error('[ErrorBoundary]', error);

    // Auto-retry once for chunk load errors (stale .next artifacts)
    if (isChunkError) {
      const retried = sessionStorage.getItem('chunk_error_retried');
      if (!retried) {
        sessionStorage.setItem('chunk_error_retried', '1');
        router.refresh();
        return;
      }
    }
  }, [error, isChunkError, router]);

  return (
    <div className="flex-1 flex items-center justify-center min-h-[60vh]">
      <div className="text-center max-w-md mx-auto p-6">
        <div className="w-16 h-16 mx-auto mb-4 rounded-full bg-[var(--color-status-error-bg)] flex items-center justify-center">
          <svg className="w-8 h-8 text-[var(--color-status-error)]" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4c-.77-.833-1.964-.833-2.732 0L4.082 16.5c-.77.833.192 2.5 1.732 2.5z" />
          </svg>
        </div>

        <h2 className="text-xl font-semibold theme-text mb-2">
          {isChunkError ? 'Page failed to load' : 'Something went wrong'}
        </h2>

        <p className="text-sm theme-text-muted mb-6">
          {isChunkError
            ? 'A cached build artifact could not be loaded. This can happen when the dev server rebuilds. Click below to retry.'
            : error.message || 'An unexpected error occurred.'}
        </p>

        <div className="flex gap-3 justify-center">
          <button
            onClick={() => {
              sessionStorage.removeItem('chunk_error_retried');
              reset();
            }}
            className="px-4 py-2 btn-primary rounded-lg transition-colors text-sm font-medium"
          >
            Retry
          </button>
          <button
            onClick={() => window.location.reload()}
            className="px-4 py-2 btn-secondary rounded-lg transition-colors text-sm font-medium"
          >
            Reload Page
          </button>
        </div>
      </div>
    </div>
  );
}
