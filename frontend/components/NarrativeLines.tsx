'use client';

import Link from 'next/link';

interface EvidenceRef {
  kind: 'artifact' | 'url' | 'run';
  id: string;
}

interface EvidenceItem {
  label: string;
  ref: string | EvidenceRef;
}

interface NarrativeStructured {
  lead: string;
  lines: string[];
  evidence: EvidenceItem[];
}

interface NarrativeLinesProps {
  structured?: NarrativeStructured;
  fallbackContent?: string;
  className?: string;
}

const SAFE_ROUTES = new Set(['/runs', '/chat', '/evals', '/performance', '/ops']);

function isSafeRoute(path: string): boolean {
  const base = '/' + path.replace(/^\//, '').split('/')[0].split('?')[0].split('#')[0];
  return SAFE_ROUTES.has(base);
}

interface ResolvedRef {
  href: string;
  isExternal: boolean;
  isDisabled: boolean;
}

function resolveRef(ref: string | EvidenceRef): ResolvedRef {
  if (typeof ref === 'object' && ref !== null && 'kind' in ref) {
    switch (ref.kind) {
      case 'run':
        return { href: `/runs/${ref.id}`, isExternal: false, isDisabled: false };
      case 'url': {
        const path = ref.id;
        if (isSafeRoute(path)) {
          return { href: path, isExternal: false, isDisabled: false };
        }
        return { href: '', isExternal: false, isDisabled: true };
      }
      case 'artifact':
        return { href: '', isExternal: false, isDisabled: true };
      default:
        return { href: '', isExternal: false, isDisabled: true };
    }
  }

  const refStr = String(ref || '');

  if (refStr.startsWith('url:')) {
    const path = refStr.slice(4);
    if (isSafeRoute(path)) {
      return { href: path, isExternal: false, isDisabled: false };
    }
    return { href: '', isExternal: false, isDisabled: true };
  }
  if (refStr.startsWith('run:')) {
    const runPath = refStr.slice(4);
    const [runId, artifactKey] = runPath.split('#');
    return {
      href: `/runs/${runId}${artifactKey ? `#${artifactKey}` : ''}`,
      isExternal: false,
      isDisabled: false,
    };
  }
  if (refStr.startsWith('artifact:')) {
    return { href: '', isExternal: false, isDisabled: true };
  }
  if (refStr.startsWith('http://') || refStr.startsWith('https://')) {
    return { href: refStr, isExternal: true, isDisabled: false };
  }
  return { href: '', isExternal: false, isDisabled: true };
}

const chipActiveClass =
  'inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-medium ' +
  'bg-[#4a7bc8]/10 text-[#4a7bc8] hover:bg-[#4a7bc8]/20 hover:text-[#6b9ae8] ' +
  'dark:bg-[#7ba3f5]/10 dark:text-[#7ba3f5] dark:hover:bg-[#7ba3f5]/20 dark:hover:text-[#9bb8f8] ' +
  'transition-colors cursor-pointer';

const chipDisabledClass =
  'inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-medium ' +
  'bg-gray-200/60 text-gray-400 dark:bg-gray-700/40 dark:text-gray-500 ' +
  'cursor-default select-none';

const linkIcon = (
  <svg className="w-3 h-3 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101" />
    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10.172 13.828a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.102 1.101" />
  </svg>
);

export default function NarrativeLines({ structured, fallbackContent, className = '' }: NarrativeLinesProps) {
  if (!structured && !fallbackContent) return null;

  if (structured && structured.lead) {
    return (
      <div
        className={`font-[system-ui] text-[15px] leading-[1.5] ${className}`}
        data-testid="narrative-lines"
      >
        <div className="my-1 leading-relaxed text-sm theme-text" data-testid="narrative-lead">
          {structured.lead}
        </div>

        {(structured.lines ?? []).map((line, i) => (
          <div key={i} className="my-1 leading-relaxed text-sm theme-text-secondary" data-testid="narrative-line">
            {line}
          </div>
        ))}

        {(structured.evidence?.length ?? 0) > 0 && (
          <div className="mt-2 flex flex-wrap gap-2" data-testid="narrative-evidence">
            {structured.evidence.map((item, i) => {
              const { href, isExternal, isDisabled } = resolveRef(item.ref);

              if (isDisabled) {
                return (
                  <span
                    key={i}
                    data-testid="evidence-chip"
                    data-disabled="true"
                    title="Evidence unavailable"
                    className={chipDisabledClass}
                  >
                    {linkIcon}
                    {item.label}
                  </span>
                );
              }

              if (isExternal) {
                return (
                  <a
                    key={i}
                    href={href}
                    target="_blank"
                    rel="noopener noreferrer"
                    data-testid="evidence-chip"
                    className={chipActiveClass}
                  >
                    {linkIcon}
                    {item.label}
                  </a>
                );
              }

              return (
                <Link
                  key={i}
                  href={href}
                  data-testid="evidence-chip"
                  className={chipActiveClass}
                >
                  {linkIcon}
                  {item.label}
                </Link>
              );
            })}
          </div>
        )}
      </div>
    );
  }

  const text = fallbackContent || '';
  const lines = text.split(/\n\n|\n/).filter(Boolean);
  if (lines.length === 0) return null;

  return (
    <div
      className={`font-[system-ui] text-[15px] leading-[1.5] ${className}`}
      data-testid="narrative-lines"
    >
      {lines.map((line, i) => (
        <div key={i} className="my-1 leading-relaxed text-sm theme-text-secondary" data-testid="narrative-line">
          {line}
        </div>
      ))}
    </div>
  );
}
