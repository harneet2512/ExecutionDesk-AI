'use client';

import SuggestionChips from './SuggestionChips';
import { ArrowTrendingUpIcon } from './icons';
import { BRAND } from '@/src/config/brand';

interface ChatEmptyStateProps {
    onSelectSuggestion: (text: string) => void;
}

export default function ChatEmptyState({ onSelectSuggestion }: ChatEmptyStateProps) {
    return (
        <div className="flex items-center justify-center h-full px-4">
            <div className="max-w-2xl w-full text-center space-y-8">
                {/* Icon */}
                <div className="inline-flex items-center justify-center w-16 h-16 rounded-2xl" style={{ backgroundColor: 'var(--color-fill-primary)' }}>
                    <ArrowTrendingUpIcon className="w-8 h-8" style={{ color: 'var(--color-text-on-fill)' }} />
                </div>

                {/* Welcome Text */}
                <div className="space-y-3">
                    <h1 className="text-xl font-semibold theme-text">
                        Welcome to {BRAND.name}
                    </h1>
                    <p className="text-sm theme-text-muted max-w-xl mx-auto">
                        Analyze markets, execute trades, and manage your portfolio with natural language.
                    </p>
                </div>

                {/* Suggestion Chips */}
                <div className="pt-4">
                    <p className="text-sm theme-text-secondary mb-4">
                        Try one of these to get started:
                    </p>
                    <SuggestionChips onSelectSuggestion={onSelectSuggestion} />
                </div>
            </div>
        </div>
    );
}
