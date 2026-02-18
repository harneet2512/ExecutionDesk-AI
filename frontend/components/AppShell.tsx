'use client';

import { useState, useEffect, ReactNode } from 'react';
import IconRail from './IconRail';
import ResizableSidebarPanel from './ResizableSidebarPanel';

export type NavSection = 'chats' | 'trades' | 'evals' | 'telemetry' | 'ops';

interface AppShellProps {
    children: ReactNode;
}

export default function AppShell({ children }: AppShellProps) {
    const [activeSection, setActiveSection] = useState<NavSection>('chats');
    const [darkMode, setDarkMode] = useState(true);
    const [mounted, setMounted] = useState(false);

    // Load dark mode preference
    useEffect(() => {
        const saved = localStorage.getItem('darkMode');
        if (saved !== null) setDarkMode(saved === 'true');
        else setDarkMode(window.matchMedia('(prefers-color-scheme: dark)').matches);
        setMounted(true);
    }, []);

    // Apply dark mode class to document
    useEffect(() => {
        if (!mounted) return;
        if (darkMode) {
            document.documentElement.classList.add('dark');
            document.body.classList.add('dark');
        } else {
            document.documentElement.classList.remove('dark');
            document.body.classList.remove('dark');
        }
        localStorage.setItem('darkMode', String(darkMode));
    }, [darkMode, mounted]);

    return (
        <div className="flex h-screen theme-bg theme-text">
            {/* Icon Rail */}
            <IconRail
                activeSection={activeSection}
                onSectionChange={setActiveSection}
                darkMode={darkMode}
                onToggleDarkMode={() => setDarkMode(!darkMode)}
            />

            {/* Resizable Sidebar Panel */}
            <ResizableSidebarPanel
                activeSection={activeSection}
            />

            {/* Main Content */}
            <main className="flex-1 flex flex-col overflow-hidden">
                {children}
            </main>
        </div>
    );
}
