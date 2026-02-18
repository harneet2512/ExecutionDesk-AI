'use client';

import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import type { Components } from 'react-markdown';
import { normalizeAssistantText } from '@/lib/normalizeAssistantText';

interface MarkdownMessageProps {
  content: string;
  className?: string;
}

/**
 * MarkdownMessage component for rendering markdown content in chat messages.
 * Supports GitHub Flavored Markdown including tables, strikethrough, etc.
 * Applies normalizeAssistantText to strip markdown headings for enterprise RAG display.
 */
export default function MarkdownMessage({ content, className = '' }: MarkdownMessageProps) {
  const normalized = normalizeAssistantText(content);
  // Custom components for styling markdown elements
  const components: Components = {
    // Tables
    table: ({ children, ...props }) => (
      <div className="overflow-x-auto my-3">
        <table
          className="min-w-full border-collapse text-sm"
          {...props}
        >
          {children}
        </table>
      </div>
    ),
    thead: ({ children, ...props }) => (
      <thead className="theme-elevated" {...props}>
        {children}
      </thead>
    ),
    tbody: ({ children, ...props }) => (
      <tbody className="divide-y divide-neutral-200 dark:divide-neutral-700" {...props}>
        {children}
      </tbody>
    ),
    tr: ({ children, ...props }) => (
      <tr className="hover:bg-neutral-50 dark:hover:bg-neutral-800/50" {...props}>
        {children}
      </tr>
    ),
    th: ({ children, ...props }) => (
      <th
        className="border border-neutral-300 dark:border-neutral-600 px-3 py-2 text-left font-semibold theme-text"
        {...props}
      >
        {children}
      </th>
    ),
    td: ({ children, ...props }) => (
      <td
        className="border border-neutral-300 dark:border-neutral-600 px-3 py-2 theme-text-secondary"
        {...props}
      >
        {children}
      </td>
    ),

    // Headings: render as normal-weight paragraphs (enterprise RAG - no big headers)
    h1: ({ children, ...props }) => (
      <p className="text-base font-medium theme-text mt-3 mb-1" {...props}>
        {children}
      </p>
    ),
    h2: ({ children, ...props }) => (
      <p className="text-base font-medium theme-text mt-3 mb-1" {...props}>
        {children}
      </p>
    ),
    h3: ({ children, ...props }) => (
      <p className="text-sm font-medium theme-text mt-2 mb-1" {...props}>
        {children}
      </p>
    ),
    h4: ({ children, ...props }) => (
      <p className="text-sm font-medium theme-text mt-2 mb-1" {...props}>
        {children}
      </p>
    ),
    h5: ({ children, ...props }) => (
      <p className="text-sm theme-text mt-2 mb-1" {...props}>
        {children}
      </p>
    ),
    h6: ({ children, ...props }) => (
      <p className="text-sm theme-text mt-2 mb-1" {...props}>
        {children}
      </p>
    ),

    // Text elements
    p: ({ children, ...props }) => (
      <p className="my-2 leading-relaxed" {...props}>
        {children}
      </p>
    ),
    strong: ({ children, ...props }) => (
      <strong className="font-semibold theme-text" {...props}>
        {children}
      </strong>
    ),
    em: ({ children, ...props }) => (
      <em className="italic theme-text-secondary" {...props}>
        {children}
      </em>
    ),

    // Lists
    ul: ({ children, ...props }) => (
      <ul className="list-disc list-inside my-2 space-y-1 pl-2" {...props}>
        {children}
      </ul>
    ),
    ol: ({ children, ...props }) => (
      <ol className="list-decimal list-inside my-2 space-y-1 pl-2" {...props}>
        {children}
      </ol>
    ),
    li: ({ children, ...props }) => (
      <li className="theme-text-secondary" {...props}>
        {children}
      </li>
    ),

    // Code
    code: ({ children, className: codeClassName, ...props }) => {
      // Check if this is inline code or a code block
      const isInline = !codeClassName;
      if (isInline) {
        return (
          <code
            className="theme-elevated px-2 py-1 rounded-lg text-sm font-mono theme-text"
            {...props}
          >
            {children}
          </code>
        );
      }
      return (
        <code className={`${codeClassName} block`} {...props}>
          {children}
        </code>
      );
    },
    pre: ({ children, ...props }) => (
      <pre
        className="theme-elevated rounded-lg p-3 my-2 overflow-x-auto text-sm font-mono"
        {...props}
      >
        {children}
      </pre>
    ),

    // Horizontal rule
    hr: ({ ...props }) => (
      <hr className="my-4 theme-border" {...props} />
    ),

    // Links: enterprise contrast, hover underline (works in light and dark)
    a: ({ children, href, ...props }) => (
      <a
        href={href}
        className="text-[#4a7bc8] hover:text-[#6b9ae8] hover:underline focus:outline-none focus:ring-2 focus:ring-[var(--color-focus-ring)] focus:ring-offset-1 rounded px-0.5 dark:text-[#7ba3f5] dark:hover:text-[#9bb8f8]"
        target="_blank"
        rel="noopener noreferrer"
        {...props}
      >
        {children}
      </a>
    ),

    // Blockquote
    blockquote: ({ children, ...props }) => (
      <blockquote
        className="border-l-4 border-neutral-300 dark:border-neutral-600 pl-4 my-2 theme-text-secondary italic"
        {...props}
      >
        {children}
      </blockquote>
    ),
  };

  return (
    <div className={`prose prose-sm dark:prose-invert max-w-none font-[system-ui] text-[15px] leading-[1.5] ${className}`}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={components}
      >
        {normalized}
      </ReactMarkdown>
    </div>
  );
}
