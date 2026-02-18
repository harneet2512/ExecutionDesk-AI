'use client';

import { useState, useEffect, useRef } from 'react';
import { useRouter } from 'next/navigation';
import { LineChart, Line, BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from 'recharts';
import { executeCommandText } from '@/lib/api';

interface CommandResponse {
  run_id: string;
  parsed_intent: any;
  selected_asset?: string;
  selected_order?: any;
  decision_trace: any[];
}

export default function AgentPage() {
  const router = useRouter();
  const [command, setCommand] = useState('');
  const [executionMode, setExecutionMode] = useState('PAPER');
  const [loading, setLoading] = useState(false);
  const [currentRun, setCurrentRun] = useState<any>(null);
  const [events, setEvents] = useState<any[]>([]);
  const [pnlData, setPnlData] = useState<any[]>([]);
  const [latencyData, setLatencyData] = useState<any[]>([]);
  const eventSourceRef = useRef<EventSource | null>(null);

  useEffect(() => {
    return () => {
      if (eventSourceRef.current) {
        eventSourceRef.current.close();
      }
    };
  }, []);

  async function handleSubmit() {
    if (!command.trim()) return;

    setLoading(true);
    setEvents([]);
    setCurrentRun(null);

    try {
      // Handle "replay run X" command
      if (command.toLowerCase().startsWith('replay run')) {
        const runMatch = command.match(/replay run\s+([a-zA-Z0-9_-]+)/i);
        if (runMatch) {
          const sourceRunId = runMatch[1];
          const result = await executeCommandText(command, executionMode, sourceRunId);
          if (result.run_id) {
            router.push(`/runs/${result.run_id}`);
            return;
          }
        }
      }

      // Handle trade commands
      const result = await executeCommandText(command, executionMode);
      setCurrentRun(result);
      
      if (!result.run_id) {
        throw new Error('No run_id returned');
      }
      
      const data = { run_id: result.run_id };

      // Subscribe to SSE events
      if (eventSourceRef.current) {
        eventSourceRef.current.close();
      }

      const eventSource = new EventSource(`/api/v1/runs/${data.run_id}/events`, {
        withCredentials: false,
      } as any);

      eventSource.onmessage = (event) => {
        try {
          const eventData = JSON.parse(event.data);
          setEvents((prev) => [...prev, eventData]);
        } catch (e) {
          console.error('Failed to parse SSE event:', e);
        }
      };

      eventSource.onerror = () => {
        eventSource.close();
        setLoading(false);
      };

      eventSourceRef.current = eventSource;

            // Poll for run completion and redirect
            const pollInterval = setInterval(async () => {
              try {
                const runDetail = await fetch(`/api/v1/runs/${data.run_id}`, {
                  headers: { 'X-Dev-Tenant': 't_default' },
                }).then((r) => r.json());

                if (runDetail.run.status === 'COMPLETED' || runDetail.run.status === 'FAILED' || runDetail.run.status === 'PAUSED') {
                  clearInterval(pollInterval);
                  setLoading(false);
                  // Redirect to run detail page to see full trace
                  router.push(`/runs/${data.run_id}`);
                }
              } catch (e) {
                console.error('Poll failed:', e);
              }
            }, 2000);
    } catch (error) {
      console.error('Command failed:', error);
      setLoading(false);
    }
  }

  return (
    <div className="p-8 max-w-7xl mx-auto">
      <h1 className="text-3xl font-bold mb-6">Agent Command Interface</h1>

      <div className="mb-6">
        <div className="flex gap-2">
          <input
            type="text"
            value={command}
            onChange={(e) => setCommand(e.target.value)}
            placeholder='e.g., "buy the most profitable crypto of last 24hrs for $10" or "buy $10 of BTC" or "replay run run_xxx"'
            className="flex-1 px-4 py-2 border theme-border rounded"
            onKeyPress={(e) => e.key === 'Enter' && handleSubmit()}
            disabled={loading}
          />
          <select
            value={executionMode}
            onChange={(e) => setExecutionMode(e.target.value)}
            className="px-3 py-2 border theme-border rounded"
            disabled={loading}
          >
            <option value="PAPER">PAPER</option>
            <option value="LIVE">LIVE</option>
          </select>
          <button
            onClick={handleSubmit}
            disabled={loading || !command.trim()}
            className="px-6 py-2 btn-primary rounded disabled:opacity-40"
          >
            {loading ? 'Executing...' : 'Execute'}
          </button>
        </div>
      </div>

      {currentRun && (
        <div className="mb-6 p-4 theme-bg rounded">
          <h2 className="text-xl font-bold mb-2">Command Result</h2>
          <div className="space-y-2">
            <p><strong>Run ID:</strong> {currentRun.run_id}</p>
            <p><strong>Parsed Intent:</strong> {JSON.stringify(currentRun.parsed_intent, null, 2)}</p>
            {currentRun.selected_asset && (
              <p><strong>Selected Asset:</strong> {currentRun.selected_asset}</p>
            )}
          </div>
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6">
        {pnlData.length > 0 && (
          <div className="p-4 theme-surface border theme-border rounded">
            <h3 className="text-lg font-bold mb-4 theme-text">PnL Over Time</h3>
            <ResponsiveContainer width="100%" height={300}>
              <LineChart data={pnlData}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="ts" />
                <YAxis />
                <Tooltip />
                <Legend />
                <Line type="monotone" dataKey="total_value_usd" stroke="#737373" name="Total Value (USD)" />
              </LineChart>
            </ResponsiveContainer>
          </div>
        )}

        {latencyData.length > 0 && (
          <div className="p-4 theme-surface border theme-border rounded">
            <h3 className="text-lg font-bold mb-4 theme-text">Latency</h3>
            <ResponsiveContainer width="100%" height={300}>
              <BarChart data={latencyData}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="ts" />
                <YAxis />
                <Tooltip />
                <Legend />
                <Bar dataKey="latency_ms" fill="#a3a3a3" name="Latency (ms)" />
              </BarChart>
            </ResponsiveContainer>
          </div>
        )}
      </div>

      <div className="p-4 theme-surface border theme-border rounded">
        <h3 className="text-lg font-bold mb-4 theme-text">Live Events</h3>
        <div className="max-h-64 overflow-y-auto space-y-1">
          {events.length === 0 ? (
            <p className="theme-text-secondary">No events yet...</p>
          ) : (
            events.map((event, idx) => (
              <div key={idx} className="text-sm p-2 theme-bg rounded">
                <strong>{event.event_type}:</strong> {JSON.stringify(event.payload || event, null, 2)}
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
}
