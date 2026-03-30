'use client';

import SuggestionChips from './SuggestionChips';
import { BRAND } from '@/src/config/brand';

interface ChatEmptyStateProps {
    onSelectSuggestion: (text: string) => void;
}

export default function ChatEmptyState({ onSelectSuggestion }: ChatEmptyStateProps) {
    return (
        <div className="flex items-center justify-center h-full px-4">
            <div className="max-w-2xl w-full text-center space-y-8">
                {/* Icon */}
                <div className="inline-flex items-center justify-center w-20 h-20 bg-neutral-800 dark:bg-neutral-200 rounded-xl shadow-lg">
                    <span className="text-4xl">💹</span>
                </div>

                {/* Welcome Text */}
                <div className="space-y-3">
                    <h1 className="text-3xl font-bold theme-text">
                        Welcome to {BRAND.name}
                    </h1>
                    <p className="text-lg theme-text-secondary max-w-xl mx-auto">
                        I can help you analyze markets, execute trades, and manage your portfolio with natural language commands.
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
