'use client';

import { useState, useEffect, useRef } from 'react';
import { useRouter } from 'next/navigation';
import { executeCommandText } from '@/lib/api';

export default function AgentPage() {
  const router = useRouter();
  const [command, setCommand] = useState('');
  const [executionMode, setExecutionMode] = useState('PAPER');
  const [loading, setLoading] = useState(false);
  const [currentRun, setCurrentRun] = useState<any>(null);
  const [events, setEvents] = useState<any[]>([]);
  const eventSourceRef = useRef<EventSource | null>(null);

  useEffect(() => {
    return () => { if (eventSourceRef.current) eventSourceRef.current.close(); };
  }, []);

  async function handleSubmit() {
    if (!command.trim()) return;
    setLoading(true);
    setEvents([]);
    setCurrentRun(null);

    try {
      if (command.toLowerCase().startsWith('replay run')) {
        const runMatch = command.match(/replay run\s+([a-zA-Z0-9_-]+)/i);
        if (runMatch) {
          const result = await executeCommandText(command, executionMode, runMatch[1]);
          if (result.run_id) { router.push(`/runs/${result.run_id}`); return; }
        }
      }

      const result = await executeCommandText(command, executionMode);
      setCurrentRun(result);
      if (!result.run_id) throw new Error('No run_id returned');

      if (eventSourceRef.current) eventSourceRef.current.close();

      const eventSource = new EventSource(`/api/v1/runs/${result.run_id}/events`, { withCredentials: false } as any);
      eventSource.onmessage = (event) => {
        try {
          setEvents((prev) => [...prev, JSON.parse(event.data)]);
        } catch {}
      };
      eventSource.onerror = () => { eventSource.close(); setLoading(false); };
      eventSourceRef.current = eventSource;

      const pollInterval = setInterval(async () => {
        try {
          const runDetail = await fetch(`/api/v1/runs/${result.run_id}`, {
            headers: { 'X-Dev-Tenant': 't_default' },
          }).then((r) => r.json());
          if (['COMPLETED', 'FAILED', 'PAUSED'].includes(runDetail.run?.status)) {
            clearInterval(pollInterval);
            setLoading(false);
            router.push(`/runs/${result.run_id}`);
          }
        } catch {}
      }, 2000);
    } catch {
      setLoading(false);
    }
  }

  return (
    <div className="flex-1 overflow-y-auto p-6 lg:p-8 max-w-3xl mx-auto page-enter">
      <h1 className="text-xl font-semibold theme-text mb-1">Agent Command</h1>
      <p className="text-sm theme-text-muted mb-6">Direct command execution with live event stream</p>

      {/* Command input */}
      <div className="flex gap-2 mb-6">
        <input
          type="text"
          value={command}
          onChange={(e) => setCommand(e.target.value)}
          placeholder='e.g. "buy $100 of BTC" or "replay run run_xxx"'
          className="flex-1 px-3 py-2 text-sm rounded-lg border theme-border theme-surface theme-text focus:outline-none focus:ring-1 focus:ring-[var(--color-focus-ring)]"
          onKeyDown={(e) => e.key === 'Enter' && handleSubmit()}
          disabled={loading}
        />
        <select
          value={executionMode}
          onChange={(e) => setExecutionMode(e.target.value)}
          className="text-xs px-2.5 py-2 rounded-lg border theme-border theme-surface theme-text"
          disabled={loading}
        >
          <option value="PAPER">PAPER</option>
          <option value="LIVE">LIVE</option>
        </select>
        <button
          onClick={handleSubmit}
          disabled={loading || !command.trim()}
          className="px-5 py-2 text-sm font-medium btn-primary rounded-lg disabled:opacity-40"
        >
          {loading ? 'Running...' : 'Execute'}
        </button>
      </div>

      {/* Run result */}
      {currentRun && (
        <div className="metric-card mb-6">
          <div className="metric-label">Command Result</div>
          <div className="space-y-1 mt-2">
            <div className="flex gap-2 text-xs">
              <span className="theme-text-muted">Run ID</span>
              <span className="font-mono text-[var(--color-link)]">{currentRun.run_id}</span>
            </div>
            {currentRun.parsed_intent && (
              <div className="text-xs">
                <span className="theme-text-muted">Intent: </span>
                <code className="text-xs theme-text">{JSON.stringify(currentRun.parsed_intent)}</code>
              </div>
            )}
            {currentRun.selected_asset && (
              <div className="text-xs">
                <span className="theme-text-muted">Asset: </span>
                <span className="font-medium theme-text">{currentRun.selected_asset}</span>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Live events */}
      <div className="border theme-border rounded-lg overflow-hidden">
        <div className="px-4 py-3 theme-elevated flex items-center justify-between">
          <span className="section-header !mb-0">
            {loading && <span className="live-dot mr-2" />}
            Live Events
          </span>
          <span className="text-[10px] theme-text-muted tabular-nums">{events.length} events</span>
        </div>
        <div className="max-h-72 overflow-y-auto divide-y divide-[var(--color-border-subtle)]">
          {events.length === 0 ? (
            <div className="px-4 py-10 text-center theme-text-muted text-sm">
              {loading ? 'Waiting for events...' : 'Submit a command to see live events'}
            </div>
          ) : (
            events.map((event, idx) => (
              <div key={idx} className="px-4 py-2 text-xs">
                <span className="font-semibold theme-text">{event.event_type}</span>
                <span className="theme-text-muted ml-2">{JSON.stringify(event.payload || event).slice(0, 200)}</span>
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
}
