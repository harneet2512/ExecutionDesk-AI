export type RunStatus =
  | 'CREATED'
  | 'RUNNING'
  | 'COMPLETED'
  | 'FAILED'
  | 'PAUSED'
  | 'CANCELLED'
  | 'PENDING_APPROVAL'
  | 'APPROVED';

export type ExecutionMode = 'PAPER' | 'LIVE' | 'ASSISTED_LIVE';

const STATUS_CONFIG: Record<string, { bg: string; text: string; label?: string }> = {
  CREATED:          { bg: 'bg-neutral-500',                              text: 'text-white' },
  RUNNING:          { bg: 'bg-[var(--color-status-info)]',               text: 'text-white' },
  COMPLETED:        { bg: 'bg-[var(--color-status-success)]',            text: 'text-white' },
  FAILED:           { bg: 'bg-[var(--color-status-error)]',              text: 'text-white' },
  PAUSED:           { bg: 'bg-[var(--color-status-warning)]',            text: 'text-black' },
  CANCELLED:        { bg: 'bg-neutral-400',                              text: 'text-white' },
  PENDING_APPROVAL: { bg: 'bg-[var(--color-status-warning)]',            text: 'text-black', label: 'PENDING' },
  APPROVED:         { bg: 'bg-[var(--color-status-success)]',            text: 'text-white' },
};

const MODE_CONFIG: Record<string, { bg: string; text: string }> = {
  PAPER:         { bg: 'bg-neutral-600',                              text: 'text-white' },
  LIVE:          { bg: 'bg-[var(--color-status-error)]',              text: 'text-white' },
  ASSISTED_LIVE: { bg: 'bg-[var(--color-status-warning)]',           text: 'text-black' },
};

export function getStatusClasses(status: string): { bg: string; text: string } {
  return STATUS_CONFIG[status] || STATUS_CONFIG.CREATED;
}

export function getStatusLabel(status: string): string {
  return STATUS_CONFIG[status]?.label || status;
}

export function getModeClasses(mode: string): { bg: string; text: string } {
  return MODE_CONFIG[mode] || MODE_CONFIG.PAPER;
}
