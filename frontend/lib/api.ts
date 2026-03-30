export interface Run {
  run_id: string;
  tenant_id: string;
  status: string;
  execution_mode: string;
  created_at: string;
}

export type { Artifact } from './artifacts';

export interface RunDetail {
  run: Run;
  nodes: any[];
  policy_events: any[];
  approvals: any[];
  orders: any[];
  snapshots: any[];
  evals: any[];
  fills?: any[];
}

/** Fetch with exponential backoff + jitter for transient errors.
 *  Retries 429/502/503/504 globally, plus 500 for chat-command endpoint
 *  because dev proxy/backend reloads can produce short-lived ECONNRESET->500. */
async function fetchWithRetry(
  endpoint: string,
  options: RequestInit,
  maxRetries: number = 2
): Promise<Response> {
  let lastErr: any;
  for (let attempt = 0; attempt <= maxRetries; attempt++) {
    try {
      const res = await fetch(endpoint, options);
      const retryableStatus =
        res.status === 429 ||
        res.status === 502 ||
        res.status === 503 ||
        res.status === 504 ||
        (res.status === 500 && endpoint.includes('/api/v1/chat/command'));
      if (retryableStatus && attempt < maxRetries) {
        const retryAfter = Number(res.headers.get('Retry-After')) || 0;
        const backoffMs = retryAfter > 0
          ? retryAfter * 1000
          : Math.min(1000 * Math.pow(2, attempt) + Math.random() * 500, 15000);
        await new Promise(r => setTimeout(r, backoffMs));
        continue;
      }
      return res;
    } catch (networkErr: any) {
      // True network errors (no response received) are retryable
      lastErr = networkErr;
      if (attempt < maxRetries) {
        const backoffMs = Math.min(1000 * Math.pow(2, attempt) + Math.random() * 500, 15000);
        await new Promise(r => setTimeout(r, backoffMs));
        continue;
      }
    }
  }
  throw lastErr || new Error('Request failed after retries');
}

/** Check if DEBUG_UI logging is enabled. */
function isDebugUI(): boolean {
  try {
    return typeof window !== 'undefined' &&
      (process.env.NEXT_PUBLIC_DEBUG_UI === '1' || localStorage.getItem('DEBUG_UI') === '1');
  } catch { return false; }
}

