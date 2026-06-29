'use client';

import { Suspense } from 'react';
import { ChevronRightIcon } from './icons';
import ConversationList from './ConversationList';
import ChatPageClient from '@/app/chat/ChatPageClient';

interface ChatPanelProps {
    isOpen: boolean;
    onClose: () => void;
}

export default function ChatPanel({ isOpen, onClose }: ChatPanelProps) {
    if (!isOpen) return null;

    return (
        <div className="w-96 theme-surface border-l theme-border flex flex-col min-h-0 flex-shrink-0">
            {/* Panel Header */}
            <div className="px-4 py-3 border-b theme-border flex items-center justify-between flex-shrink-0">
                <h2 className="text-sm font-semibold theme-text uppercase tracking-wide">
                    Chat
                </h2>
                <button
                    onClick={onClose}
                    className="w-8 h-8 rounded-lg flex items-center justify-center theme-text-secondary hover:theme-text hover:bg-[var(--color-fill-ghost-hover)] transition-all"
                    aria-label="Close chat panel"
                    title="Close chat panel"
                >
                    <ChevronRightIcon className="w-5 h-5" />
                </button>
            </div>

            {/* Chat Content */}
            <div className="flex-1 flex flex-col min-h-0 overflow-hidden">
                <Suspense fallback={
                    <div className="flex items-center justify-center h-full theme-bg">
                        <div className="text-sm theme-text-secondary animate-pulse">Loading chat...</div>
                    </div>
                }>
                    <ChatPageClient />
                </Suspense>
            </div>
        </div>
    );
}
