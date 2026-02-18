'use client';

import { useEffect, useState, useRef } from 'react';
import { useParams } from 'next/navigation';
import { getRunDetail, getRunStatus, getPortfolioValueOverTime, approve, deny, listApprovals, getTrace } from '@/lib/api';
import { LineChart, Line, BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from 'recharts';

const fmtNum = (v: any, digits = 2) => (typeof v === 'number' && isFinite(v) ? v.toFixed(digits) : '\u2014');

/** Coerce any API-origin value to string for safe React rendering. */
function safeStr(v: unknown): string {
  if (typeof v === 'string') return v;
  if (typeof v === 'number' && isFinite(v)) return String(v);
  if (v != null && typeof v === 'object') return JSON.stringify(v);
  return '';
}

export default function RunDetailPage() {
  const params = useParams();
  const runId = params.id as string;
  const [detail, setDetail] = useState<any>(null);
  const [trace, setTrace] = useState<any>(null);
  const [portfolioData, setPortfolioData] = useState<any[]>([]);
  const [approvals, setApprovals] = useState<any[]>([]);
  const [events, setEvents] = useState<any[]>([]);
  const [activeTab, setActiveTab] = useState<'timeline' | 'evidence' | 'orders' | 'pnl' | 'charts' | 'evals'>('timeline');
  const [pnlData, setPnlData] = useState<any>(null);
  const [slippageData, setSlippageData] = useState<any>(null);
  const [fills, setFills] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [runStatus, setRunStatus] = useState<string>('');
  const [showDebugIds, setShowDebugIds] = useState(false);
  const [runEvals, setRunEvals] = useState<any[]>([]);
  const eventSourceRef = useRef<EventSource | null>(null);
  const terminalRef = useRef(false);

  // Full data load - only on initial mount and when status transitions to terminal
  async function loadDataFull() {
    try {
      const [runDetail, portfolio, pendingApprovals, traceData, pnl, slippage] = await Promise.all([
        getRunDetail(runId),
        getPortfolioValueOverTime(runId).catch(() => []),
        listApprovals().catch(() => []),
        getTrace(runId).catch(() => null),
        fetch(`/api/v1/analytics/pnl?run_id=${runId}`, {
          headers: { 'X-Dev-Tenant': 't_default' },
        }).then(r => r.json()).catch(() => null),
        fetch(`/api/v1/analytics/slippage?run_id=${runId}`, {
          headers: { 'X-Dev-Tenant': 't_default' },
        }).then(r => r.json()).catch(() => null),
      ]);
      setDetail(runDetail);
      const status = runDetail?.run?.status || '';
      setRunStatus(status);
      setPortfolioData(portfolio);
      setApprovals(pendingApprovals.filter((a: any) => a.run_id === runId));
      setTrace(traceData);
      setPnlData(pnl);
      setSlippageData(slippage);

      if (runDetail.fills) {
        setFills(runDetail.fills);
      }

      if (['COMPLETED', 'FAILED'].includes(status)) {
        terminalRef.current = true;
      }
    } catch (error) {
      console.error('Failed to load run detail:', error);
    } finally {
      setLoading(false);
    }
  }

  // Lightweight status poll - 1 query instead of 6+
  async function pollStatus() {
    if (terminalRef.current) return;
    try {
      const data = await getRunStatus(runId);
      const status = data.status || '';
      setRunStatus(status);
      if (['COMPLETED', 'FAILED'].includes(status)) {
        terminalRef.current = true;
        // Terminal reached - do one full data load to get final results
        loadDataFull();
      }
    } catch (error) {
      console.error('Failed to poll run status:', error);
    }
  }

  useEffect(() => {
    // Initial full load + SSE subscription (runs once per runId)
    loadDataFull();

    // SSE for real-time events
    if (eventSourceRef.current) eventSourceRef.current.close();
    const eventSource = new EventSource(`/api/v1/runs/${runId}/events`, {
      withCredentials: false,
    } as any);
    eventSource.onmessage = (event) => {
      try {
        const eventData = JSON.parse(event.data);
        setEvents((prev) => [...prev, eventData]);
        // Update status from event if available (no full reload)
        if (eventData.event_type === 'RUN_COMPLETE' || eventData.status) {
          pollStatus();
        }
      } catch (e) {
        console.error('Failed to parse SSE event:', e);
      }
    };
    eventSource.onerror = () => { eventSource.close(); };
    eventSourceRef.current = eventSource;

    // Lightweight poll every 5s (stops automatically when terminal)
    const interval = setInterval(pollStatus, 5000);
    return () => {
      clearInterval(interval);
      if (eventSourceRef.current) eventSourceRef.current.close();
    };
  }, [runId]);

  async function handleApprove(approvalId: string) {
    try {
      await approve(approvalId);
      await loadDataFull();
    } catch (error) {
      console.error('Failed to approve:', error);
    }
  }

  async function handleDeny(approvalId: string) {
    try {
      await deny(approvalId);
      await loadDataFull();
    } catch (error) {
      console.error('Failed to deny:', error);
    }
  }

  if (loading || !detail) return <div className="p-8">Loading...</div>;

  const isCommandRun = !!detail.run.command_text;
  const rankings = trace?.artifacts?.rankings || [];
  const candlesBatches = trace?.artifacts?.candles_batches || [];
  const toolCalls = trace?.artifacts?.tool_calls || [];
  const steps = trace?.steps || [];

  return (
    <div className="p-8 max-w-7xl mx-auto">
      <div className="flex items-center justify-between mb-2">
        <h1 className="text-3xl font-bold theme-text">Run Details</h1>
        <button
          onClick={() => setShowDebugIds(!showDebugIds)}
          className={`px-3 py-1.5 text-xs rounded-lg transition-colors ${showDebugIds ? 'bg-neutral-600 text-white' : 'theme-elevated theme-text-secondary hover:bg-[var(--color-fill-ghost-hover)]'}`}
        >
          {showDebugIds ? 'Debug ON' : 'Debug'}
        </button>
      </div>
      <div className="flex flex-wrap gap-4 text-sm theme-text-secondary mb-4">
        <span>Status: <span className={`font-medium ${detail.run.status === 'COMPLETED' ? 'text-[var(--color-status-success)]' : detail.run.status === 'FAILED' ? 'text-[var(--color-status-error)]' : 'theme-text'}`}>{detail.run.status}</span></span>
        <span>Mode: <span className="font-medium">{detail.run.execution_mode}</span></span>
        {showDebugIds && (
          <>
            <span>Run ID: <code className="theme-elevated px-1 rounded font-mono text-xs">{runId}</code></span>
            {detail.run.trace_id && (
              <span>Trace ID: <code className="theme-elevated px-1 rounded font-mono text-xs">{detail.run.trace_id}</code></span>
            )}
          </>
        )}
      </div>
      {isCommandRun && detail.run.command_text && (
        <p className="theme-text-secondary mb-4">Command: &quot;{detail.run.command_text}&quot;</p>
      )}
      
      {detail.run.status === 'PAUSED' && approvals.length > 0 && (
        <div className="mb-6 p-4 bg-[var(--color-status-warning-bg)] border border-[var(--color-status-warning)]/20 rounded">
          <h2 className="text-xl font-semibold mb-2 theme-text">Pending Approvals</h2>
          {approvals.map((approval: any) => (
            <div key={approval.approval_id} className="mb-2">
              <p>Approval ID: {approval.approval_id}</p>
              <div className="flex gap-2 mt-2">
                <button
                  onClick={() => handleApprove(approval.approval_id)}
                  className="px-4 py-2 bg-[var(--color-status-success)] text-white rounded hover:opacity-90"
                >
                  Approve
                </button>
                <button
                  onClick={() => handleDeny(approval.approval_id)}
                  className="px-4 py-2 bg-[var(--color-status-error)] text-white rounded hover:opacity-90"
                >
                  Deny
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Tabs */}
      <div className="flex gap-2 mb-6 border-b theme-border">
        <button
          onClick={() => setActiveTab('timeline')}
          className={`px-4 py-2 ${activeTab === 'timeline' ? 'border-b-2 border-neutral-800 dark:border-neutral-200' : ''}`}
        >
          Execution Trace
        </button>
        <button
          onClick={() => setActiveTab('evidence')}
          className={`px-4 py-2 ${activeTab === 'evidence' ? 'border-b-2 border-neutral-800 dark:border-neutral-200' : ''}`}
        >
          Evidence
        </button>
        <button
          onClick={() => setActiveTab('orders')}
          className={`px-4 py-2 ${activeTab === 'orders' ? 'border-b-2 border-neutral-800 dark:border-neutral-200' : ''}`}
        >
          Orders & Fills
        </button>
        <button
          onClick={() => setActiveTab('pnl')}
          className={`px-4 py-2 ${activeTab === 'pnl' ? 'border-b-2 border-neutral-800 dark:border-neutral-200' : ''}`}
        >
          PnL & Slippage
        </button>
        <button
          onClick={() => setActiveTab('charts')}
          className={`px-4 py-2 ${activeTab === 'charts' ? 'border-b-2 border-neutral-800 dark:border-neutral-200' : ''}`}
        >
          Charts
        </button>
        <button
          onClick={() => {
            setActiveTab('evals');
            // Load evals on first click
            if (runEvals.length === 0) {
              fetch(`/api/v1/evals/run/${runId}`, { headers: { 'X-Dev-Tenant': 't_default' } })
                .then(r => r.json())
                .then(data => setRunEvals(data.evals || []))
                .catch(() => {});
            }
          }}
          className={`px-4 py-2 ${activeTab === 'evals' ? 'border-b-2 border-neutral-800 dark:border-neutral-200' : ''}`}
        >
          Evals
        </button>
      </div>

      {/* Timeline Tab */}
      {activeTab === 'timeline' && (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <div className="lg:col-span-2">
            <h2 className="text-xl font-semibold mb-4 theme-text">Steps Timeline</h2>
            <div className="space-y-4">
              {steps.map((step: any, idx: number) => (
                <div
                  key={step.step_id || idx}
                  className={`p-4 border rounded ${
                    step.status === 'COMPLETED' ? 'bg-[var(--color-status-success-bg)] border-[var(--color-status-success)]/20' :
                    step.status === 'RUNNING' ? 'bg-[var(--color-status-info-bg)] border-[var(--color-status-info)]/20' :
                    step.status === 'FAILED' ? 'bg-[var(--color-status-error-bg)] border-[var(--color-status-error)]/20' :
                    'theme-bg theme-border'
                  }`}
                >
                  <div className="flex justify-between items-center">
                    <h3 className="font-semibold theme-text">{step.step_name}</h3>
                    <span className={`px-2 py-1 rounded text-sm ${
                      step.status === 'COMPLETED' ? 'bg-[var(--color-status-success-bg)] text-[var(--color-status-success)]' :
                      step.status === 'RUNNING' ? 'bg-[var(--color-status-info-bg)] text-[var(--color-status-info)]' :
                      'theme-elevated theme-text-secondary'
                    }`}>
                      {step.status}
                    </span>
                  </div>
                  {step.completed_at && (
                    <p className="text-sm theme-text-secondary mt-1">
                      Completed: {new Date(step.completed_at).toLocaleString()}
                    </p>
                  )}
                </div>
              ))}
            </div>

            <h2 className="text-xl font-semibold mt-6 mb-4">Live Events</h2>
            <div className="max-h-64 overflow-y-auto space-y-1">
              {events.length === 0 ? (
                <p className="theme-text-secondary">No events yet...</p>
              ) : (
                events.slice(-20).map((event: any, idx: number) => (
                  <div key={idx} className="text-sm p-2 theme-bg rounded theme-text">
                    <strong>{event.event_type || event.payload?.event_type}:</strong>{' '}
                    {event.payload?.summary || event.payload?.step_name || JSON.stringify(event.payload || event).slice(0, 100)}
                  </div>
                ))
              )}
            </div>
          </div>

          <div>
            <h2 className="text-xl font-semibold mb-4 theme-text">Plan Summary</h2>
            {trace?.plan ? (
              <div className="p-4 theme-bg rounded theme-text">
                <p><strong>Strategy:</strong> {trace.plan.strategy_spec?.strategy_name || 'N/A'}</p>
                <p><strong>Metric:</strong> {trace.plan.strategy_spec?.metric || 'N/A'}</p>
                <p><strong>Window:</strong> {trace.plan.strategy_spec?.window || 'N/A'}</p>
                {trace.plan.selected_asset && (
                  <p><strong>Selected Asset:</strong> {trace.plan.selected_asset}</p>
                )}
              </div>
            ) : (
              <p className="theme-text-secondary">No plan available</p>
            )}
          </div>
        </div>
      )}

      {/* Evidence Tab */}
      {activeTab === 'evidence' && (
        <div className="space-y-6">
          {/* Rankings */}
          {rankings.length > 0 && (
            <div className="p-4 theme-surface border theme-border rounded">
              <h2 className="text-xl font-semibold mb-4 theme-text">Asset Rankings</h2>
              <table className="w-full border-collapse border theme-border">
                <thead>
                  <tr className="theme-elevated">
                    <th className="border theme-border p-2 theme-text">Symbol</th>
                    <th className="border theme-border p-2 theme-text">Score</th>
                    <th className="border theme-border p-2 theme-text">First Price</th>
                    <th className="border theme-border p-2 theme-text">Last Price</th>
                    <th className="border theme-border p-2 theme-text">Return</th>
                  </tr>
                </thead>
                <tbody>
                  {rankings.map((rank: any, idx: number) => (
                    <tr key={idx} className={idx === 0 ? 'bg-[var(--color-status-success-bg)]' : ''}>
                      <td className="border theme-border p-2 theme-text">{rank.symbol}</td>
                      <td className="border theme-border p-2 theme-text">{fmtNum(rank.score, 4)}</td>
                      <td className="border theme-border p-2 theme-text">${fmtNum(rank.first_price)}</td>
                      <td className="border theme-border p-2 theme-text">${fmtNum(rank.last_price)}</td>
                      <td className="border theme-border p-2 theme-text">{typeof rank.first_price === 'number' && typeof rank.last_price === 'number' && rank.first_price !== 0
                        ? ((rank.last_price - rank.first_price) / rank.first_price * 100).toFixed(2) + '%'
                        : '\u2014'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {/* Candles Batches */}
          {candlesBatches.length > 0 && (
            <div className="p-4 theme-surface border theme-border rounded">
              <h2 className="text-xl font-semibold mb-4 theme-text">Market Data (Candles)</h2>
              <table className="w-full border-collapse border theme-border">
                <thead>
                  <tr className="theme-elevated">
                    <th className="border theme-border p-2">Symbol</th>
                    <th className="border theme-border p-2">Candles Count</th>
                  </tr>
                </thead>
                <tbody>
                  {candlesBatches.map((batch: any) => (
                    <tr key={batch.batch_id}>
                      <td className="border theme-border p-2">{batch.symbol}</td>
                      <td className="border theme-border p-2">{batch.candles_count}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {/* Tool Calls */}
          {toolCalls.length > 0 && (
            <div className="p-4 theme-surface border theme-border rounded">
              <h2 className="text-xl font-semibold mb-4 theme-text">Tool Calls</h2>
              <table className="w-full border-collapse border theme-border">
                <thead>
                  <tr className="theme-elevated">
                    <th className="border theme-border p-2">Tool</th>
                    <th className="border theme-border p-2">Server</th>
                    <th className="border theme-border p-2">Status</th>
                  </tr>
                </thead>
                <tbody>
                  {toolCalls.map((tc: any) => (
                    <tr key={tc.id}>
                      <td className="border theme-border p-2">{tc.tool_name}</td>
                      <td className="border theme-border p-2">{tc.mcp_server}</td>
                      <td className="border theme-border p-2">{tc.status}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {/* Evaluations */}
          {(detail?.evals ?? []).length > 0 && (
            <div className="p-4 theme-surface border theme-border rounded">
              <h2 className="text-xl font-semibold mb-4 theme-text">Evaluation Scorecard</h2>
              <table className="w-full border-collapse border theme-border">
                <thead>
                  <tr className="theme-elevated">
                    <th className="border theme-border p-2">Metric</th>
                    <th className="border theme-border p-2">Score</th>
                  </tr>
                </thead>
                <tbody>
                  {(detail?.evals ?? []).map((evaluation: any, evIdx: number) => (
                    <tr key={evaluation?.eval_id ?? evIdx}>
                      <td className="border theme-border p-2">{safeStr(evaluation?.eval_name)}</td>
                      <td className="border theme-border p-2">
                        <div className="flex items-center">
                          <span>{fmtNum(evaluation?.score)}</span>
                          <div className="ml-2 w-32 h-2 bg-neutral-200 dark:bg-neutral-700 rounded">
                            <div
                              className="h-2 bg-neutral-600 rounded"
                              style={{ width: `${typeof evaluation?.score === 'number' && isFinite(evaluation.score) ? evaluation.score * 100 : 0}%` }}
                            />
                          </div>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* Orders & Fills Tab */}
      {activeTab === 'orders' && (
        <div className="space-y-6">
          {/* Orders */}
          <div className="p-4 theme-surface border theme-border rounded">
            <h2 className="text-xl font-semibold mb-4 theme-text">Orders</h2>
            {detail.orders.length === 0 ? (
              <p className="theme-text-muted text-sm italic">No orders placed (this may be a portfolio analysis or non-trading run).</p>
            ) : (
            <table className="w-full border-collapse border theme-border">
              <thead>
                <tr className="theme-elevated">
                  <th className="border theme-border p-2">Order ID</th>
                  <th className="border theme-border p-2">Symbol</th>
                  <th className="border theme-border p-2">Side</th>
                  <th className="border theme-border p-2">Notional</th>
                  <th className="border theme-border p-2">Status</th>
                  <th className="border theme-border p-2">Avg Fill Price</th>
                  <th className="border theme-border p-2">Filled Qty</th>
                  <th className="border theme-border p-2">Total Fees</th>
                </tr>
              </thead>
              <tbody>
                {detail.orders.map((order: any) => (
                  <tr key={order.order_id}>
                    <td className="border theme-border p-2 text-xs">{order.order_id}</td>
                    <td className="border theme-border p-2">{order.symbol}</td>
                    <td className="border theme-border p-2">{order.side}</td>
                    <td className="border theme-border p-2">${fmtNum(order.notional_usd)}</td>
                    <td className="border theme-border p-2">{order.status}</td>
                    <td className="border theme-border p-2">${fmtNum(order.avg_fill_price)}</td>
                    <td className="border theme-border p-2">{fmtNum(order.filled_qty, 6)}</td>
                    <td className="border theme-border p-2">${fmtNum(order.total_fees, 4)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            )}
          </div>

          {/* Fills */}
          {detail.orders.length > 0 && fills.length === 0 && (
            <div className="p-4 theme-surface border theme-border rounded">
              <h2 className="text-xl font-semibold mb-4 theme-text">Fills</h2>
              <p className="theme-text-muted text-sm italic">No fills recorded yet. Fills appear after orders are matched by the exchange.</p>
            </div>
          )}
          {fills.length > 0 && (
            <div className="p-4 theme-surface border theme-border rounded">
              <h2 className="text-xl font-semibold mb-4 theme-text">Fills</h2>
              <table className="w-full border-collapse border theme-border">
                <thead>
                  <tr className="theme-elevated">
                    <th className="border theme-border p-2">Fill ID</th>
                    <th className="border theme-border p-2">Order ID</th>
                    <th className="border theme-border p-2">Product</th>
                    <th className="border theme-border p-2">Price</th>
                    <th className="border theme-border p-2">Size</th>
                    <th className="border theme-border p-2">Fee</th>
                    <th className="border theme-border p-2">Liquidity</th>
                  </tr>
                </thead>
                <tbody>
                  {fills.map((fill: any) => (
                    <tr key={fill.fill_id}>
                      <td className="border theme-border p-2 text-xs">{fill.fill_id}</td>
                      <td className="border theme-border p-2 text-xs">{fill.order_id}</td>
                      <td className="border theme-border p-2">{fill.product_id}</td>
                      <td className="border theme-border p-2">${fmtNum(fill.price)}</td>
                      <td className="border theme-border p-2">{fmtNum(fill.size, 6)}</td>
                      <td className="border theme-border p-2">${fmtNum(fill.fee, 4)}</td>
                      <td className="border theme-border p-2">{fill.liquidity_indicator || 'N/A'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* PnL & Slippage Tab */}
      {activeTab === 'pnl' && (
        <div className="space-y-6">
          {/* PnL Summary */}
          {pnlData && (
            <div className="p-4 theme-surface border theme-border rounded">
              <h2 className="text-xl font-semibold mb-4 theme-text">PnL Summary</h2>
              <div className="grid grid-cols-3 gap-4 mb-4">
                <div className="p-3 theme-bg rounded">
                  <p className="text-sm theme-text-secondary">Realized PnL</p>
                  <p className="text-2xl font-bold theme-text">${fmtNum(pnlData.realized_pnl)}</p>
                </div>
                <div className="p-3 theme-bg rounded">
                  <p className="text-sm theme-text-secondary">Unrealized PnL</p>
                  <p className="text-2xl font-bold theme-text">${fmtNum(pnlData.unrealized_pnl)}</p>
                </div>
                <div className="p-3 theme-bg rounded">
                  <p className="text-sm theme-text-secondary">Total PnL</p>
                  <p className="text-2xl font-bold theme-text">${fmtNum(pnlData.total_pnl)}</p>
                </div>
              </div>
              {pnlData.pnl_over_time && pnlData.pnl_over_time.length > 0 && (
                <ResponsiveContainer width="100%" height={300}>
                  <LineChart data={pnlData.pnl_over_time}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="ts" />
                    <YAxis />
                    <Tooltip />
                    <Legend />
                    <Line type="monotone" dataKey="realized" stroke="#737373" name="Realized PnL" />
                    <Line type="monotone" dataKey="unrealized" stroke="#a3a3a3" name="Unrealized PnL" />
                    <Line type="monotone" dataKey="total" stroke="#525252" name="Total PnL" />
                  </LineChart>
                </ResponsiveContainer>
              )}
            </div>
          )}

          {/* Slippage Analysis */}
          {slippageData && (
            <div className="p-4 theme-surface border theme-border rounded">
              <h2 className="text-xl font-semibold mb-4 theme-text">Slippage Analysis</h2>
              {slippageData.summary && (
                <div className="mb-4">
                  <p>Avg Slippage: {fmtNum(slippageData.summary.avg_slippage_bps)} bps</p>
                  <p>Max Slippage: {fmtNum(slippageData.summary.max_slippage_bps)} bps</p>
                  <p>Min Slippage: {fmtNum(slippageData.summary.min_slippage_bps)} bps</p>
                </div>
              )}
              {slippageData.distribution && (
                <ResponsiveContainer width="100%" height={300}>
                  <BarChart data={slippageData.distribution.bins.map((bin: number, idx: number) => ({
                    bin: `${bin}-${slippageData.distribution.bins[idx + 1] || 'inf'}`,
                    count: slippageData.distribution.counts[idx] || 0
                  }))}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="bin" />
                    <YAxis />
                    <Tooltip />
                    <Legend />
                    <Bar dataKey="count" fill="#737373" name="Orders in Bin" />
                  </BarChart>
                </ResponsiveContainer>
              )}
            </div>
          )}
        </div>
      )}

      {/* Evals Tab */}
      {activeTab === 'evals' && (
        <div className="space-y-6">
          <div className="p-4 theme-elevated border theme-border rounded-xl">
            <h2 className="text-xl font-semibold mb-4 theme-text">Evaluation Results</h2>
            {runEvals.length === 0 ? (
              <p className="theme-text-secondary">No evaluations found for this run. Evals are emitted during trade execution.</p>
            ) : (
              <div className="space-y-2">
                {runEvals.map((ev: any, idx: number) => {
                  const score = typeof ev.score === 'number' ? ev.score : 0;
                  const pass = score >= 0.5;
                  const pct = Math.max(0, Math.min(100, score * 100));
                  const barColor = score >= 0.9 ? 'bg-neutral-400' : score >= 0.7 ? 'bg-neutral-500' : score >= 0.5 ? 'bg-neutral-600' : 'bg-neutral-700';
                  return (
                    <div key={idx} className="p-3 theme-surface border theme-border rounded-lg">
                      <div className="flex items-center gap-3 mb-2">
                        <span className={`w-2.5 h-2.5 rounded-full ${pass ? 'bg-[var(--color-status-success)]' : 'bg-[var(--color-status-error)]'}`} />
                        <span className="text-sm font-medium theme-text">
                          {safeStr(ev.eval_name).replace(/_/g, ' ') || '\u2014'}
                        </span>
                        {ev.category != null && safeStr(ev.category) && (
                          <span className="text-xs px-2 py-0.5 theme-elevated theme-text-secondary rounded">
                            {safeStr(ev.category)}
                          </span>
                        )}
                        <span className="text-xs theme-text-secondary ml-auto font-mono">
                          {score.toFixed(3)}
                        </span>
                      </div>
                      <div className="w-full h-1.5 bg-neutral-200 dark:bg-neutral-700 rounded-full">
                        <div className={`h-1.5 rounded-full ${barColor}`} style={{ width: `${pct}%` }} />
                      </div>
                      {ev.reasons && ev.reasons.length > 0 && (
                        <ul className="mt-2 text-xs theme-text-secondary space-y-0.5 ml-5">
                          {ev.reasons.slice(0, 3).map((r: unknown, ri: number) => (
                            <li key={ri}>{safeStr(r)}</li>
                          ))}
                        </ul>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </div>
      )}

      {/* Charts Tab */}
      {activeTab === 'charts' && (
        <div className="space-y-6">
          <div className="p-4 theme-surface border theme-border rounded">
            <h2 className="text-xl font-semibold mb-4 theme-text">Portfolio Value Over Time</h2>
            {portfolioData.length > 0 ? (
              <ResponsiveContainer width="100%" height={400}>
                <LineChart data={portfolioData}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="ts" />
                  <YAxis />
                  <Tooltip />
                  <Legend />
                  <Line type="monotone" dataKey="total_value_usd" stroke="#737373" name="Total Value" />
                  <Line type="monotone" dataKey="cash_usd" stroke="#a3a3a3" name="Cash" />
                </LineChart>
              </ResponsiveContainer>
            ) : (
              <p className="theme-text-secondary">No portfolio data yet</p>
            )}
          </div>

          {rankings.length > 0 && (
            <div className="p-4 theme-surface border theme-border rounded">
              <h2 className="text-xl font-semibold mb-4 theme-text">Asset Returns Comparison</h2>
              <ResponsiveContainer width="100%" height={300}>
                <BarChart data={rankings.slice(0, 5)}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="symbol" />
                  <YAxis />
                  <Tooltip />
                  <Legend />
                  <Bar dataKey="score" fill="#737373" name="Return Score" />
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}

          <div className="grid grid-cols-2 gap-4">
            <div>
              <h2 className="text-xl font-semibold mb-2">Nodes</h2>
              <ul className="list-disc pl-5">
                {detail.nodes.map((node: any) => (
                  <li key={node.node_id}>
                    {node.name}: {node.status}
                  </li>
                ))}
              </ul>
            </div>
            <div>
              <h2 className="text-xl font-semibold mb-2">Orders</h2>
              <ul className="list-disc pl-5">
                {detail.orders.map((order: any) => (
                  <li key={order.order_id}>
                    {order.symbol} {order.side} ${fmtNum(order.notional_usd)} - {order.status}
                  </li>
                ))}
              </ul>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
