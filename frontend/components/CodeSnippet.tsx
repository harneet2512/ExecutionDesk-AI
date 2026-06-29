'use client';

import { useState } from 'react';

type Language = 'python' | 'javascript' | 'curl';

interface CodeSnippetProps {
  snippets: Record<Language, string>;
  title?: string;
}

const LANGUAGE_LABELS: Record<Language, string> = {
  python: 'Python',
  javascript: 'JavaScript',
  curl: 'cURL',
};

export default function CodeSnippet({ snippets, title }: CodeSnippetProps) {
  const languages = Object.keys(snippets) as Language[];
  const [active, setActive] = useState<Language>(languages[0]);
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(snippets[active]);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Clipboard API may not be available
    }
  };

  return (
    <div className="rounded-lg border theme-border overflow-hidden">
      {title && (
        <div className="px-4 py-2 theme-surface border-b theme-border text-sm font-medium theme-text">
          {title}
        </div>
      )}
      <div className="flex items-center justify-between px-4 py-2 theme-elevated border-b theme-border">
        <div className="flex gap-1">
          {languages.map((lang) => (
            <button
              key={lang}
              onClick={() => setActive(lang)}
              className={`px-3 py-1 text-xs rounded-md transition-colors ${
                active === lang
                  ? 'theme-surface theme-text font-medium border theme-border-strong'
                  : 'theme-text-secondary hover:theme-text'
              }`}
            >
              {LANGUAGE_LABELS[lang]}
            </button>
          ))}
        </div>
        <button
          onClick={handleCopy}
          className="px-2 py-1 text-xs theme-text-secondary hover:theme-text transition-colors"
          title="Copy to clipboard"
        >
          {copied ? 'Copied' : 'Copy'}
        </button>
      </div>
      <pre className="p-4 overflow-x-auto text-sm leading-relaxed theme-bg theme-text font-mono">
        <code>{snippets[active]}</code>
      </pre>
    </div>
  );
}
