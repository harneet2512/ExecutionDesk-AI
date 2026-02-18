'use client';

import { useEffect, useState } from 'react';
import { getOpsMetrics } from '@/lib/api';
import { LineChart, Line, BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from 'recharts';

export default function OpsPage() {
  const [metrics, setMetrics] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    loadMetrics();
    const interval = setInterval(loadMetrics, 5000);
    return () => clearInterval(interval);
  }, []);

  async function loadMetrics() {
    try {
      const data = await getOpsMetrics();
      setMetrics(data);
    } catch (error) {
      console.error('Failed to load metrics:', error);
    } finally {
      setLoading(false);
    }
  }

  if (loading || !metrics) return <div className="p-8">Loading...</div>;

  return (
    <div className="p-8">
      <h1 className="text-3xl font-bold mb-6">Operations Dashboard</h1>
      
      <div className="grid grid-cols-2 gap-6 mb-6">
        <div>
          <h2 className="text-xl font-semibold mb-2">Run Duration Over Time</h2>
          {metrics.run_durations.length > 0 ? (
            <ResponsiveContainer width="100%" height={300}>
              <LineChart data={metrics.run_durations}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="ts" />
                <YAxis />
                <Tooltip />
                <Legend />
                <Line type="monotone" dataKey="duration_ms" stroke="#737373" name="Duration (ms)" />
              </LineChart>
            </ResponsiveContainer>
          ) : (
            <p>No run duration data yet</p>
          )}
        </div>
        
        <div>
          <h2 className="text-xl font-semibold mb-2">Order Fill Latency</h2>
          {metrics.order_fill_latency_ms.length > 0 ? (
            <ResponsiveContainer width="100%" height={300}>
              <BarChart data={metrics.order_fill_latency_ms}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="ts" />
                <YAxis />
                <Tooltip />
                <Legend />
                <Bar dataKey="latency_ms" fill="#a3a3a3" name="Latency (ms)" />
              </BarChart>
            </ResponsiveContainer>
          ) : (
            <p>No fill latency data yet</p>
          )}
        </div>
      </div>

      <div className="grid grid-cols-2 gap-6">
        <div>
          <h2 className="text-xl font-semibold mb-2">Eval Score Trends</h2>
          {metrics.eval_trends.length > 0 ? (
            <ResponsiveContainer width="100%" height={300}>
              <LineChart data={metrics.eval_trends}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="ts" />
                <YAxis />
                <Tooltip />
                <Legend />
                <Line type="monotone" dataKey="score" stroke="#ffc658" name="Score" />
              </LineChart>
            </ResponsiveContainer>
          ) : (
            <p>No eval trends data yet</p>
          )}
        </div>
        
        <div>
          <h2 className="text-xl font-semibold mb-2">Policy Blocks Over Time</h2>
          {metrics.policy_blocks.length > 0 ? (
            <ResponsiveContainer width="100%" height={300}>
              <BarChart data={metrics.policy_blocks}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="ts" />
                <YAxis />
                <Tooltip />
                <Legend />
                <Bar dataKey="count" fill="#525252" name="Blocks" />
              </BarChart>
            </ResponsiveContainer>
          ) : (
            <p>No policy blocks data yet</p>
          )}
        </div>
      </div>
    </div>
  );
}
