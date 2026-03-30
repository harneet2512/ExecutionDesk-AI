'use client';

import { useState, useEffect } from 'react';

interface NewsToggleProps {
    onToggle?: (enabled: boolean) => void;
    initialValue?: boolean;
}

/**
 * Toggle switch for enabling/disabling news analysis in trading decisions.
 * Persists state to localStorage for consistency across sessions.
 */
export default function NewsToggle({ onToggle, initialValue }: NewsToggleProps) {
    const [enabled, setEnabled] = useState<boolean>(initialValue ?? true);
    const [mounted, setMounted] = useState(false);

    // Load from localStorage on mount
    useEffect(() => {
        setMounted(true);
        const stored = localStorage.getItem('newsEnabled');
        if (stored !== null) {
            const value = stored === 'true';
            setEnabled(value);
            // Don't call onToggle on mount - parent can read from localStorage if needed
            // This prevents stale closure issues and unnecessary re-renders
        }
    }, []);

    const handleToggle = () => {
        const newValue = !enabled;
        setEnabled(newValue);
        localStorage.setItem('newsEnabled', String(newValue));
        onToggle?.(newValue);
    };

    // Prevent hydration mismatch
    if (!mounted) {
        return (
            <div className="flex items-center gap-2 text-sm">
                <div className="w-10 h-5 rounded-full bg-neutral-300 dark:bg-neutral-600" />
                <span className="theme-text-muted">Use News</span>
            </div>
        );
    }

    return (
        <div className="flex items-center gap-2">
            <button
                onClick={handleToggle}
                role="switch"
                aria-checked={enabled}
                aria-pressed={enabled}
                aria-label={enabled ? 'Disable news analysis' : 'Enable news analysis'}
                data-testid="news-toggle"
                className={`
          relative inline-flex h-5 w-10 shrink-0 cursor-pointer items-center rounded-full
          transition-colors duration-200 ease-in-out focus:outline-none focus:ring-2
          focus:ring-[var(--color-focus-ring)] focus:ring-offset-2
          ${enabled
                        ? 'bg-[var(--color-fill-primary)]'
                        : 'bg-neutral-300 dark:bg-neutral-600'
                    }
        `}
            >
                <span
                    className={`
            inline-block h-4 w-4 transform rounded-full bg-white shadow-sm
            transition-transform duration-200 ease-in-out
            ${enabled ? 'translate-x-5' : 'translate-x-0.5'}
          `}
                />
            </button>
            <span className="text-sm font-medium theme-text-secondary">
                Use News
            </span>
            {enabled && (
                <span className="text-xs theme-text-muted">
                    (RSS + GDELT)
                </span>
            )}
        </div>
    );
}
