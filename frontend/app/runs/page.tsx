'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { listRuns, triggerRun, Run } from '@/lib/api';

export default function RunsPage() {
  const [runs, setRuns] = useState<Run[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    loadRuns();
  }, []);

  async function loadRuns() {
    try {
      const data = await listRuns();
      setRuns(data);
    } catch (error) {
      console.error('Failed to load runs:', error);
    } finally {
      setLoading(false);
    }
  }

  async function handleTrigger() {
    try {
      await triggerRun();
      await loadRuns();
    } catch (error) {
      console.error('Failed to trigger run:', error);
    }
  }

  if (loading) return <div className="p-8">Loading...</div>;

  return (
    <div className="p-8">
      <div className="flex justify-between items-center mb-6">
        <h1 className="text-3xl font-bold">Runs</h1>
        <button
          onClick={handleTrigger}
          className="px-4 py-2 btn-primary rounded"
        >
          Trigger Run
        </button>
      </div>
      <table className="w-full border-collapse border theme-border">
        <thead>
          <tr className="theme-elevated">
            <th className="border theme-border p-2">Run ID</th>
            <th className="border theme-border p-2">Status</th>
            <th className="border theme-border p-2">Mode</th>
            <th className="border theme-border p-2">Created</th>
            <th className="border theme-border p-2">Actions</th>
          </tr>
        </thead>
        <tbody>
          {runs.map((run) => (
            <tr key={run.run_id}>
              <td className="border theme-border p-2 font-mono text-xs" title={run.run_id}>{run.run_id.slice(0, 12)}...</td>
              <td className="border theme-border p-2">{run.status}</td>
              <td className="border theme-border p-2">{run.execution_mode}</td>
              <td className="border theme-border p-2">{new Date(run.created_at).toLocaleString()}</td>
              <td className="border theme-border p-2">
                <Link href={`/runs/${run.run_id}`} className="theme-text hover:opacity-80 hover:underline">
                  View
                </Link>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
