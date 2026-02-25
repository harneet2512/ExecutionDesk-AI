'use client';

import { useEffect, useState, useRef } from 'react';
import { useParams } from 'next/navigation';
import { getRunDetail, getRunStatus, getPortfolioValueOverTime, approve, deny, getTrace, fetchEvalRunDetail, type EvalDetail } from '@/lib/api';
import RunCharts from '@/components/RunCharts';
import RunCopilot from '@/components/RunCopilot';
import { LineChart, Line, BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from 'recharts';

const fmtNum = (v: any, digits = 2) => (typeof v === 'number' && isFinite(v) ? v.toFixed(digits) : '\u2014');

/** Coerce any API-origin value to string for safe React rendering. */
function safeStr(v: unknown): string {
  if (typeof v === 'string') return v;
  if (typeof v === 'number' && isFinite(v)) return String(v);
  if (v != null && typeof v === 'object') return JSON.stringify(v);
  return '';
}

function evalOneLineWhat(ev: EvalDetail): string {
  return ev.definition?.description || 'Measures run quality for this criterion.';
}

function evalOneLineThreshold(ev: EvalDetail): string {
  if (typeof ev.definition?.threshold === 'number' && isFinite(ev.definition.threshold)) {
    return `Default threshold: ${(ev.definition.threshold * 100).toFixed(0)}%`;
  }
  return 'Default threshold: N/A';
}

function evalOneLineWhy(ev: EvalDetail): string {
  if (Array.isArray(ev.reasons) && ev.reasons.length > 0) return safeStr(ev.reasons[0]);
  return 'Helps validate decision quality and production safety.';
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
  const [runEvals, setRunEvals] = useState<EvalDetail[]>([]);
  const [evalsLoading, setEvalsLoading] = useState(false);
  const [expandedEvalKey, setExpandedEvalKey] = useState<string | null>(null);
  const [evalSearch, setEvalSearch] = useState('');
  const eventSourceRef = useRef<EventSource | null>(null);
  const terminalRef = useRef(false);

  // Full data load - only on initial mount and when status transitions to terminal
  async function loadDataFull() {
    try {
      const [runDetail, portfolio, traceData, pnl, slippage] = await Promise.all([
        getRunDetail(runId),
        getPortfolioValueOverTime(runId).catch(() => []),
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
      // Use approvals from run detail response — no separate /approvals endpoint needed
      const pendingApprovals = runDetail.approvals || [];
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
    <div className="p-8 pb-10 max-w-7xl mx-auto min-h-0">
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
        <span>Status: <span className={`font-medium ${detail.run.status === 'COMPLETED' ? 'text-[var(--color-status-success)]' : detail.run.status === 'FAILED' ? 'text-[var(--color-status-error)]' : 'theme-text'}`}>{detail.run.status}</span>
          {detail.run.status === 'COMPLETED' &&
           detail.orders?.some((o: any) =>
             !['FILLED','FAILED','REJECTED','CANCELED','EXPIRED','TIMEOUT'].includes((o.status||'').toUpperCase())
           ) && (
            <span className="text-xs text-[var(--color-status-warning)] ml-1">(fill pending)</span>
          )}
        </span>
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

      {/* Run Copilot Panel */}
      <RunCopilot
        runId={runId}
        run={detail.run}
        orders={detail.orders || []}
        evals={runEvals}
        traceArtifacts={trace?.artifacts}
      />

      {/* Tabs */}
      <div className="flex gap-2 mb-6 border-b theme-border">
        <button
          data-testid="run-tab-timeline"
          onClick={() => setActiveTab('timeline')}
          className={`px-4 py-2 ${activeTab === 'timeline' ? 'border-b-2 border-neutral-800 dark:border-neutral-200' : ''}`}
        >
          Execution Trace
        </button>
        <button
          data-testid="run-tab-evidence"
          onClick={() => setActiveTab('evidence')}
          className={`px-4 py-2 ${activeTab === 'evidence' ? 'border-b-2 border-neutral-800 dark:border-neutral-200' : ''}`}
        >
          Evidence
        </button>
        <button
          data-testid="run-tab-orders"
          onClick={() => setActiveTab('orders')}
          className={`px-4 py-2 ${activeTab === 'orders' ? 'border-b-2 border-neutral-800 dark:border-neutral-200' : ''}`}
        >
          Orders & Fills
        </button>
        <button
          data-testid="run-tab-pnl"
          onClick={() => setActiveTab('pnl')}
          className={`px-4 py-2 ${activeTab === 'pnl' ? 'border-b-2 border-neutral-800 dark:border-neutral-200' : ''}`}
        >
          PnL & Slippage
        </button>
        <button
          data-testid="run-tab-charts"
          onClick={() => setActiveTab('charts')}
          className={`px-4 py-2 ${activeTab === 'charts' ? 'border-b-2 border-neutral-800 dark:border-neutral-200' : ''}`}
        >
          Charts
        </button>
        <button
          data-testid="run-tab-evals"
          onClick={() => {
            setActiveTab('evals');
            // Load evals on first click
            if (runEvals.length === 0) {
              setEvalsLoading(true);
              fetchEvalRunDetail(runId)
                .then((data) => {
                  const all: EvalDetail[] = [];
                  const cats = (data ?? {}).categories ?? {};
                  for (const category of Object.values(cats)) {
                    if (Array.isArray(category.evals)) all.push(...category.evals);
                  }
                  setRunEvals(all);
                })
                .catch(() => setRunEvals([]))
                .finally(() => setEvalsLoading(false));
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
            {(trace?.plan || trace?.trade_plan) ? (
              <div className="p-4 theme-bg rounded theme-text space-y-1">
                <p><strong>Strategy:</strong>{' '}
                  {trace?.plan?.strategy_spec?.strategy_name || trace?.trade_plan?.strategy || 'user_direct'}
                </p>
                <p><strong>Metric:</strong>{' '}
                  {trace?.plan?.strategy_spec?.metric || trace?.trade_plan?.metric || 'trade_plan metric not set'}
                </p>
                <p><strong>Window:</strong>{' '}
                  {trace?.plan?.strategy_spec?.window || trace?.trade_plan?.window?.label || 'spot'}
                </p>
                {(trace?.plan?.selected_asset || trace?.trade_plan?.selected_asset) && (
                  <p><strong>Selected Asset:</strong>{' '}
                    {trace?.plan?.selected_asset || trace?.trade_plan?.selected_asset}
                  </p>
                )}
                {trace?.trade_plan?.rationale && (
                  <p className="text-sm theme-text-secondary mt-2">{trace.trade_plan.rationale}</p>
                )}
              </div>
            ) : (
              <div className="p-4 theme-bg rounded theme-text-secondary text-sm space-y-1">
                {trace?.trade_plan?.unavailable_reason ? (
                  <p>Plan unavailable: {trace.trade_plan.unavailable_reason === 'analyze_only'
                    ? 'This was an ANALYZE-only run (no trade planned).'
                    : trace.trade_plan.unavailable_reason === 'run_failed_before_proposal'
                    ? `Run failed before proposal stage${trace.trade_plan.stage_failed ? ` (failed at: ${trace.trade_plan.stage_failed})` : ''}.`
                    : trace.trade_plan.unavailable_reason}</p>
                ) : (
                  <p>Plan Summary: trade_plan artifact was not emitted. The run may not have reached proposal stage, or it was an ANALYZE-only run.</p>
                )}
              </div>
            )}
          </div>
        </div>
      )}

      {/* Evidence Tab */}
      {activeTab === 'evidence' && (
        <div className="space-y-6">
          <div className="text-xs theme-text-secondary">
            Lookback: {safeStr(trace?.artifacts?.rankings_meta?.lookback_window || trace?.plan?.strategy_spec?.window || 'N/A')}; Universe: {(trace?.artifacts?.rankings_meta?.universe_count ?? rankings.length) || 0} symbols; Candles batches: {candlesBatches.length || 0}
          </div>
          {rankings.length === 0 && candlesBatches.length === 0 && toolCalls.length === 0 && (
            <div className="p-4 theme-surface border theme-border rounded text-sm theme-text-secondary">
              No rankings or candle evidence is available for this run yet. This usually means the research node did not emit artifacts. Next step: open Execution Trace and verify research node outputs.
            </div>
          )}
          {/* Rankings */}
          {rankings.length > 0 && (
            <div className="p-4 theme-surface border theme-border rounded">
              <h2 className="text-xl font-semibold mb-4 theme-text">Asset Rankings</h2>
              <div className="overflow-x-auto">
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
                      <td className="border theme-border p-2 theme-text">
                        {typeof rank.first_price === 'number' ? `$${fmtNum(rank.first_price)}` : <span title={safeStr(rank.first_price_reason || 'First price unavailable from candle history')}>Unavailable</span>}
                      </td>
                      <td className="border theme-border p-2 theme-text">
                        {typeof rank.last_price === 'number' ? `$${fmtNum(rank.last_price)}` : <span title={safeStr(rank.last_price_reason || 'Last price unavailable from candle history')}>Unavailable</span>}
                      </td>
                      <td className="border theme-border p-2 theme-text" title={safeStr(rank.return_reason || '')}>{typeof rank.first_price === 'number' && typeof rank.last_price === 'number' && rank.first_price !== 0
                        ? ((rank.last_price - rank.first_price) / rank.first_price * 100).toFixed(2) + '%'
                        : 'Unavailable'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              </div>
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
                    <td className="border theme-border p-2">
                      {(() => {
                        const s = (order.status || '').toUpperCase();
                        if (s === 'FILLED') return <span className="text-[var(--color-status-success)] font-medium">Filled ✓</span>;
                        if (s === 'FAILED') return <span className="text-[var(--color-status-error)] font-medium">Failed ✗</span>;
                        if (s === 'REJECTED') return <span className="text-[var(--color-status-error)] font-medium">Rejected ✗</span>;
                        if (s === 'CANCELED' || s === 'EXPIRED') return <span className="text-[var(--color-status-error)] font-medium">{order.status}</span>;
                        if (s === 'SUBMITTED') return <span className="text-[var(--color-status-warning)] font-medium">Submitted (at venue)</span>;
                        if (s === 'PENDING_FILL') return <span className="text-[var(--color-status-warning)] font-medium">Pending fill</span>;
                        if (s === 'PARTIALLY_FILLED') return <span className="text-[var(--color-status-warning)] font-medium">Partially filled</span>;
                        return <span className="theme-text-secondary">{order.status}</span>;
                      })()}
                    </td>
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
              <p className="theme-text-muted text-sm italic">
                Orders: {detail.orders.length} submitted. Fills appear after exchange matching (typically under ~5s in PAPER mode; variable in LIVE mode). This page refreshes run status every 5 seconds.
              </p>
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
          {!pnlData && !slippageData && (
            <div className="p-4 theme-surface border theme-border rounded text-sm theme-text-secondary">
              PnL data is unavailable for this run. PnL is computed from fills and latest prices. Next step: verify at least one fill exists, then refresh.
            </div>
          )}
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
        <div className="flex flex-col" style={{ height: 'calc(100vh - 260px)', minHeight: 480 }}>
          <div className="flex flex-col h-full p-4 theme-elevated border theme-border rounded-xl overflow-hidden">
            {/* Sticky header + search */}
            <div className="flex-shrink-0 pb-3 border-b theme-border">
              <div className="flex items-center justify-between gap-3">
                <h2 className="text-xl font-semibold theme-text">Evaluation Results</h2>
                {runEvals.length > 0 && (
                  <span className="text-xs theme-text-secondary">
                    {runEvals.filter((ev: any) => (typeof ev.score === 'number' ? ev.score : 0) >= 0.5).length}/{runEvals.length} passed
                  </span>
                )}
              </div>
              {runEvals.length > 3 && (
                <input
                  type="search"
                  placeholder="Filter evals by name or category..."
                  value={evalSearch}
                  onChange={e => setEvalSearch(e.target.value)}
                  className="mt-2 w-full px-3 py-1.5 text-sm theme-surface border theme-border rounded-lg theme-text placeholder:theme-text-secondary focus:outline-none focus:ring-1 focus:ring-[var(--color-accent,#6366f1)]"
                />
              )}
            </div>

            {/* Scrollable eval list */}
            <div className="flex-1 min-h-0 overflow-y-auto pt-3 pr-1">
              {evalsLoading ? (
                <p className="theme-text-secondary text-sm">Loading eval explainability...</p>
              ) : runEvals.length === 0 ? (
                <p className="theme-text-secondary text-sm">No evaluations found for this run. Evals are emitted during trade execution.</p>
              ) : (() => {
                const searchLow = evalSearch.trim().toLowerCase();
                const filtered = searchLow
                  ? runEvals.filter((ev: any) =>
                      (ev.eval_name || '').toLowerCase().includes(searchLow) ||
                      (ev.category || '').toLowerCase().includes(searchLow) ||
                      (ev.definition?.description || '').toLowerCase().includes(searchLow)
                    )
                  : runEvals;
                if (filtered.length === 0) {
                  return <p className="text-sm theme-text-secondary">No evals match &ldquo;{evalSearch}&rdquo;.</p>;
                }
                return (
                  <div data-testid="run-evals-list" className="space-y-2">
                    {filtered.map((ev: any, idx: number) => {
                      const rawScore = ev.score;
                      const isNA = rawScore == null || (typeof rawScore === 'number' && rawScore < 0) ||
                        (Array.isArray(ev.reasons) && ev.reasons.some((r: unknown) => typeof r === 'string' && (r.startsWith('N/A:') || r.includes('deferred'))));
                      const score = isNA ? 0 : (typeof rawScore === 'number' ? rawScore : 0);
                      const pass = !isNA && score >= 0.5;
                      const pct = isNA ? 0 : Math.max(0, Math.min(100, score * 100));
                      const barColor = isNA ? 'bg-neutral-500' : score >= 0.9 ? 'bg-neutral-400' : score >= 0.7 ? 'bg-neutral-500' : score >= 0.5 ? 'bg-neutral-600' : 'bg-neutral-700';
                      const key = `${safeStr(ev.eval_name)}-${idx}`;
                      const isOpen = expandedEvalKey === key;
                      return (
                        <div key={idx} className="p-3 theme-surface border theme-border rounded-lg">
                          <div className="flex items-center gap-3 mb-2">
                            {isNA
                              ? <span className="w-2.5 h-2.5 rounded-full bg-neutral-500" title="N/A — deferred" />
                              : <span className={`w-2.5 h-2.5 rounded-full ${pass ? 'bg-[var(--color-status-success)]' : 'bg-[var(--color-status-error)]'}`} />
                            }
                            <span className="text-sm font-medium theme-text">
                              {safeStr(ev.eval_name).replace(/_/g, ' ') || '\u2014'}
                            </span>
                            {ev.category != null && safeStr(ev.category) && (
                              <span className="text-xs px-2 py-0.5 theme-elevated theme-text-secondary rounded">
                                {safeStr(ev.category)}
                              </span>
                            )}
                            <span className="text-xs theme-text-secondary ml-auto font-mono">
                              {isNA ? 'N/A' : score.toFixed(3)}
                            </span>
                          </div>
                          <div className="w-full h-1.5 bg-neutral-200 dark:bg-neutral-700 rounded-full">
                            {isNA
                              ? <div className="h-1.5 rounded-full bg-neutral-500 opacity-40" style={{ width: '100%' }} />
                              : <div className={`h-1.5 rounded-full ${barColor}`} style={{ width: `${pct}%` }} />
                            }
                          </div>
                          <div className="mt-2 text-xs space-y-1 theme-text-secondary">
                            <p><strong>What this measures:</strong> {evalOneLineWhat(ev)}</p>
                            <p><strong>{evalOneLineThreshold(ev)}</strong></p>
                            <p><strong>Why it matters:</strong> {evalOneLineWhy(ev)}</p>
                          </div>
                          {ev.reasons && ev.reasons.length > 0 && (
                            <ul className="mt-2 text-xs theme-text-secondary space-y-0.5 ml-5 list-disc">
                              {ev.reasons.slice(0, 3).map((r: unknown, ri: number) => (
                                <li key={ri}>{safeStr(r)}</li>
                              ))}
                            </ul>
                          )}
                          <button
                            data-testid={`eval-view-details-${idx}`}
                            onClick={() => setExpandedEvalKey(isOpen ? null : key)}
                            className="mt-3 text-xs btn-secondary px-2 py-1 rounded"
                          >
                            {isOpen ? 'Hide details' : 'View details'}
                          </button>
                          {isOpen && (
                            <div className="mt-3 p-3 theme-elevated rounded border theme-border text-xs space-y-2">
                              <p><strong>Definition:</strong> {safeStr(ev.definition?.description || 'N/A')}</p>
                              <p><strong>Formula:</strong> {safeStr(ev.definition?.rubric || 'N/A')}</p>
                              <p><strong>Defaults:</strong> threshold={typeof ev.definition?.threshold === 'number' ? ev.definition.threshold : 'N/A'}, evaluator={safeStr(ev.evaluator_type || 'default')}</p>
                              <p><strong>Inputs used:</strong> {ev.details && typeof ev.details === 'object' ? Object.keys(ev.details).join(', ') || 'N/A' : 'N/A'}</p>
                              <p><strong>Data sources:</strong> {safeStr(ev.category || 'eval pipeline artifacts')}</p>
                              <p><strong>Edge cases:</strong> Missing fields are treated as unavailable; evaluator records reasons/fallbacks.</p>
                              <div>
                                <p className="mb-1"><strong>Raw JSON payload</strong></p>
                                <pre data-testid={`eval-raw-json-${idx}`} className="max-h-48 overflow-auto p-2 theme-sunken rounded border theme-border">{JSON.stringify(ev, null, 2)}</pre>
                              </div>
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </div>
                );
              })()}
            </div>
          </div>
        </div>
      )}

      {/* Charts Tab */}
      {activeTab === 'charts' && (
        <div className="space-y-4">
          {/* Single professional chart: Portfolio Value & Trade Markers */}
          <RunCharts runId={runId} />

          {/* Compact node / order summary */}
          <div className="grid grid-cols-2 gap-4 pt-2">
            <div className="p-3 theme-surface border theme-border rounded">
              <h3 className="text-sm font-semibold theme-text mb-2">DAG Nodes</h3>
              <ul className="space-y-1">
                {detail.nodes.map((node: any) => (
                  <li key={node.node_id} className="text-xs flex justify-between theme-text-secondary">
                    <span>{node.name}</span>
                    <span className={node.status === 'COMPLETED' ? 'text-[var(--color-status-success)]' : node.status === 'FAILED' ? 'text-[var(--color-status-error)]' : 'theme-text-secondary'}>
                      {node.status}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
            <div className="p-3 theme-surface border theme-border rounded">
              <h3 className="text-sm font-semibold theme-text mb-2">Orders</h3>
              <ul className="space-y-1">
                {detail.orders.map((order: any) => (
                  <li key={order.order_id} className="text-xs flex justify-between theme-text-secondary">
                    <span>{order.symbol} {order.side} ${fmtNum(order.notional_usd)}</span>
                    <span className={order.status === 'FILLED' ? 'text-[var(--color-status-success)]' : order.status === 'FAILED' || order.status === 'REJECTED' ? 'text-[var(--color-status-error)]' : 'text-[var(--color-status-warning)]'}>
                      {order.status}
                    </span>
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