async function apiFetch(endpoint: string, options: RequestInit = {}) {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(options.headers as Record<string, string>),
  };

  if (typeof window !== 'undefined' && !headers['Authorization']) {
    headers['X-Dev-Tenant'] = 't_default';
  }

  const debugEnabled = isDebugUI();
  const method = options.method || 'GET';

  // Log request details
  if (debugEnabled) {
    console.log(`[API REQ] ${method} ${endpoint}`);
    if (options.body && typeof options.body === 'string') {
      try {
        const bodyObj = JSON.parse(options.body);
        console.log(`[API REQ] Body keys: ${Object.keys(bodyObj).join(', ')}`);
      } catch {
        console.log(`[API REQ] Body: (non-JSON)`);
      }
    }
  }

  // Use relative path - Next.js rewrites will handle proxying to backend
  let res: Response;
  try {
    res = await fetchWithRetry(endpoint, { ...options, headers }, 2);
  } catch (networkErr: any) {
    const msg = networkErr?.message || 'Unknown network error';
    const err: any = new Error(`Network error on ${method} ${endpoint}: Could not reach the server. ${msg}`);
    err.statusCode = 0;
    err.isNetworkError = true;
    throw err;
  }

  // Get response as text first for debugging
  const responseText = await res.clone().text();
  // Always extract X-Request-ID from response header (most reliable source)
  const headerRequestId = res.headers.get('X-Request-ID') || '';

  if (debugEnabled) {
    const contentType = res.headers.get('content-type') || 'unknown';
    console.log(`[API RES] ${method} ${endpoint} -> ${res.status} (X-Request-ID: ${headerRequestId})`);
    console.log(`[API RES] Content-Type: ${contentType}`);
    console.log(`[API RES] Body (first 500): ${responseText.substring(0, 500)}`);
  }

  if (!res.ok) {
    // Try to parse error message from response
    let errorMessage = res.statusText || 'Request failed';
    let requestId = headerRequestId;
    let retryAfterSeconds = 0;
    let errorCode = '';
    try {
      const errorData = JSON.parse(responseText);
      // Handle global exception handler shape: {error: {code, message, request_id}}
      if (errorData.error && typeof errorData.error === 'object') {
        errorMessage = errorData.error.message || errorMessage;
        requestId = requestId || errorData.error.request_id || '';
        errorCode = errorData.error.error_code || errorData.error.code || '';
      }
      // Handle FastAPI detail shape: {detail: "..."}
      const detail = errorData.detail;
      if (typeof detail === 'string') {
        errorMessage = detail;
      } else if (detail && typeof detail === 'object') {
        errorMessage = detail.message || detail.error?.message || JSON.stringify(detail);
        requestId = requestId || detail.request_id || detail.error?.request_id || '';
        if (!errorCode) {
          errorCode = detail.error?.error_code || detail.error?.code || detail.error_code || '';
        }
      }
      // Handle chat error shape: {content: "...", status: "FAILED"}
      if (errorData.content && errorData.status === 'FAILED') {
        errorMessage = errorData.content;
      }
      if (!errorMessage || errorMessage === res.statusText) {
        errorMessage = errorData.message || res.statusText || 'Request failed';
      }
      // Ensure errorMessage is never empty
      if (!errorMessage) errorMessage = 'Unknown error';
      if (errorData.request_id) requestId = requestId || errorData.request_id;
      if (errorData.retry_after_seconds) {
        retryAfterSeconds = Number(errorData.retry_after_seconds) || 0;
      }
    } catch {
      // Response not JSON - use raw text snippet
      errorMessage = responseText.substring(0, 200) || res.statusText || 'Request failed';
    }

    // 429 Rate Limited: extract Retry-After from header as fallback
    if (res.status === 429 && !retryAfterSeconds) {
      const hdrRetry = res.headers.get('Retry-After');
      if (hdrRetry) retryAfterSeconds = Number(hdrRetry) || 60;
      else retryAfterSeconds = 60;
    }

    if (debugEnabled) {
      console.error(`[API ERR] ${method} ${endpoint} ${res.status} ${errorCode || 'UNKNOWN'}: ${errorMessage}${requestId ? ` (req_id: ${requestId})` : ''}${retryAfterSeconds ? ` retry_after=${retryAfterSeconds}s` : ''}`);
    }
    const errMsg = requestId
      ? `API error ${res.status}: ${errorMessage} (Request ID: ${requestId})`
      : `API error ${res.status}: ${errorMessage}`;
    // Extract remediation from error envelope
    let remediation = '';
    try {
      const errorData2 = JSON.parse(responseText);
      remediation = errorData2?.error?.remediation || errorData2?.detail?.error?.remediation || '';
    } catch { /* ignore */ }

    const err: any = new Error(errMsg);
    err.statusCode = res.status;
    err.requestId = requestId;
    err.errorCode = errorCode;
    err.retryAfterSeconds = retryAfterSeconds;
    err.remediation = remediation;
    err.endpoint = `${method} ${endpoint}`;
    err.toJSON = () => ({
      message: errMsg,
      statusCode: res.status,
      requestId,
      errorCode,
      retryAfterSeconds,
      remediation,
      endpoint: `${method} ${endpoint}`,
    });
    throw err;
  }

  // Defensive JSON parsing for 200 responses
  try {
    return JSON.parse(responseText);
  } catch {
    // 200 response but non-JSON body (e.g., proxy error, empty response)
    if (debugEnabled) {
      console.warn(`[API WARN] 200 response but non-JSON body on ${endpoint}: ${responseText.substring(0, 200)}`);
    }
    return { content: responseText || 'Empty response', status: 'COMPLETED' };
  }
}

export interface HealthStatus {
  ok: boolean;
  db_ok: boolean;
  schema_ok: boolean;
  message: string;
  migrations_applied: number;
  migrations_pending: number;
  pending_list: string[];
  db_path?: string;
  current_version?: number;
  required_version?: number;
  migrate_cmd?: string;
  config?: {
    enable_live_trading?: boolean;
    trading_disable_live?: boolean;
    live_execution_allowed?: boolean;
    execution_mode_default?: string;
    market_data_mode?: string;
    live_max_notional_usd?: number;
  };
}

/** Non-throwing health check. Returns null on network error. */
export async function checkHealth(): Promise<HealthStatus | null> {
  try {
    const res = await fetch('/api/v1/ops/health', {
      headers: { 'Content-Type': 'application/json', 'X-Dev-Tenant': 't_default' },
    });
    if (!res.ok) return null;
    return await res.json();
  } catch {
    return null;
  }
}

export interface Capabilities {
  live_trading_enabled: boolean;
  paper_trading_enabled: boolean;
  insights_enabled: boolean;
  news_enabled: boolean;
  db_ready: boolean;
  migrations_needed?: boolean;
  remediation?: string | null;
  news_provider_status?: string;
  market_data_provider?: string;
  version?: string;
}

