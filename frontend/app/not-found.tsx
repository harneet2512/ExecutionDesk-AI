import Link from 'next/link';

export default function NotFound() {
  return (
    <div className="flex-1 flex items-center justify-center min-h-[60vh]">
      <div className="text-center max-w-md mx-auto p-6">
        <div className="w-16 h-16 mx-auto mb-4 rounded-full bg-[var(--color-fill-secondary)] flex items-center justify-center">
          <span className="text-2xl font-bold theme-text-muted">404</span>
        </div>

        <h2 className="text-xl font-semibold theme-text mb-2">
          Page not found
        </h2>

        <p className="text-sm theme-text-muted mb-6">
          The page you are looking for does not exist or has been moved.
        </p>

        <Link
          href="/"
          className="px-4 py-2 btn-primary rounded-lg transition-colors text-sm font-medium inline-block"
        >
          Go Home
        </Link>
      </div>
    </div>
  );
}
