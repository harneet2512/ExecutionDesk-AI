import { test, expect } from '@playwright/test';
import { normalizeArtifacts } from '../../frontend/lib/artifacts';

test.describe('normalizeArtifacts', () => {
  test('handles array input', async () => {
    const input = [{ id: 'a1', artifact_type: 'plan', artifact_json: { ok: true } }];
    const out = normalizeArtifacts(input);
    expect(out).toHaveLength(1);
    expect(out[0].id).toBe('a1');
    expect(out[0].artifact_type).toBe('plan');
  });

  test('handles object map input', async () => {
    const input = {
      k1: { id: 'a1', artifact_type: 'plan' },
      k2: { id: 'a2', artifact_type: 'decision_record' },
    };
    const out = normalizeArtifacts(input);
    expect(out).toHaveLength(2);
    expect(out.map((x) => x.id)).toEqual(['a1', 'a2']);
  });

  test('handles single object input', async () => {
    const input = { id: 'single', artifact_type: 'plan' };
    const out = normalizeArtifacts(input);
    expect(out).toHaveLength(1);
    expect(out[0].id).toBe('single');
  });

  test('handles null/undefined and primitive input', async () => {
    expect(normalizeArtifacts(null)).toEqual([]);
    expect(normalizeArtifacts(undefined)).toEqual([]);
    expect(normalizeArtifacts('string')).toEqual([]);
    expect(normalizeArtifacts(42)).toEqual([]);
  });
});
