'use client';

import { useEffect, useState } from 'react';
import { LineChart, Line, BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from 'recharts';
import { getPerformance } from '@/lib/api';

export default function PerformancePage() {
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [window, setWindow] = useState('7d');

  useEffect(() => {
    loadData();
  }, [window]);

  async function loadData() {
    try {
      const performance = await getPerformance(window);
      setData(performance);
    } catch (error) {
      console.error('Failed to load performance:', error);
    } finally {
      setLoading(false);
    }
  }

  if (loading || !data) return <div className="p-8">Loading...</div>;

  return (
    <div className="p-8 max-w-7xl mx-auto">
      <h1 className="text-3xl font-bold mb-6">Performance Analytics</h1>

      <div className="mb-4">
        <label className="mr-2">Window:</label>
        <select
          value={window}
          onChange={(e) => setWindow(e.target.value)}
          className="px-3 py-1 border rounded"
        >
          <option value="1d">1 Day</option>
          <option value="7d">7 Days</option>
          <option value="30d">30 Days</option>
        </select>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6">
        <div className="p-4 theme-surface border theme-border rounded">
          <h2 className="text-xl font-bold mb-4 theme-text">Daily PnL</h2>
          {data.daily_pnl.length > 0 ? (
            <ResponsiveContainer width="100%" height={300}>
              <LineChart data={data.daily_pnl}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="date" />
                <YAxis />
                <Tooltip />
                <Legend />
                <Line type="monotone" dataKey="pnl" stroke="#737373" name="PnL (USD)" />
              </LineChart>
            </ResponsiveContainer>
          ) : (
            <p className="theme-text-secondary">No PnL data available</p>
          )}
        </div>

        <div className="p-4 theme-surface border theme-border rounded">
          <h2 className="text-xl font-bold mb-4 theme-text">Daily Returns</h2>
          {data.daily_pnl.length > 0 ? (
            <ResponsiveContainer width="100%" height={300}>
              <BarChart data={data.daily_pnl}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="date" />
                <YAxis />
                <Tooltip />
                <Legend />
                <Bar dataKey="returns" fill="#a3a3a3" name="Returns" />
              </BarChart>
            </ResponsiveContainer>
          ) : (
            <p className="theme-text-secondary">No returns data available</p>
          )}
        </div>
      </div>

      <div className="p-4 theme-surface border theme-border rounded mb-6">
        <h2 className="text-xl font-bold mb-4 theme-text">Summary</h2>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <div>
            <p className="theme-text-secondary">Total PnL</p>
            <p className="text-2xl font-bold theme-text">${data.summary.total_pnl.toFixed(2)}</p>
          </div>
          <div>
            <p className="theme-text-secondary">Total Returns</p>
            <p className="text-2xl font-bold theme-text">{(data.summary.total_returns * 100).toFixed(2)}%</p>
          </div>
          <div>
            <p className="theme-text-secondary">Win Rate</p>
            <p className="text-2xl font-bold theme-text">{(data.summary.win_rate * 100).toFixed(1)}%</p>
          </div>
          <div>
            <p className="theme-text-secondary">Trades</p>
            <p className="text-2xl font-bold theme-text">{data.summary.trades_count}</p>
          </div>
        </div>
      </div>

      <div className="p-4 theme-surface border theme-border rounded">
        <h2 className="text-xl font-bold mb-4 theme-text">Recent Trades</h2>
        <table className="w-full border-collapse border theme-border">
          <thead>
            <tr className="theme-elevated">
              <th className="border theme-border p-2">Order ID</th>
              <th className="border theme-border p-2">Symbol</th>
              <th className="border theme-border p-2">Side</th>
              <th className="border theme-border p-2">Notional (USD)</th>
              <th className="border theme-border p-2">Time</th>
            </tr>
          </thead>
          <tbody>
            {data.trades.slice(0, 20).map((trade: any) => (
              <tr key={trade.order_id}>
                <td className="border theme-border p-2">{trade.order_id}</td>
                <td className="border theme-border p-2">{trade.symbol}</td>
                <td className="border theme-border p-2">{trade.side}</td>
                <td className="border theme-border p-2">${trade.notional_usd.toFixed(2)}</td>
                <td className="border theme-border p-2">{new Date(trade.created_at).toLocaleString()}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
