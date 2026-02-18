'use client';

import { useState, useEffect } from 'react';
import { listConversations, createConversation, deleteConversation, type Conversation } from '@/lib/api';
import { useRouter } from 'next/navigation';

function getFriendlySidebarError(error: any): string {
    const message = String(error?.message || '');
    const requestIdMatch = message.match(/Request ID:\s*([a-zA-Z0-9-]+)/i);
    const requestId = requestIdMatch?.[1];

    if (error?.isNetworkError || error?.statusCode === 0) {
        return 'Cannot reach the backend server. Start the backend and try again.';
    }

    if (error?.statusCode >= 500) {
        return requestId
            ? `Server is temporarily unavailable. Try again in a moment. (Request ID: ${requestId})`
            : 'Server is temporarily unavailable. Try again in a moment.';
    }

    if (error?.statusCode === 429) {
        const retryAfter = Number(error?.retryAfterSeconds) || 60;
        return `Too many requests. Please retry in about ${retryAfter} seconds.`;
    }

    return message || 'Could not load conversations';
}

export default function ConversationList() {
    const router = useRouter();
    const [conversations, setConversations] = useState<Conversation[]>([]);
    const [loading, setLoading] = useState(true);
    const [loadError, setLoadError] = useState<string | null>(null);
    const [currentConversationId, setCurrentConversationId] = useState<string | null>(null);
    const [deleteModalOpen, setDeleteModalOpen] = useState(false);
    const [conversationToDelete, setConversationToDelete] = useState<string | null>(null);
    const [deleting, setDeleting] = useState(false);
    const [deleteError, setDeleteError] = useState<string | null>(null);

    useEffect(() => {
        loadConversations();
    }, []);

    const loadConversations = async () => {
        try {
            setLoading(true);
            setLoadError(null);
            const convs = await listConversations();
            setConversations(Array.isArray(convs) ? convs : []);
        } catch (e: any) {
            console.error('Failed to load conversations:', e);
            setLoadError(getFriendlySidebarError(e));
            setConversations([]);
        } finally {
            setLoading(false);
        }
    };

    const handleNewChat = async () => {
        try {
            const conv = await createConversation();
            await loadConversations();
            setCurrentConversationId(conv.conversation_id);
            router.push(`/chat?conversation=${conv.conversation_id}`);
        } catch (e: any) {
            console.error('Failed to create conversation:', e);
            setLoadError(getFriendlySidebarError(e));
        }
    };

    const handleSelectConversation = (conversationId: string) => {
        setCurrentConversationId(conversationId);
        router.push(`/chat?conversation=${conversationId}`);
    };

    const handleDeleteClick = (e: React.MouseEvent, conversationId: string) => {
        e.stopPropagation(); // Prevent selecting the conversation
        setConversationToDelete(conversationId);
        setDeleteError(null);
        setDeleteModalOpen(true);
    };

    const handleConfirmDelete = async () => {
        if (!conversationToDelete) return;

        try {
            setDeleting(true);
            await deleteConversation(conversationToDelete);

            // Remove from local state
            setConversations(prev => prev.filter(c => c.conversation_id !== conversationToDelete));

            // If we deleted the current conversation, navigate to a new one
            if (currentConversationId === conversationToDelete) {
                const remainingConversations = conversations.filter(c => c.conversation_id !== conversationToDelete);
                if (remainingConversations.length > 0) {
                    handleSelectConversation(remainingConversations[0].conversation_id);
                } else {
                    // Create a new conversation if none left
                    handleNewChat();
                }
            }
        } catch (e: any) {
            console.error('Failed to delete conversation:', e);
            setDeleteError(e?.message || 'Failed to delete conversation');
        } finally {
            setDeleting(false);
            setDeleteModalOpen(false);
            setConversationToDelete(null);
        }
    };

    const handleCancelDelete = () => {
        setDeleteModalOpen(false);
        setConversationToDelete(null);
    };

    if (loading) {
        return (
            <div className="p-4 space-y-3">
                {[1, 2, 3].map((i) => (
                    <div key={i} className="h-16 theme-elevated rounded-lg animate-pulse" />
                ))}
            </div>
        );
    }

    return (
        <>
            <div className="p-3 space-y-2">
                {/* New Chat Button */}
                <button
                    onClick={handleNewChat}
                    className="w-full px-4 py-3 btn-primary rounded-lg text-sm font-medium transition-colors shadow-sm"
                >
                    + New Chat
                </button>

                {/* Error Banner */}
                {loadError && (
                    <div className="p-3 bg-[var(--color-status-error-bg)] border border-[var(--color-status-error)]/20 rounded-lg">
                        <p className="text-xs text-[var(--color-status-error)] mb-2">
                            {loadError}
                        </p>
                        <button
                            onClick={loadConversations}
                            className="text-xs font-medium text-[var(--color-status-error)] hover:underline"
                        >
                            Retry
                        </button>
                    </div>
                )}

                {/* Conversations List */}
                {!loadError && conversations.length === 0 ? (
                    <p className="text-sm theme-text-secondary text-center py-8">
                        No conversations yet. Start a new chat!
                    </p>
                ) : (
                    <div className="space-y-1">
                        {conversations.map((conv) => (
                            <div
                                key={conv.conversation_id}
                                className={`group relative flex items-center rounded-lg text-sm transition-all ${currentConversationId === conv.conversation_id
                                        ? 'theme-elevated border-l-2 border-neutral-500 theme-text shadow-sm'
                                        : 'hover:bg-neutral-100 dark:hover:bg-neutral-800 theme-text-secondary'
                                    }`}
                            >
                                <button
                                    onClick={() => handleSelectConversation(conv.conversation_id)}
                                    className="flex-1 text-left px-3 py-3"
                                >
                                    <div className="truncate font-medium pr-6">{conv.title || 'New Conversation'}</div>
                                    <div className="text-xs theme-text-muted mt-1">
                                        {new Date(conv.updated_at).toLocaleDateString()}
                                    </div>
                                </button>

                                {/* Delete button - visible on hover */}
                                <button
                                    onClick={(e) => handleDeleteClick(e, conv.conversation_id)}
                                    className="absolute right-2 top-1/2 -translate-y-1/2 p-2 rounded-lg opacity-0 group-hover:opacity-100 hover:bg-[var(--color-status-error-bg)] theme-text-muted hover:text-[var(--color-status-error)] transition-all"
                                    title="Delete conversation"
                                >
                                    <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                                    </svg>
                                </button>
                            </div>
                        ))}
                    </div>
                )}
            </div>

            {/* Delete Confirmation Modal */}
            {deleteModalOpen && (
                <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
                    <div className="theme-surface rounded-lg shadow-xl p-6 max-w-sm mx-4">
                        <h3 className="text-lg font-semibold theme-text mb-2">
                            Delete Conversation
                        </h3>
                        <p className="theme-text-secondary mb-4">
                            Are you sure you want to delete this conversation permanently? This action cannot be undone.
                        </p>
                        {deleteError && (
                            <p className="text-xs text-[var(--color-status-error)] mb-4 p-2 bg-[var(--color-status-error-bg)] rounded">
                                {deleteError}
                            </p>
                        )}
                        <div className="flex justify-end gap-3">
                            <button
                                onClick={handleCancelDelete}
                                disabled={deleting}
                                className="btn-ghost px-4 py-2 text-sm font-medium rounded-lg transition-colors"
                            >
                                Cancel
                            </button>
                            <button
                                onClick={handleConfirmDelete}
                                disabled={deleting}
                                className="btn-destructive px-4 py-2 text-sm font-medium rounded-lg transition-colors disabled:opacity-50"
                            >
                                {deleting ? 'Deleting...' : 'Delete'}
                            </button>
                        </div>
                    </div>
                </div>
            )}
        </>
    );
}
