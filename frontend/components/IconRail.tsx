'use client';

import { ReactNode } from 'react';
import { useRouter, usePathname } from 'next/navigation';
import {
    HomeIcon,
    ChatBubbleIcon,
    ChartBarIcon,
    CheckCircleIcon,
    ArrowTrendingUpIcon,
    CogIcon,
    GlobeAltIcon,
    UsersIcon,
    ScaleIcon,
    CurrencyDollarIcon,
    ChatPanelIcon,
    SunIcon,
    MoonIcon,
} from './icons';

interface NavItem {
    path: string;
    icon: ReactNode;
    label: string;
}

interface IconRailProps {
    darkMode: boolean;
    onToggleDarkMode: () => void;
    chatPanelOpen: boolean;
    onToggleChatPanel: () => void;
}

const navItems: NavItem[] = [
    { path: '/', icon: <HomeIcon className="w-6 h-6" />, label: 'Home' },
    { path: '/chat', icon: <ChatBubbleIcon className="w-6 h-6" />, label: 'Chats' },
    { path: '/runs', icon: <ChartBarIcon className="w-6 h-6" />, label: 'Trades' },
    { path: '/evals', icon: <CheckCircleIcon className="w-6 h-6" />, label: 'Evals' },
    { path: '/performance', icon: <ArrowTrendingUpIcon className="w-6 h-6" />, label: 'Telemetry' },
    { path: '/ops', icon: <CogIcon className="w-6 h-6" />, label: 'Operations' },
    { path: '/markets', icon: <GlobeAltIcon className="w-6 h-6" />, label: 'Markets' },
    { path: '/liquidity', icon: <ScaleIcon className="w-6 h-6" />, label: 'Liquidity' },
    { path: '/positions', icon: <CurrencyDollarIcon className="w-6 h-6" />, label: 'Positions' },
    { path: '/clients', icon: <UsersIcon className="w-6 h-6" />, label: 'Clients' },
];

function isActive(pathname: string, itemPath: string): boolean {
    if (itemPath === '/') return pathname === '/';
    return pathname === itemPath || pathname.startsWith(itemPath + '/');
}

export default function IconRail({
    darkMode,
    onToggleDarkMode,
    chatPanelOpen,
    onToggleChatPanel,
}: IconRailProps) {
    const router = useRouter();
    const pathname = usePathname();

    return (
        <div className="w-16 theme-surface border-r theme-border flex flex-col items-center py-4 gap-2 min-h-0 overflow-x-hidden">
            {/* Logo/Brand */}
            <div className="w-10 h-10 rounded-xl flex items-center justify-center font-bold text-sm mb-4 flex-shrink-0"
                 style={{ backgroundColor: 'var(--color-fill-primary)', color: 'var(--color-text-on-fill)' }}>
                ED
            </div>

            {/* Navigation Icons */}
            <div className="flex flex-col gap-2 min-h-0 flex-1">
                {navItems.map((item) => (
                    <button
                        key={item.path}
                        onClick={() => router.push(item.path)}
                        className={`group relative w-12 h-12 rounded-xl flex items-center justify-center transition-all ${isActive(pathname, item.path)
                                ? 'nav-active-accent theme-elevated theme-text shadow-lg border theme-border-strong'
                                : 'theme-text-secondary hover:theme-text hover:bg-[var(--color-fill-ghost-hover)]'
                            }`}
                        title={item.label}
                        aria-label={item.label}
                    >
                        {item.icon}

                        {/* Tooltip */}
                        <div className="absolute left-full ml-2 px-3 py-2 theme-elevated theme-text text-sm rounded-lg opacity-0 group-hover:opacity-100 pointer-events-none transition-opacity whitespace-nowrap z-50 border theme-border shadow-lg">
                            {item.label}
                        </div>
                    </button>
                ))}
            </div>

            {/* Bottom Actions */}
            <div className="pt-2 mt-4 border-t theme-border flex-shrink-0 flex flex-col gap-2">
                {/* Chat Panel Toggle */}
                <button
                    onClick={onToggleChatPanel}
                    className={`w-12 h-12 rounded-xl flex items-center justify-center transition-all group relative ring-1 theme-border ${chatPanelOpen
                            ? 'theme-elevated theme-text shadow-lg'
                            : 'theme-text-secondary hover:theme-text hover:bg-[var(--color-fill-ghost-hover)]'
                        }`}
                    title={chatPanelOpen ? 'Hide Chat Panel' : 'Show Chat Panel'}
                    aria-label={chatPanelOpen ? 'Hide Chat Panel' : 'Show Chat Panel'}
                >
                    <ChatPanelIcon className="w-6 h-6" />

                    {/* Tooltip */}
                    <div className="absolute left-full ml-2 px-3 py-2 theme-elevated theme-text text-sm rounded-lg opacity-0 group-hover:opacity-100 pointer-events-none transition-opacity whitespace-nowrap z-50 border theme-border shadow-lg">
                        {chatPanelOpen ? 'Hide Chat Panel' : 'Show Chat Panel'}
                    </div>
                </button>

                {/* Dark Mode Toggle */}
                <button
                    onClick={onToggleDarkMode}
                    className="w-12 h-12 rounded-xl flex items-center justify-center theme-text-secondary hover:theme-text hover:bg-[var(--color-fill-ghost-hover)] transition-all group relative ring-1 theme-border"
                    title={darkMode ? 'Light Mode' : 'Dark Mode'}
                    aria-label={darkMode ? 'Switch to light mode' : 'Switch to dark mode'}
                >
                    {darkMode ? <SunIcon className="w-6 h-6" /> : <MoonIcon className="w-6 h-6" />}

                    {/* Tooltip */}
                    <div className="absolute left-full ml-2 px-3 py-2 theme-elevated theme-text text-sm rounded-lg opacity-0 group-hover:opacity-100 pointer-events-none transition-opacity whitespace-nowrap z-50 border theme-border shadow-lg">
                        {darkMode ? 'Light Mode' : 'Dark Mode'}
                    </div>
                </button>
            </div>
        </div>
    );
}
