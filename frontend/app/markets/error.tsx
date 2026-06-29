'use client';

export default function MarketsError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <div className="flex-1 flex items-center justify-center min-h-[60vh]">
      <div className="text-center max-w-md mx-auto p-6">
        <h2 className="text-xl font-semibold theme-text mb-2">
          Failed to load markets
        </h2>
        <p className="text-sm theme-text-muted mb-6">
          {error.message || 'An unexpected error occurred while loading market data.'}
        </p>
        <button
          onClick={reset}
          className="px-4 py-2 btn-primary rounded-lg text-sm font-medium"
          aria-label="Retry loading markets"
        >
          Retry
        </button>
      </div>
    </div>
  );
}
