'use client';

import { ReactNode } from 'react';
import {
    RocketIcon,
    ChartBarIcon,
    CurrencyDollarIcon,
    ArrowPathIcon,
} from './icons';

interface SuggestionChipsProps {
    onSelectSuggestion: (text: string) => void;
}

const suggestions: { icon: ReactNode; text: string }[] = [
    {
        icon: <RocketIcon className="w-5 h-5 flex-shrink-0" />,
        text: 'Buy $2 of the highest-performing crypto in the last 24h',
    },
    {
        icon: <ChartBarIcon className="w-5 h-5 flex-shrink-0" />,
        text: 'Analyze my portfolio',
    },
    {
        icon: <CurrencyDollarIcon className="w-5 h-5 flex-shrink-0" />,
        text: 'Buy $2 of BTC',
    },
    {
        icon: <ArrowPathIcon className="w-5 h-5 flex-shrink-0" />,
        text: 'Sell last purchase',
    },
];

export default function SuggestionChips({ onSelectSuggestion }: SuggestionChipsProps) {
    return (
        <div className="flex flex-wrap gap-3 justify-center">
            {suggestions.map((suggestion, index) => (
                <button
                    key={index}
                    onClick={() => onSelectSuggestion(suggestion.text)}
                    className="group px-4 py-3 theme-surface hover:bg-neutral-100 dark:hover:bg-neutral-800 border theme-border rounded-xl text-sm text-left transition-all shadow-sm hover:shadow-md hover:border-neutral-400 dark:hover:border-neutral-500"
                >
                    <div className="flex items-start gap-2">
                        <span className="theme-text-secondary group-hover:theme-text">{suggestion.icon}</span>
                        <span className="theme-text-secondary group-hover:theme-text">
                            {suggestion.text}
                        </span>
                    </div>
                </button>
            ))}
        </div>
    );
}
