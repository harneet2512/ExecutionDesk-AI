'use client';

/**
 * ChatDisclaimer - Persistent footer disclaimer (ChatGPT-style)
 * 
 * Displays a non-intrusive disclaimer at the bottom of the chat interface
 * to ensure users understand this is not financial advice.
 */
export default function ChatDisclaimer() {
  return (
    <div className="text-center text-xs theme-text-secondary py-2 border-t theme-border theme-bg">
      This is not financial advice. Information is for educational purposes only. Trading involves risk.
    </div>
  );
}