/** Non-throwing capabilities fetch. Returns null on error. */
export async function fetchCapabilities(): Promise<Capabilities | null> {
  try {
    const res = await fetch('/api/v1/ops/capabilities', {
      headers: { 'Content-Type': 'application/json', 'X-Dev-Tenant': 't_default' },
    });
    if (!res.ok) return null;
    return await res.json();
  } catch {
    return null;
  }
}

export async function triggerRun(execution_mode: string = "PAPER"): Promise<Run> {
  return apiFetch('/api/v1/runs/trigger', {
    method: 'POST',
    body: JSON.stringify({ execution_mode }),
  });
}

export async function listRuns(): Promise<Run[]> {
  return apiFetch('/api/v1/runs');
}

export async function getRunStatus(runId: string): Promise<any> {
  return apiFetch('/api/v1/runs/status/' + runId);
}

/** Non-throwing status fetch for polling. Returns null on any error.
 *  Uses raw fetch() to avoid apiFetch throw which triggers Next.js dev error overlay. */
export async function getRunStatusSafe(runId: string): Promise<any | null> {
  try {
    const res = await fetch('/api/v1/runs/status/' + runId, {
      headers: { 'Content-Type': 'application/json', 'X-Dev-Tenant': 't_default' },
    });
    if (!res.ok) return null;
    return await res.json();
  } catch {
    return null;
  }
}

/** Safe fetch for display components. Returns null on any error.
 *  Injects X-Dev-Tenant header and uses fetchWithRetry (1 retry). */
export async function apiFetchSafe(endpoint: string): Promise<any | null> {
  try {
    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
      'X-Dev-Tenant': 't_default',
    };
    const res = await fetchWithRetry(endpoint, { headers }, 1);
    if (!res.ok) return null;
    return await res.json();
  } catch {
    return null;
  }
}

export async function getRunDetail(runId: string): Promise<RunDetail> {
  return apiFetch('/api/v1/runs/' + runId);
}

export async function getPortfolioValueOverTime(runId?: string): Promise<any[]> {
  const url = '/api/v1/portfolio/metrics/value-over-time' + (runId ? '?run_id=' + runId : '');
  return apiFetch(url);
}

export async function getOpsMetrics(): Promise<any> {
  return apiFetch('/api/v1/ops/metrics');
}

export async function listApprovals(): Promise<any[]> {
  // Approvals are embedded in the run detail response; this stub avoids 404 spam.
  return [];
}

export async function approve(approvalId: string, comment: string = ""): Promise<any> {
  return apiFetch('/api/v1/approvals/' + approvalId + '/decision', {
    method: 'POST',
    body: JSON.stringify({ decision: 'APPROVED', comment }),
  });
}

export async function deny(approvalId: string, comment: string = ""): Promise<any> {
  return apiFetch('/api/v1/approvals/' + approvalId + '/decision', {
    method: 'POST',
    body: JSON.stringify({ decision: 'REJECTED', comment }),
  });
}

export async function executeCommand(text: string, options: {
  execution_mode?: string;
  budget_usd?: number;
  window?: string;
  metric?: string;
} = {}): Promise<CommandResponse> {
  return apiFetch('/api/v1/agent/command', {
    method: 'POST',
    body: JSON.stringify({
      text,
      execution_mode: options.execution_mode || 'PAPER',
      budget_usd: options.budget_usd || 10.0,
      window: options.window || '24h',
      metric: options.metric || 'return',
    }),
  });
}

export interface CommandResponse {
  run_id: string;
  parsed_intent: any;
  selected_asset?: string;
  selected_order?: any;
  decision_trace: any[];
}

export async function executeCommandText(command: string, execution_mode: string = "PAPER", source_run_id?: string): Promise<any> {
  return apiFetch('/api/v1/commands/execute', {
    method: 'POST',
    body: JSON.stringify({ command, execution_mode, source_run_id }),
  });
}

export async function getTrace(runId: string): Promise<any> {
  return apiFetch('/api/v1/runs/' + runId + '/trace');
}

export async function getPerformance(window: string = "7d"): Promise<any> {
  return apiFetch('/api/v1/analytics/performance?window=' + window);
}

export async function executeChatCommand(
  text: string,
  conversationId?: string,
  newsEnabled?: boolean
): Promise<any> {
  return apiFetch('/api/v1/chat/command', {
    method: 'POST',
    body: JSON.stringify({
      text,
      conversation_id: conversationId,
      news_enabled: newsEnabled
    }),
  });
}

