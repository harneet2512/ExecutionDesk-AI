/**
 * Normalize assistant text for enterprise RAG display.
 * - Removes markdown headings (#, ##, ###, etc.)
 * - Collapses excessive blank lines to max 1
 * - Preserves URLs and normal text
 */
export function normalizeAssistantText(text: string | null | undefined): string {
  if (text == null || typeof text !== 'string') return '';
  const trimmed = text.trim();
  if (!trimmed) return '';

  const lines = trimmed.split('\n');
  const out: string[] = [];

  for (const line of lines) {
    // Remove markdown heading: optional whitespace + 1-6 # + space + rest
    const stripped = line.replace(/^\s{0,10}#{1,6}\s+/, '');
    out.push(stripped);
  }

  // Collapse excessive blank lines to max 1
  const joined = out.join('\n');
  const collapsed = joined.replace(/\n{3,}/g, '\n\n');
  return collapsed.trim();
}
