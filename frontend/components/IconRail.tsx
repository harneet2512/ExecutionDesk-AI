'use client';

import { NavSection } from './AppShell';

interface IconRailProps {
    activeSection: NavSection;
    onSectionChange: (section: NavSection) => void;
    darkMode: boolean;
    onToggleDarkMode: () => void;
}

const sections: { id: NavSection; icon: string; label: string }[] = [
    { id: 'chats', icon: '💬', label: 'Chats' },
    { id: 'trades', icon: '📊', label: 'Trades' },
    { id: 'evals', icon: '✓', label: 'Evals' },
    { id: 'telemetry', icon: '📈', label: 'Telemetry' },
    { id: 'ops', icon: '⚙️', label: 'Operations' },
];

export default function IconRail({
    activeSection,
    onSectionChange,
    darkMode,
    onToggleDarkMode,
}: IconRailProps) {
    return (
        <div className="w-16 theme-surface border-r theme-border flex flex-col items-center py-4 gap-2 min-h-0 overflow-x-hidden">
            {/* Logo/Brand */}
            <div className="w-10 h-10 theme-elevated rounded-xl flex items-center justify-center theme-text font-bold text-lg mb-4 shadow-lg flex-shrink-0 border theme-border">
                A
            </div>

            {/* Navigation Icons */}
            <div className="flex flex-col gap-2 min-h-0">
                {sections.map((section) => (
                    <button
                        key={section.id}
                        onClick={() => onSectionChange(section.id)}
                        className={`group relative w-12 h-12 rounded-xl flex items-center justify-center transition-all ${activeSection === section.id
                                ? 'theme-elevated theme-text shadow-lg border theme-border-strong'
                                : 'theme-text-secondary hover:theme-text hover:bg-[var(--color-fill-ghost-hover)]'
                            }`}
                        title={section.label}
                    >
                        <span className="text-2xl">{section.icon}</span>

                        {/* Tooltip */}
                        <div className="absolute left-full ml-2 px-3 py-2 theme-elevated theme-text text-sm rounded-lg opacity-0 group-hover:opacity-100 pointer-events-none transition-opacity whitespace-nowrap z-50 border theme-border shadow-lg">
                            {section.label}
                        </div>
                    </button>
                ))}
            </div>

            {/* Dark Mode Toggle - always visible at bottom */}
            <div className="pt-2 mt-4 border-t theme-border flex-shrink-0">
                <button
                    onClick={onToggleDarkMode}
                    className="w-12 h-12 rounded-xl flex items-center justify-center text-amber-400 hover:bg-[var(--color-fill-ghost-hover)] transition-all group relative ring-1 theme-border"
                    title={darkMode ? 'Light Mode' : 'Dark Mode'}
                    aria-label={darkMode ? 'Switch to light mode' : 'Switch to dark mode'}
                >
                    <span className="text-2xl">{darkMode ? '☀️' : '🌙'}</span>

                    {/* Tooltip */}
                    <div className="absolute left-full ml-2 px-3 py-2 theme-elevated theme-text text-sm rounded-lg opacity-0 group-hover:opacity-100 pointer-events-none transition-opacity whitespace-nowrap z-50 border theme-border shadow-lg">
                        {darkMode ? 'Light Mode' : 'Dark Mode'}
                    </div>
                </button>
            </div>
        </div>
    );
}
