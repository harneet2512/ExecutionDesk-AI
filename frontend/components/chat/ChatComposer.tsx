import React from 'react';
import ChatDisclaimer from '@/components/ChatDisclaimer';

export interface ChatComposerProps {
  inputText: string;
  onInputChange: (e: React.ChangeEvent<HTMLTextAreaElement>) => void;
  onSend: () => void;
  onKeyDown: (e: React.KeyboardEvent<HTMLTextAreaElement>) => void;
  loading: boolean;
  textareaRef: React.RefObject<HTMLTextAreaElement>;
}

export default function ChatComposer({
  inputText,
  onInputChange,
  onSend,
  onKeyDown,
  loading,
  textareaRef,
}: ChatComposerProps) {
  return (
    <>
      {/* Composer */}
      <div className="border-t theme-border theme-bg px-6 py-4">
        <div className="max-w-4xl mx-auto">
          {/* Input Area */}
          <div className="flex gap-2 items-end">
            <textarea
              ref={textareaRef}
              value={inputText}
              onChange={onInputChange}
              onKeyDown={onKeyDown}
              placeholder="Ask me anything about trading..."
              className="flex-1 px-4 py-3 border theme-border rounded-xl resize-none focus:outline-none focus:ring-2 focus:ring-[var(--color-focus-ring)] theme-surface theme-text placeholder-neutral-400"
              rows={1}
              disabled={loading}
            />
            <button
              onClick={onSend}
              disabled={loading || !inputText.trim()}
              className="px-6 py-3 btn-primary disabled:opacity-40 disabled:cursor-not-allowed rounded-xl font-medium transition-colors shadow-sm"
            >
              Send
            </button>
          </div>
          <p className="text-xs theme-text-muted mt-2 text-center">
            Press Enter to send, Shift+Enter for new line
          </p>
        </div>
      </div>

      {/* Footer Disclaimer */}
      <ChatDisclaimer />
    </>
  );
}