// Trade Tickets API (ASSISTED_LIVE for stocks)
export interface TradeTicket {
  ticket_id: string;
  run_id: string;
  tenant_id: string;
  symbol: string;
  side: 'BUY' | 'SELL';
  notional_usd: number;
  est_qty?: number;
  suggested_limit?: number;
  tif?: string;
  status: string;
  asset_class: string;
  created_at: string;
  expires_at?: string;
  receipt_json?: any;
}

export async function getTicketByRunId(runId: string): Promise<TradeTicket | null> {
  try {
    return await apiFetch('/api/v1/trade_tickets/by-run/' + runId);
  } catch {
    return null;
  }
}

export async function getTicket(ticketId: string): Promise<TradeTicket> {
  return apiFetch('/api/v1/trade_tickets/' + ticketId);
}

export async function listPendingTickets(): Promise<TradeTicket[]> {
  return apiFetch('/api/v1/trade_tickets/');
}

export async function submitTicketReceipt(
  ticketId: string,
  receipt: object
): Promise<{ status: string; message: string }> {
  return apiFetch('/api/v1/trade_tickets/' + ticketId + '/receipt', {
    method: 'POST',
    body: JSON.stringify({ receipt_json: receipt }),
  });
}

export async function cancelTicket(
  ticketId: string
): Promise<{ status: string; message: string }> {
  return apiFetch('/api/v1/trade_tickets/' + ticketId + '/cancel', {
    method: 'POST',
    body: JSON.stringify({}),
  });
}

// Conversations
export interface Conversation {
  conversation_id: string;
  tenant_id: string;
  title: string | null;
  created_at: string;
  updated_at: string;
  last_message_at?: string | null;
}

export interface Message {
  message_id: string;
  conversation_id: string;
  role: 'user' | 'assistant';
  content: string;
  run_id?: string | null;
  metadata_json?: any;
  created_at: string;
}

export async function listConversations(): Promise<Conversation[]> {
  return apiFetch('/api/v1/conversations');
}

export async function createConversation(title?: string): Promise<{ conversation_id: string; title: string | null; created_at: string }> {
  return apiFetch('/api/v1/conversations', {
    method: 'POST',
    body: JSON.stringify({ title }),
  });
}

export async function getConversation(conversationId: string): Promise<Conversation> {
  return apiFetch('/api/v1/conversations/' + conversationId);
}

export async function listMessages(conversationId: string): Promise<Message[]> {
  return apiFetch('/api/v1/conversations/' + conversationId + '/messages');
}

export async function createMessage(
  conversationId: string,
  content: string,
  role: 'user' | 'assistant' = 'user',
  runId?: string,
  metadata?: any
): Promise<{ message_id: string; conversation_id: string; created_at: string }> {
  return apiFetch('/api/v1/conversations/' + conversationId + '/messages', {
    method: 'POST',
    body: JSON.stringify({ content, role, run_id: runId, metadata_json: metadata }),
  });
}

export async function deleteConversation(conversationId: string): Promise<{ deleted: boolean; conversation_id: string }> {
  return apiFetch('/api/v1/conversations/' + conversationId, {
    method: 'DELETE',
  });
}

export interface RunTelemetry {
  run_id: string;
  tenant_id: string;
  started_at?: string | null;
  ended_at?: string | null;
  duration_ms?: number | null;
  tool_calls_count: number;
  sse_events_count: number;
  error_count: number;
  last_error?: string | null;
  tokens_in?: number | null;
  tokens_out?: number | null;
  trace_id?: string | null;
  created_at: string;
  updated_at: string;
}

export async function listRunTelemetry(): Promise<RunTelemetry[]> {
  return apiFetch('/api/v1/telemetry/runs');
}

export async function getRunTelemetry(runId: string): Promise<RunTelemetry> {
  return apiFetch('/api/v1/telemetry/runs/' + runId);
}

export async function confirmTrade(confirmationId: string): Promise<any> {
  if (!confirmationId || confirmationId === 'undefined' || confirmationId === 'null') {
    console.error('[API] confirmTrade called with invalid ID:', confirmationId);
    throw new Error('Invalid confirmation ID: ' + confirmationId);
  }
  const url = '/api/v1/confirmations/' + confirmationId + '/confirm';
  console.log('[API] confirmTrade calling:', { confirmationId, url });

  try {
    const result = await apiFetch(url, {
      method: 'POST',
      body: JSON.stringify({}),
    });
    console.log('[API] confirmTrade success:', result);
    return result;
  } catch (e: any) {
    console.error('[API] confirmTrade FAILED:', {
      confirmationId,
      url,
      statusCode: e.statusCode ?? 'unknown',
      requestId: e.requestId ?? 'unknown',
      errorCode: e.errorCode ?? 'unknown',
      message: e.message ?? String(e),
    });
    throw e;
  }
}

