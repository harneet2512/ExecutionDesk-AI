import { Suspense } from 'react';
import ChatPageClient from './ChatPageClient';

function ChatPageFallback() {
  return (
    <div className="flex items-center justify-center h-full theme-bg">
      <div className="text-sm theme-text-secondary animate-pulse">Loading...</div>
    </div>
  );
}

export default function ChatPage() {
  return (
    <Suspense fallback={<ChatPageFallback />}>
      <ChatPageClient />
    </Suspense>
  );
}
