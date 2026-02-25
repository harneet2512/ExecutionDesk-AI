export interface Artifact {
  id: string;
  type: string;
  title?: string;
  createdAt?: string;
  payload?: unknown;
  url?: string;
  run_id?: string;
  step_name?: string;
  artifact_type?: string;
  artifact_json?: unknown;
  created_at?: string;
}

function asRecord(v: unknown): Record<string, unknown> | null {
  if (!v || typeof v !== 'object' || Array.isArray(v)) return null;
  return v as Record<string, unknown>;
}

function normalizeArtifact(raw: unknown): Artifact | null {
  const obj = asRecord(raw);
  if (!obj) return null;
  const id = String(
    obj.id ??
      obj.artifact_id ??
      `${obj.run_id ?? 'run'}:${obj.step_name ?? 'step'}:${obj.artifact_type ?? 'artifact'}:${obj.created_at ?? ''}`
  );
  const type = String(obj.type ?? obj.artifact_type ?? 'unknown');
  const title = typeof obj.title === 'string' ? obj.title : undefined;
  const createdAt =
    typeof obj.createdAt === 'string'
      ? obj.createdAt
      : typeof obj.created_at === 'string'
      ? obj.created_at
      : undefined;
  const payload = obj.payload ?? obj.artifact_json;
  const url = typeof obj.url === 'string' ? obj.url : undefined;
  return {
    id,
    type,
    title,
    createdAt,
    payload,
    url,
    run_id: typeof obj.run_id === 'string' ? obj.run_id : undefined,
    step_name: typeof obj.step_name === 'string' ? obj.step_name : undefined,
    artifact_type: typeof obj.artifact_type === 'string' ? obj.artifact_type : undefined,
    artifact_json: obj.artifact_json,
    created_at: typeof obj.created_at === 'string' ? obj.created_at : undefined,
  };
}

export function normalizeArtifacts(input: unknown): Artifact[] {
  if (Array.isArray(input)) {
    return input.map(normalizeArtifact).filter((a): a is Artifact => a !== null);
  }
  const obj = asRecord(input);
  if (!obj) return [];
  const looksLikeArtifact =
    'artifact_type' in obj || 'artifact_json' in obj || 'type' in obj || 'id' in obj || 'step_name' in obj;
  if (looksLikeArtifact) {
    const normalized = normalizeArtifact(obj);
    return normalized ? [normalized] : [];
  }
  return Object.values(obj).map(normalizeArtifact).filter((a): a is Artifact => a !== null);
}
