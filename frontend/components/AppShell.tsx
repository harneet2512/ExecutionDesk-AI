'use client';

import { useState, useEffect, ReactNode } from 'react';
import IconRail from './IconRail';
import ChatPanel from './ChatPanel';

export type NavSection = 'chats' | 'trades' | 'evals' | 'telemetry' | 'ops' | 'clients';

interface AppShellProps {
    children: ReactNode;
}

export default function AppShell({ children }: AppShellProps) {
    const [darkMode, setDarkMode] = useState(true);
    const [chatPanelOpen, setChatPanelOpen] = useState(false);
    const [mounted, setMounted] = useState(false);

    // Load preferences from localStorage
    useEffect(() => {
        const savedDark = localStorage.getItem('darkMode');
        if (savedDark !== null) setDarkMode(savedDark === 'true');
        else setDarkMode(window.matchMedia('(prefers-color-scheme: dark)').matches);

        const savedChatPanel = localStorage.getItem('chatPanelOpen');
        if (savedChatPanel !== null) setChatPanelOpen(savedChatPanel === 'true');

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

    // Persist chat panel state
    useEffect(() => {
        if (!mounted) return;
        localStorage.setItem('chatPanelOpen', String(chatPanelOpen));
    }, [chatPanelOpen, mounted]);

    const toggleChatPanel = () => setChatPanelOpen(prev => !prev);

    return (
        <div className="flex h-screen theme-bg theme-text">
            {/* Icon Rail */}
            <IconRail
                darkMode={darkMode}
                onToggleDarkMode={() => setDarkMode(!darkMode)}
                chatPanelOpen={chatPanelOpen}
                onToggleChatPanel={toggleChatPanel}
            />

            {/* Main Content */}
            <main className="flex-1 flex flex-col min-h-0 overflow-y-auto">
                {children}
            </main>

            {/* Chat Panel (right side, collapsible) */}
            <ChatPanel
                isOpen={chatPanelOpen}
                onClose={() => setChatPanelOpen(false)}
            />
        </div>
    );
}