export async function cancelTrade(confirmationId: string): Promise<any> {
  if (!confirmationId || confirmationId === 'undefined' || confirmationId === 'null') {
    console.error('[API] cancelTrade called with invalid ID:', confirmationId);
    throw new Error('Invalid confirmation ID: ' + confirmationId);
  }
  return apiFetch('/api/v1/confirmations/' + confirmationId + '/cancel', {
    method: 'POST',
    body: JSON.stringify({}),
  });
}

/** Get confirmation status for recovery after network errors. */
export async function getConfirmationStatus(confirmationId: string): Promise<{
  confirmation_id: string;
  status: string;
  executed: boolean;
  order_id: string | null;
  order_status: string;
  run_id: string | null;
  request_id: string;
}> {
  return apiFetch('/api/v1/confirmations/' + confirmationId + '/status');
}

// Eval Dashboard API
export interface EvalDashboard {
  total_runs_evaluated: number;
  overall_avg_score: number;
  overall_grade: string;
  category_scores: Record<string, {
    avg_score: number;
    min_score: number | null;
    max_score: number | null;
    eval_count: number;
    pass_rate: number;
    grade: string;
  }>;
  grade_distribution: Record<string, number>;
  recent_runs: EvalRunSummary[];
}

export interface EvalRunSummary {
  run_id: string;
  status: string;
  mode: string;
  created_at: string;
  command: string | null;
  eval_count: number;
  avg_score: number;
  grade: string;
  passed: number;
  failed: number;
}

export interface EvalDefinition {
  title: string;
  description: string;
  category: string;
  rubric: string;
  how_to_improve: string[];
  threshold: number;
  evaluator_type: string;
}

export interface EvalDetail {
  eval_id?: string;
  eval_name: string;
  score: number;
  reasons: string[];
  evaluator_type: string;
  thresholds: Record<string, any>;
  details: any;
  definition?: EvalDefinition | null;
  category: string;
  pass: boolean;
  ts?: string;
  /** LLM or rule-generated explanation text (stored after POST explain). */
  explanation?: string | null;
  /** 'rules' | 'llm' */
  explanation_source?: string | null;
}

export interface EvalRunDetail {
  run: {
    run_id: string;
    command: string | null;
    mode: string;
    status: string;
    created_at: string;
  };
  summary: {
    total_evals: number;
    avg_score: number;
    grade: string;
    passed: number;
    failed: number;
  };
  categories: Record<string, {
    avg_score: number;
    grade: string;
    total: number;
    passed: number;
    failed: number;
    evals: EvalDetail[];
  }>;
}

export async function fetchEvalDashboard(): Promise<EvalDashboard> {
  return apiFetch('/api/v1/evals/dashboard');
}

export async function fetchEvalRuns(limit: number = 50, offset: number = 0): Promise<{ runs: EvalRunSummary[]; limit: number; offset: number }> {
  return apiFetch('/api/v1/evals/runs?limit=' + limit + '&offset=' + offset);
}

export async function fetchEvalRunDetail(runId: string): Promise<EvalRunDetail> {
  return apiFetch('/api/v1/evals/run/' + runId + '/details');
}

/** Generate and store explanations for all evals in the run (rule + optional LLM). Returns run-level summary. */
export interface EvalRunExplainResponse {
  run_id: string;
  evals_updated: number;
  run_explanation: {
    main_drivers?: string[];
    strongest_areas?: string[];
    what_to_fix?: string[];
  } | null;
}

export async function fetchEvalRunExplain(runId: string): Promise<EvalRunExplainResponse> {
  return apiFetch('/api/v1/evals/run/' + runId + '/explain', { method: 'POST' });
}

// Enterprise eval summary
export interface EvalSummary {
  window: string;
  window_hours: number;
  total_runs: number;
  total_evals: number;
  avg_score: number;
  min_score: number | null;
  max_score: number | null;
  p50_score: number | null;
  p95_score: number | null;
  pass_rate: number;
  passed_count: number;
  failed_count: number;
  avg_groundedness: number | null;
  avg_retrieval_relevance: number | null;
  avg_faithfulness: number | null;
  missing_headlines_count: number;
  missing_candles_count: number;
  missing_headlines_pct: number;
  missing_candles_pct: number;
}

export async function fetchEvalSummary(window: string = '24h'): Promise<EvalSummary> {
  return apiFetch('/api/v1/evals/summary?window=' + window);
}

export async function fetchConversationEvals(conversationId: string): Promise<{ evals: any[]; conversation_id: string }> {
  return apiFetch('/api/v1/evals/conversations/' + conversationId);
}
