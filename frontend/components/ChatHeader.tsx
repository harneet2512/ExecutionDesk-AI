'use client';

interface ChatHeaderProps {
    conversationTitle?: string;
    onNewChat: () => void;
    onToggleSteps?: () => void;
    stepsOpen?: boolean;
}

export default function ChatHeader({
    conversationTitle,
    onNewChat,
    onToggleSteps,
    stepsOpen = false,
}: ChatHeaderProps) {
    return (
        <div className="px-6 py-4 border-b theme-border theme-surface">
            <div className="flex items-center justify-between">
                {/* Title */}
                <div className="flex-1 min-w-0">
                    <h1 className="text-lg font-semibold theme-text truncate">
                        {conversationTitle || 'New Conversation'}
                    </h1>
                </div>

                {/* Actions */}
                <div className="flex items-center gap-2">
                    {onToggleSteps && (
                        <button
                            onClick={onToggleSteps}
                            className={`px-3 py-2 rounded-lg text-sm font-medium transition-colors ${stepsOpen
                                    ? 'theme-elevated theme-text'
                                    : 'btn-secondary'
                                }`}
                        >
                            {stepsOpen ? 'Hide Steps' : 'Show Steps'}
                        </button>
                    )}
                    <button
                        onClick={onNewChat}
                        className="px-3 py-2 btn-primary rounded-lg text-sm font-medium transition-colors shadow-sm"
                    >
                        + New Chat
                    </button>
                </div>
            </div>
        </div>
    );
}
