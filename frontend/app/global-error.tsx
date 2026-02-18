'use client';

/**
 * Root-level error boundary for unrecoverable errors.
 * This catches errors that escape the route-level error.tsx,
 * including errors in the root layout itself.
 */
export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <html>
      <body>
        <div style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          minHeight: '100vh',
          fontFamily: 'system-ui, -apple-system, sans-serif',
          backgroundColor: '#0f172a',
          color: '#e2e8f0',
        }}>
          <div style={{ textAlign: 'center', maxWidth: '480px', padding: '24px' }}>
            <h1 style={{ fontSize: '24px', fontWeight: 700, marginBottom: '12px' }}>
              Application Error
            </h1>
            <p style={{ fontSize: '14px', color: '#94a3b8', marginBottom: '24px' }}>
              {error.message || 'An unrecoverable error occurred. Please reload the application.'}
            </p>
            <div style={{ display: 'flex', gap: '12px', justifyContent: 'center' }}>
              <button
                onClick={() => reset()}
                style={{
                  padding: '10px 20px',
                  backgroundColor: '#2563eb',
                  color: 'white',
                  border: 'none',
                  borderRadius: '8px',
                  cursor: 'pointer',
                  fontSize: '14px',
                  fontWeight: 500,
                }}
              >
                Try Again
              </button>
              <button
                onClick={() => window.location.href = '/'}
                style={{
                  padding: '10px 20px',
                  backgroundColor: '#334155',
                  color: '#e2e8f0',
                  border: 'none',
                  borderRadius: '8px',
                  cursor: 'pointer',
                  fontSize: '14px',
                  fontWeight: 500,
                }}
              >
                Reload Application
              </button>
            </div>
          </div>
        </div>
      </body>
    </html>
  );
}
