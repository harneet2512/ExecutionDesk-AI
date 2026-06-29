'use client';

import { useState, useEffect, useRef, useCallback } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import {
  executeChatCommand,
  listMessages,
  createMessage,
  createConversation,
  getConversation,
  getRunStatusSafe,
  getTicketByRunId,
  submitTicketReceipt,
  cancelTicket,
  checkHealth,
  fetchCapabilities,
  type Message,
  type TradeTicket,
  type HealthStatus,
  type Capabilities,
} from '@/lib/api';
import { mergeRunState, flushStepsToTerminal } from '@/lib/runState';
import ChatHeader from '@/components/ChatHeader';
import StepsDrawer, { Step } from '@/components/StepsDrawer';
import NewsToggle from '@/components/NewsToggle';
import ChatBanners, { CircuitBreakerBanner } from '@/components/chat/ChatBanners';
import ChatMessageList from '@/components/chat/ChatMessageList';
import ChatComposer from '@/components/chat/ChatComposer';

export default function ChatPageClient() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const conversationParam = searchParams?.get('conversation');

  const [currentConversationId, setCurrentConversationId] = useState<string | null>(conversationParam);
  const [conversationTitle, setConversationTitle] = useState<string>('New Conversation');
  const [messages, setMessages] = useState<Message[]>([]);
  const [inputText, setInputText] = useState('');
  const [loading, setLoading] = useState(false);
  const [currentRunId, setCurrentRunId] = useState<string | null>(null);
  const [steps, setSteps] = useState<Step[]>([]);
  const [stepsDrawerOpen, setStepsDrawerOpen] = useState(false);
  const [newsEnabled, setNewsEnabled] = useState(true);
  const debugPreconfirmNews = process.env.NEXT_PUBLIC_DEBUG_PRECONFIRM_NEWS === '1';
  const debugRender = process.env.NEXT_PUBLIC_DEBUG_RENDER === '1';
  const [currentTicket, setCurrentTicket] = useState<TradeTicket | null>(null);
  const [currentStepName, setCurrentStepName] = useState<string | null>(null);
  const [runStartTime, setRunStartTime] = useState<number | null>(null);
  const [elapsedTime, setElapsedTime] = useState(0);
  const [copiedMessageId, setCopiedMessageId] = useState<string | null>(null);
  // Track intent by run_id to enable intent-aware rendering
  const [runIntents, setRunIntents] = useState<Record<string, string>>({});
  // Track confirmation IDs that have been acted upon (confirmed/cancelled)
  const [actedConfirmations, setActedConfirmations] = useState<Set<string>>(new Set());
  // Track completed run statuses for TradeReceipt terminal-state gating
  const [completedRuns, setCompletedRuns] = useState<Record<string, string>>({});
  // Health gating: block UI when backend schema is unhealthy
  const [healthStatus, setHealthStatus] = useState<HealthStatus | null>(null);
  const [healthChecked, setHealthChecked] = useState(false);
  // Capabilities: feature flags for LIVE trading, news, etc.
  const [capabilities, setCapabilities] = useState<Capabilities | null>(null);

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const eventSourceRef = useRef<EventSource | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const stepsOpenedRef = useRef(false);
  const recoveryAttemptedRef = useRef(false);
  const confirmingRef = useRef<Set<string>>(new Set());
  const sseConnectedRef = useRef(false);
  const processedRunCompletionsRef = useRef<Set<string>>(new Set());
  // Ref-mirror of health state so that effects can read latest without re-firing
  const healthCheckedRef = useRef(false);
  const healthOkRef = useRef(true);
  // Ref-mirrors for SSE handler to avoid stale closures (R1 fix)
  const completedRunsRef = useRef<Record<string, string>>({});
  const runIntentsRef = useRef<Record<string, string>>({});
  // Send lock to prevent double POST from rapid clicks/Enter before state updates
  const sendingRef = useRef(false);
  // Track pending optimistic messages by client_message_id for deduplication
  const pendingOptimisticRef = useRef<Map<string, string>>(new Map());

  // Keep refs in sync with state (R1 fix: SSE handler reads refs, not state)
  useEffect(() => { completedRunsRef.current = completedRuns; }, [completedRuns]);
  useEffect(() => { runIntentsRef.current = runIntents; }, [runIntents]);

  // Diagnose-first runtime evidence: branch + payload shape per message.
  useEffect(() => {
    if (!debugRender) return;
    messages.forEach((msg, idx) => {
      const intent = msg.metadata_json?.intent || (msg.run_id ? runIntents[msg.run_id] : undefined);
      const hasPortfolioSnapshotCardData = !!(msg.metadata_json?.portfolio_snapshot_card_data || msg.metadata_json?.portfolio_brief);
      const hasTradeConfirmation = intent === 'TRADE_CONFIRMATION_PENDING';
      const hasPreconfirmInsight = !!(msg.metadata_json?.preconfirm_insight || msg.metadata_json?.financial_insight);
      const isPortfolioAnalysis = intent === 'PORTFOLIO_ANALYSIS' || hasPortfolioSnapshotCardData;
      const rendererBranch = hasTradeConfirmation
        ? 'trade_confirmation_pending'
        : isPortfolioAnalysis
          ? 'portfolio_analysis'
          : msg.run_id
            ? 'run_artifacts'
            : 'narrative_only';
      console.info('[CHAT_RENDER_DEBUG][message]', {
        index: idx,
        message_id: msg.message_id,
        role: msg.role,
        run_id: msg.run_id || null,
        kind: msg.role,
        type: msg.metadata_json?.status || null,
        intent,
        status: msg.metadata_json?.status || null,
        metadata_keys: msg.metadata_json ? Object.keys(msg.metadata_json) : [],
        hasPortfolioSnapshotCardData,
        hasTradeConfirmation,
        hasPreconfirmInsight,
        newsEnabled: msg.metadata_json?.news_enabled ?? newsEnabled,
        rendererBranch,
      });
    });
  }, [debugRender, messages, runIntents, newsEnabled]);

  // Health check + capabilities: gate all API calls on backend health
  useEffect(() => {
    (async () => {
      const [health, caps] = await Promise.all([
        checkHealth(),
        fetchCapabilities(),
      ]);
      setHealthStatus(health);
      setCapabilities(caps);
      setHealthChecked(true);
      // Mirror to refs so conversation-loading effect can read without re-firing
      healthCheckedRef.current = true;
      healthOkRef.current = !health || health.ok;
    })();
  }, []);

  // Reset recovery ref on navigation to a different conversation
  useEffect(() => {
    recoveryAttemptedRef.current = false;
  }, [conversationParam]);

  // Load conversation when param changes (only if health is OK)
  // Uses refs for health gate to avoid re-firing when health state changes.
  // AbortController cancels stale fetches when the user rapidly switches conversations.
  useEffect(() => {
    if (!conversationParam) return;
    if (healthCheckedRef.current && !healthOkRef.current) return;

    const abortController = new AbortController();

    setCurrentConversationId(conversationParam);
    setMessages([]);
    setCurrentRunId(null);
    setSteps([]);
    setActedConfirmations(new Set());
    setCompletedRuns({});
    setConversationTitle('New Conversation');

    (async () => {
      try {
        await Promise.all([
          loadConversation(conversationParam),
          loadMessages(conversationParam),
        ]);
      } catch (e: any) {
        if (abortController.signal.aborted) return;
        const is404 = e?.statusCode === 404 || e?.message?.includes('404');
        if (is404 && !recoveryAttemptedRef.current) {
          recoveryAttemptedRef.current = true;
          console.warn('[ChatPage] Conversation not found, creating new one');
          try {
            const conv = await createConversation();
            if (abortController.signal.aborted) return;
            setCurrentConversationId(conv.conversation_id);
            router.replace(`/chat?conversation=${conv.conversation_id}`);
          } catch (createErr) {
            if (process.env.NODE_ENV === 'development') console.error('[ChatPage] Recovery failed:', createErr);
          }
        } else {
          if (process.env.NODE_ENV === 'development') console.error('[ChatPage] Failed to load conversation:', e);
        }
      }
    })();

    return () => { abortController.abort(); };
  }, [conversationParam]);

  // Load conversation details (throws on 404 so parent useEffect can handle recovery)
  const loadConversation = async (conversationId: string) => {
    const conv = await getConversation(conversationId);
    setConversationTitle(conv.title || 'New Conversation');
  };

  // Circuit breaker state for loadMessages
  const loadMsgInFlight = useRef(false);
  const loadMsgLastFailure = useRef(0);
  const loadMsgConsecFails = useRef(0);
  const [loadMsgCircuitOpen, setLoadMsgCircuitOpen] = useState(false);
  const CIRCUIT_COOLDOWN_MS = 8000; // 8s cooldown after consecutive failures

  // Bug 5 fix: Merge messages by message_id instead of wholesale replacement
  // This prevents UI flicker and race conditions between SSE and polling
  // Enhanced: Also handles optimistic message deduplication via client_message_id
  const mergeMessages = useCallback((prev: Message[], incoming: Message[]): Message[] => {
    if (prev.length === 0) return incoming;
    
    const byId = new Map<string, Message>();
    // Build a map of client_message_id -> optimistic message_id for deduplication
    const clientIdToOptId = new Map<string, string>();
    
    // Start with existing messages, tracking optimistic ones by client_message_id
    prev.forEach(m => {
      byId.set(m.message_id, m);
      // Track optimistic messages by their client_message_id
      if (m.message_id.startsWith('opt_') && m.metadata_json?.client_message_id) {
        clientIdToOptId.set(m.metadata_json.client_message_id, m.message_id);
      }
    });
    
    // Merge in incoming (incoming wins for same message_id)
    // Also replace optimistic messages when server returns real message with same client_message_id
    incoming.forEach(m => {
      // Check if this server message matches a pending optimistic message
      const clientMsgId = m.metadata_json?.client_message_id;
      if (clientMsgId && clientIdToOptId.has(clientMsgId)) {
        // Remove the optimistic message, use server's real message
        const optId = clientIdToOptId.get(clientMsgId)!;
        byId.delete(optId);
        pendingOptimisticRef.current.delete(clientMsgId);
      }
      byId.set(m.message_id, m);
    });
    
    // Sort by created_at to maintain order
    const merged = Array.from(byId.values());
    merged.sort((a, b) => {
      const aTime = new Date(a.created_at).getTime();
      const bTime = new Date(b.created_at).getTime();
      return aTime - bTime;
    });
    
    return merged;
  }, []);

  // Load messages for a conversation (core impl)
  const loadMessages = async (conversationId: string) => {
    const msgs = await listMessages(conversationId);
    // Bug 5 fix: Use merge instead of wholesale replacement
    setMessages(prev => mergeMessages(prev, msgs));
    // Find the last run_id from messages
    const lastRunId = msgs.findLast(m => m.run_id)?.run_id;
    if (lastRunId) {
      setCurrentRunId(prev => prev === lastRunId ? prev : lastRunId);
    }
    // Reconstruct acted confirmations from message history
    const acted = new Set<string>();
    msgs.forEach((m, i) => {
      if (m.role === 'user' && (m.content === 'CONFIRM' || m.content === 'CANCEL')) {
        for (let j = i - 1; j >= 0; j--) {
          const confId = msgs[j].metadata_json?.confirmation_id;
          if (confId) { acted.add(confId); break; }
        }
      }
      if (m.metadata_json?.intent === 'TRADE_EXECUTION' && m.metadata_json?.status === 'EXECUTING') {
        for (let j = i - 1; j >= 0; j--) {
          const confId = msgs[j].metadata_json?.confirmation_id;
          if (confId) { acted.add(confId); break; }
        }
      }
    });
    // Only update acted confirmations if the set changed (prevent unnecessary re-renders)
    setActedConfirmations(prev => {
      if (prev.size === acted.size && Array.from(acted).every(id => prev.has(id))) return prev;
      return acted;
    });
    // Reconstruct completed run statuses from message metadata
    // D3: Only update state when values actually change to prevent re-render cascades
    const completed: Record<string, string> = {};
    msgs.forEach(m => {
      if (m.run_id && m.metadata_json?.status) {
        const s = String(m.metadata_json.status).toUpperCase();
        if (s === 'COMPLETED' || s === 'FAILED') {
          completed[m.run_id] = s;
        }
      }
    });
    // Bug 3 fix: Use mergeRunState to ensure terminal states always win
    setCompletedRuns(prev => {
      const merged = mergeRunState(prev, completed);
      // Check if anything actually changed before triggering a state update
      const hasNew = Object.keys(merged).some(k => prev[k] !== merged[k]);
      if (!hasNew) return prev;
      return merged;
    });
    // Reset circuit breaker on success
    loadMsgConsecFails.current = 0;
    if (loadMsgCircuitOpen) setLoadMsgCircuitOpen(false);
  };

  // Debounced loadMessages with in-flight guard, cooldown, and circuit breaker.
  // When the circuit is open (3+ consecutive failures), auto-calls are suppressed
  // and a "Retry" button is shown instead.
  const loadMessagesDebounced = useCallback(async (convId: string) => {
    // In-flight guard: collapse concurrent calls
    if (loadMsgInFlight.current) return;
    // Circuit breaker: if recently failed 3+ times, block auto-retry
    if (loadMsgConsecFails.current >= 3) {
      const elapsed = Date.now() - loadMsgLastFailure.current;
      if (elapsed < CIRCUIT_COOLDOWN_MS) {
        setLoadMsgCircuitOpen(true);
        return;
      }
      // Cooldown expired, allow retry
    }
    loadMsgInFlight.current = true;
    try {
      await loadMessages(convId);
    } catch (e: any) {
      loadMsgConsecFails.current += 1;
      loadMsgLastFailure.current = Date.now();
      if (loadMsgConsecFails.current >= 3) {
        setLoadMsgCircuitOpen(true);
      }
      if (process.env.NODE_ENV === 'development') console.error('Failed to load messages:', e);
    } finally {
      // Cooldown window: 1000ms before next fetch allowed (P2: reduce overlapping requests)
      setTimeout(() => { loadMsgInFlight.current = false; }, 1000);
    }
  }, []);

  // Manual retry: resets circuit breaker and forces a fetch
  const retryLoadMessages = useCallback(async () => {
    if (!currentConversationId) return;
    loadMsgConsecFails.current = 0;
    loadMsgLastFailure.current = 0;
    setLoadMsgCircuitOpen(false);
    loadMsgInFlight.current = false;
    try {
      await loadMessages(currentConversationId);
    } catch (e) {
      if (process.env.NODE_ENV === 'development') console.error('Retry failed:', e);
    }
  }, [currentConversationId]);

  // Stable callback for TradeProcessingCard.onComplete (R1 fix: prevents infinite loop
  // from inline arrow function creating new ref each render -> useEffect re-fire)
  // Also flushes steps to terminal state (U1 fix: prevents stale "running" steps)
  const handleTradeComplete = useCallback((completedStatus: string, runId: string) => {
    setLoading(false);
    if (runId) {
      // Bug 3 fix: Use mergeRunState to ensure terminal states always win
      setCompletedRuns(prev => {
        const merged = mergeRunState(prev, { [runId]: completedStatus });
        // Avoid state update if already set (prevent render loop)
        if (prev[runId] === merged[runId]) return prev;
        return merged;
      });
    }
    // Bug 3 fix: Use flushStepsToTerminal utility to prevent "running" while "FAILED"
    setSteps(prev => flushStepsToTerminal(prev, completedStatus));

    // Use debounced load to avoid spamming backend
    if (currentConversationId) {
      // slight delay to let backend write final state
      setTimeout(() => loadMessagesDebounced(currentConversationId), 500);
    }
  }, [currentConversationId, loadMessagesDebounced]);

  // Create new conversation
  const handleNewChat = async () => {
    try {
      recoveryAttemptedRef.current = false;
      const conv = await createConversation();
      setCurrentConversationId(conv.conversation_id);
      setConversationTitle('New Conversation');
      setMessages([]);
      setCurrentRunId(null);
      setSteps([]);
      router.push(`/chat?conversation=${conv.conversation_id}`);
    } catch (e) {
      if (process.env.NODE_ENV === 'development') console.error('Failed to create conversation:', e);
    }
  };

  // Scroll to bottom
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  // Track elapsed time while loading
  useEffect(() => {
    if (loading && runStartTime) {
      const interval = setInterval(() => {
        setElapsedTime(Math.floor((Date.now() - runStartTime) / 1000));
      }, 1000);
      return () => clearInterval(interval);
    } else if (!loading) {
      setElapsedTime(0);
      setCurrentStepName(null);
    }
  }, [loading, runStartTime]);

  // Copy message to clipboard
  const handleCopyMessage = async (messageId: string, content: string) => {
    try {
      await navigator.clipboard.writeText(content);
      setCopiedMessageId(messageId);
      setTimeout(() => setCopiedMessageId(null), 2000);
    } catch (e) {
      if (process.env.NODE_ENV === 'development') console.error('Failed to copy:', e);
    }
  };

  // SSE event handling
  useEffect(() => {
    if (!currentRunId) return;

    // StrictMode guard: prevent double connection on double-mount
    let mounted = true;

    if (eventSourceRef.current) {
      eventSourceRef.current.close();
    }

    // Reset drawer opened flag for new run
    stepsOpenedRef.current = false;

    // P0: Stop if run is already known to be completed (use ref to avoid stale closure)
    if (currentRunId && completedRunsRef.current[currentRunId]) {
      return;
    }

    let reconnectTimer: NodeJS.Timeout | null = null;
    let reconnectAttempts = 0;
    const maxReconnectAttempts = 5;
    let lastEventId = '';

    function connect() {
      // StrictMode guard: don't connect if already unmounted
      if (!mounted) return;
      if (!currentRunId) return; // Guard against null runId
      // EventSource cannot set custom headers, so pass tenant as query param
      const sseParams = new URLSearchParams({ tenant: 't_default' });
      if (lastEventId) sseParams.set('last_event_id', lastEventId);
      const eventSource = new EventSource(
        `/api/v1/runs/${currentRunId}/events?${sseParams.toString()}`,
        { withCredentials: false } as any
      );

      eventSource.onmessage = (event: MessageEvent) => {
        try {
          const eventId = (event as any).id || '';
          if (eventId) lastEventId = eventId;

          const data = JSON.parse(event.data);

          // Handle STEP_STARTED
          if (data.event_type === 'STEP_STARTED' || data.payload?.event_type === 'STEP_STARTED') {
            const payload = data.payload || data;
            const timestamp = data.ts || payload.started_at || new Date().toISOString();

            // Update current step name for dynamic processing indicator
            const stepName = payload.step_name || payload.name || 'Processing';
            setCurrentStepName(stepName.charAt(0).toUpperCase() + stepName.slice(1).replace(/_/g, ' '));

            // Auto-open steps drawer on first step (use ref to avoid re-running effect)
            if (!stepsOpenedRef.current) {
              stepsOpenedRef.current = true;
              const autoOpen = localStorage.getItem('stepsDrawerAutoOpen');
              if (autoOpen !== 'false') {
                setStepsDrawerOpen(true);
              }
            }

            setSteps((prev) => {
              const existing = prev.find((s) => s.step_id === payload.step_id);
              if (existing) {
                return prev.map((s) =>
                  s.step_id === payload.step_id
                    ? { ...s, status: 'running' as const, description: payload.description, timestamp, started_timestamp: payload.started_at || timestamp }
                    : s
                );
              }
              return [
                ...prev,
                {
                  step_id: payload.step_id,
                  step_name: payload.step_name,
                  status: 'running' as const,
                  description: payload.description,
                  timestamp,
                  started_timestamp: payload.started_at || timestamp,
                  sequence: payload.sequence || prev.length + 1
                }
              ];
            });
          }

          // Handle STEP_FINISHED
          if (data.event_type === 'STEP_FINISHED' || data.event_type === 'STEP_COMPLETED' || data.payload?.event_type === 'STEP_FINISHED' || data.payload?.event_type === 'STEP_COMPLETED') {
            const payload = data.payload || data;
            const timestamp = data.ts || payload.completed_at || new Date().toISOString();
            setSteps((prev) =>
              prev.map((s) =>
                s.step_id === payload.step_id
                  ? {
                    ...s,
                    status: payload.status === 'completed' ? 'done' as const : 'failed' as const,
                    summary: payload.summary,
                    evidence_refs: payload.evidence_refs,
                    timestamp,
                    started_timestamp: payload.started_at || s.started_timestamp,
                    duration_ms: payload.duration_ms,
                    sequence: payload.sequence || s.sequence
                  }
                  : s
              )
            );
          }

          // Handle RUN_COMPLETE / RUN_COMPLETED (SSE endpoint sends RUN_COMPLETE, pubsub sends RUN_COMPLETED)
          // Bug 2 fix: Don't say "Trade executed successfully" until we know order was actually FILLED
          if ((data.event_type === 'RUN_COMPLETE' || data.event_type === 'RUN_COMPLETED') && currentConversationId && currentRunId) {
            const alreadyProcessed = processedRunCompletionsRef.current.has(currentRunId);
            if (!alreadyProcessed) {
              processedRunCompletionsRef.current.add(currentRunId);
              const payload = data.payload || data;
              const runStatus = payload?.status || 'COMPLETED';
              const intent = runIntentsRef.current[currentRunId];
              
              // Only show success message when actually completed, not on failure
              if (runStatus === 'COMPLETED') {
                // Use payload summary from runner artifact, or infer from intent
                let summary = payload?.summary;
                
                if (!summary) {
                  if (intent === 'TRADE_EXECUTION' || intent === 'TRADE_CONFIRMATION_PENDING') {
                    // Bug 2 fix: Use order_status from payload if available to determine actual outcome
                    const orderStatus = payload?.order_status;
                    if (orderStatus === 'FILLED') {
                      summary = 'Trade executed successfully';
                    } else if (orderStatus === 'SUBMITTED' || orderStatus === 'PENDING' || orderStatus === 'OPEN') {
                      summary = 'Order submitted - check receipt for fill status';
                    } else {
                      // Run completed but order status unknown - let TradeReceipt show actual status
                      summary = 'Trade processing complete - see receipt for details';
                    }
                  } else if (intent === 'PORTFOLIO' || intent === 'PORTFOLIO_ANALYSIS') {
                    // Don't create a separate completion message for portfolio - the PortfolioCard handles display
                    return;
                  } else {
                    // No summary from backend and unknown intent - skip generic message to avoid ghost bubbles
                    return;
                  }
                }
                createMessage(currentConversationId, summary, 'assistant', currentRunId, { event_type: data.event_type, status: 'COMPLETED', intent, order_status: payload?.order_status })
                  .then(() => loadMessagesDebounced(currentConversationId))
                  .catch(e => { if (process.env.NODE_ENV === 'development') console.error('Failed to create assistant message:', e); });
              } else if (runStatus === 'FAILED') {
                const errorMsg = payload?.error || 'Trade execution failed';
                createMessage(currentConversationId, `Execution failed: ${errorMsg}`, 'assistant', currentRunId, { event_type: data.event_type, status: 'FAILED' })
                  .then(() => loadMessagesDebounced(currentConversationId))
                  .catch(e => { if (process.env.NODE_ENV === 'development') console.error('Failed to create failure message:', e); });
              }
            }
          }

          // Handle RUN_FAILED events from runner/approvals
          if (data.event_type === 'RUN_FAILED' && currentConversationId && currentRunId) {
            const alreadyProcessed = processedRunCompletionsRef.current.has(currentRunId);
            if (!alreadyProcessed) {
              processedRunCompletionsRef.current.add(currentRunId);
              const payload = data.payload || data;
              const errorMsg = payload?.error || 'Trade execution failed';
              createMessage(currentConversationId, `Execution failed: ${errorMsg}`, 'assistant', currentRunId, { event_type: 'RUN_FAILED', status: 'FAILED' })
                .then(() => loadMessagesDebounced(currentConversationId))
                .catch(e => { if (process.env.NODE_ENV === 'development') console.error('Failed to create failure message:', e); });
            }
          }

          // Handle TRADE_TICKET_CREATED for ASSISTED_LIVE stocks
          if (data.event_type === 'TRADE_TICKET_CREATED' && currentRunId) {
            const payload = data.payload || data;
            // Fetch the full ticket details
            getTicketByRunId(currentRunId)
              .then(ticket => {
                if (ticket) {
                  setCurrentTicket(ticket);
                }
              })
              .catch(e => { if (process.env.NODE_ENV === 'development') console.error('Failed to fetch ticket:', e); });
          }
        } catch (e) {
          if (process.env.NODE_ENV === 'development') console.error('Failed to parse SSE event:', e);
        }
      };

      eventSource.onerror = () => {
        eventSource.close();
        if (reconnectAttempts < maxReconnectAttempts) {
          reconnectAttempts++;
          const backoffMs = Math.min(1000 * Math.pow(2, reconnectAttempts - 1) + Math.random() * 500, 30000);
          reconnectTimer = setTimeout(() => connect(), backoffMs);
        } else {
          console.warn('SSE connection failed, falling back to polling');
          sseConnectedRef.current = false;
          eventSourceRef.current = null;
        }
      };

      eventSource.onopen = () => {
        reconnectAttempts = 0;
        sseConnectedRef.current = true;
      };

      eventSourceRef.current = eventSource;
    }

    try {
      connect();
    } catch (e) {
      console.warn('SSE not available, using polling only:', e);
    }

    // Poll for completion (P1: skip if SSE is connected and healthy)
    let errorCount = 0;
    const pollStartTime = Date.now();
    const POLL_TIMEOUT_MS = 120_000; // 120s client-side safety net
    const pollInterval = setInterval(async () => {
      // Skip polling tick when SSE is connected (P1: reduce overlapping requests)
      if (sseConnectedRef.current) return;

      // Absolute timeout: stop polling after 120s regardless
      if (Date.now() - pollStartTime > POLL_TIMEOUT_MS) {
        clearInterval(pollInterval);
        setLoading(false);
        if (eventSourceRef.current) eventSourceRef.current.close();
        createMessage(
          currentConversationId!,
          'Execution is taking longer than expected. Check the run details page for status.',
          'assistant'
        ).catch(() => {});
        loadMessagesDebounced(currentConversationId!).catch(() => {});
        return;
      }

      // Use non-throwing status fetch (raw fetch, no apiFetch throw = no Next.js error overlay)
      const statusData = await getRunStatusSafe(currentRunId);
      if (!statusData) {
        errorCount++;
        // Stop polling after 5 consecutive failures
        if (errorCount >= 5) {
          clearInterval(pollInterval);
          setLoading(false);
          if (eventSourceRef.current) eventSourceRef.current.close();
          createMessage(
            currentConversationId!,
            'Polling stopped after repeated failures. Check if backend is running on port 8000.',
            'assistant'
          ).catch(() => {});
          loadMessagesDebounced(currentConversationId!).catch(() => {});
        }
        return;
      }
      errorCount = 0;

      if (statusData.status === 'COMPLETED' || statusData.status === 'FAILED' || statusData.status === 'PAUSED') {
        clearInterval(pollInterval);
        setLoading(false);
        if (eventSourceRef.current) eventSourceRef.current.close();
      }
    }, 2000);

    return () => {
      // StrictMode guard: mark as unmounted to prevent reconnects
      mounted = false;
      clearInterval(pollInterval);
      if (reconnectTimer) clearTimeout(reconnectTimer);
      sseConnectedRef.current = false;
      if (eventSourceRef.current) eventSourceRef.current.close();
    };
  }, [currentRunId, currentConversationId]);

  // Handle message send
  const handleSend = async () => {
    // Double-send prevention: ref-based lock checked before state
    if (sendingRef.current) return;
    if (!inputText.trim() || loading) return;
    
    // Acquire send lock immediately
    sendingRef.current = true;
    
    const userMessageText = inputText.trim();
    setInputText('');
    setLoading(true);

    let convId = currentConversationId;
    if (!convId) {
      // Create conversation first
      try {
        const conv = await createConversation();
        convId = conv.conversation_id;
        setCurrentConversationId(convId);
        router.push(`/chat?conversation=${convId}`);
      } catch (convErr: any) {
        if (process.env.NODE_ENV === 'development') console.error('Failed to create conversation:', convErr);
        setLoading(false);
        sendingRef.current = false; // Release lock on error
        setMessages(prev => [...prev, {
          message_id: 'err_' + Date.now(),
          conversation_id: '',
          role: 'assistant',
          content: 'Could not connect to the server. Please check that the backend is running and try again.',
          created_at: new Date().toISOString(),
        }]);
        return;
      }
    }
    setRunStartTime(Date.now());
    setCurrentStepName(null);

    // Generate client_message_id for idempotent message creation
    const clientMessageId = crypto.randomUUID();

    try {
      // Create user message with client_message_id for deduplication
      await createMessage(convId, userMessageText, 'user', undefined, { client_message_id: clientMessageId });
      
      // Optimistically append to UI with client_message_id in metadata for later deduplication
      const optimisticId = 'opt_' + Date.now();
      pendingOptimisticRef.current.set(clientMessageId, optimisticId);
      setMessages(prev => [...prev, {
        message_id: optimisticId,
        conversation_id: convId || '',
        role: 'user' as const,
        content: userMessageText,
        created_at: new Date().toISOString(),
        metadata_json: { client_message_id: clientMessageId },
      }]);

      // Execute command (natural language only)
      const result = await executeChatCommand(userMessageText, convId, newsEnabled);
      const preconfirmInsight = result?.preconfirm_insight || result?.financial_insight || null;
      const portfolioSnapshotCardData = result?.portfolio_snapshot_card_data || result?.portfolio_brief || null;
      if (debugPreconfirmNews) {
        console.info('[PRECONFIRM_NEWS][chat_command_result]', {
          intent: result?.intent,
          status: result?.status,
          news_enabled: result?.news_enabled,
          has_preconfirm_insight: !!preconfirmInsight,
          preconfirm_insight_keys: preconfirmInsight ? Object.keys(preconfirmInsight) : [],
          pending_trade_asset: result?.pending_trade?.asset,
          confirmation_id: result?.confirmation_id,
          has_portfolio_snapshot_card_data: !!portfolioSnapshotCardData,
          portfolio_snapshot_card_data_keys: portfolioSnapshotCardData ? Object.keys(portfolioSnapshotCardData) : [],
        });
      }

      // CRITICAL: Check if run_id exists before treating as run-based response
      if (result.run_id) {
        // Run-based response: set run_id and create run message
        setCurrentRunId(result.run_id);
        setSteps([]);
        
        // Track intent for this run to enable proper completion message handling
        // Update ref immediately so SSE handler can access it without waiting for render
        if (result.intent) {
          runIntentsRef.current = { ...runIntentsRef.current, [result.run_id]: result.intent };
          setRunIntents(prev => ({ ...prev, [result.run_id]: result.intent }));
        }

        // Check if the response is already COMPLETED with content (e.g., portfolio analysis)
        // If so, display the content directly instead of a placeholder
        if (result.status === 'COMPLETED' && result.content) {
          // Mark as already processed to prevent SSE handler from creating duplicate message
          processedRunCompletionsRef.current.add(result.run_id);
          
          // Completed synchronously - display final content immediately
          // Generate client_message_id for assistant message deduplication
          const assistantClientId = crypto.randomUUID();
          const completedMeta: Record<string, any> = { intent: result.intent, status: result.status, client_message_id: assistantClientId };
          if (result.narrative_structured) completedMeta.narrative_structured = result.narrative_structured;
          if (portfolioSnapshotCardData) {
            completedMeta.portfolio_snapshot_card_data = portfolioSnapshotCardData;
          }
          await createMessage(
            convId,
            result.content,
            'assistant',
            result.run_id,
            completedMeta,
          );
          setMessages(prev => [...prev, {
            message_id: 'opt_' + Date.now(),
            conversation_id: convId || '',
            role: 'assistant' as const,
            content: result.content,
            run_id: result.run_id,
            created_at: new Date().toISOString(),
            metadata_json: completedMeta,
          }]);
          setLoading(false);
        } else {
          // Async execution - use contextual text from backend when available
          const processingMsg = result.content || `Executing ${result.intent || 'command'}...`;
          const assistantClientId = crypto.randomUUID();
          await createMessage(
            convId,
            processingMsg,
            'assistant',
            result.run_id,
            { intent: result.intent, status: 'EXECUTING', client_message_id: assistantClientId }
          );
          // Optimistically add assistant message to UI (no loadMessagesDebounced needed)
          setMessages(prev => [...prev, {
            message_id: 'opt_' + Date.now(),
            conversation_id: convId || '',
            role: 'assistant' as const,
            content: processingMsg,
            run_id: result.run_id,
            created_at: new Date().toISOString(),
            metadata_json: { intent: result.intent, status: 'EXECUTING', client_message_id: assistantClientId },
          }]);
          // Note: loading stays true - SSE/polling will handle completion
        }
      } else {
        // Message-only response: create plain assistant message immediately
        setLoading(false);

        // Extract content from response
        const content = result.content || result.message || 'Response received';
        const assistantClientId = crypto.randomUUID();

        await createMessage(
          convId,
          content,
          'assistant',
          undefined,
          {
            intent: result.intent,
            status: result.status,
            news_enabled: result.news_enabled ?? newsEnabled,
            confirmation_id: result.confirmation_id,
            pending_trade: result.pending_trade,
            preconfirm_insight: preconfirmInsight || undefined,
            financial_insight: preconfirmInsight || undefined,
            portfolio_snapshot_card_data: portfolioSnapshotCardData || undefined,
            selection_result: result.selection_result || undefined,
            narrative_structured: result.narrative_structured || undefined,
            client_message_id: assistantClientId
          }
        );
        setMessages(prev => [...prev, {
          message_id: 'opt_' + Date.now(),
          conversation_id: convId || '',
          role: 'assistant' as const,
          content: content,
          created_at: new Date().toISOString(),
          metadata_json: {
            intent: result.intent,
            status: result.status,
            news_enabled: result.news_enabled ?? newsEnabled,
            confirmation_id: result.confirmation_id,
            pending_trade: result.pending_trade,
            preconfirm_insight: preconfirmInsight || undefined,
            financial_insight: preconfirmInsight || undefined,
            portfolio_snapshot_card_data: portfolioSnapshotCardData || undefined,
            selection_result: result.selection_result || undefined,
            narrative_structured: result.narrative_structured || undefined,
            client_message_id: assistantClientId
          },
        }]);
      }
    } catch (error: any) {
      if (process.env.NODE_ENV === 'development') console.error('Command failed:', error);
      setLoading(false);
      try {
        if (convId) {
          const errMsg = error?.message || 'Something went wrong. Please try again.';
          const retryAfter = error?.retryAfterSeconds;

          let displayMsg: string;
          if (retryAfter) {
            // Rate limited - friendly message with auto-retry hint
            displayMsg = `Too many requests. Please wait ${retryAfter} seconds before trying again.`;
          } else {
            // Generic error - extract request_id for prominent display
            const reqIdMatch = errMsg.match(/Request ID:\s*([a-f0-9-]+)/i);
            // Deterministic messaging: never say "may have executed"
            // Command-phase errors (before confirmation) never execute trades
            displayMsg = reqIdMatch
              ? `Order not submitted. No trade was placed.\n\n**Request ID:** \`${reqIdMatch[1]}\`\n\nShare this ID when reporting issues.`
              : `Error: ${errMsg}`;
          }
          const errorClientId = crypto.randomUUID();
          await createMessage(convId, displayMsg, 'assistant', undefined, { client_message_id: errorClientId });
          // Optimistically add error message to UI
          setMessages(prev => [...prev, {
            message_id: 'opt_' + Date.now(),
            conversation_id: convId || '',
            role: 'assistant' as const,
            content: displayMsg,
            created_at: new Date().toISOString(),
            metadata_json: { client_message_id: errorClientId },
          }]);
        }
      } catch (innerErr) {
        if (process.env.NODE_ENV === 'development') console.error('Failed to save error message:', innerErr);
      }
    } finally {
      // Always release send lock
      sendingRef.current = false;
    }
  };

  // Handle suggestion chip click
  const handleSuggestionClick = (text: string) => {
    setInputText(text);
    // Auto-focus textarea
    textareaRef.current?.focus();
    // Optionally auto-send
    // setTimeout(() => handleSend(), 100);
  };

  // Handle keyboard shortcuts
  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  // Handle confirm trade action (called from ConfirmationCard via ChatMessageList)
  const handleConfirm = useCallback(async (confId: string) => {
    if (process.env.NODE_ENV === 'development') console.log('[CONFIRM] Button clicked', { confirmation_id: confId });

    if (!confId) {
      if (process.env.NODE_ENV === 'development') console.error('[CONFIRM] No confirmation_id provided');
      return;
    }
    // C1: In-flight guard to prevent double-click
    if (confirmingRef.current.has(confId)) return;
    confirmingRef.current.add(confId);
    try {
      setLoading(true);
      const res = await import('@/lib/api').then(m => m.confirmTrade(confId));
      if (process.env.NODE_ENV === 'development') console.log('[CONFIRM] Response received', res);
      // Mark as acted AFTER API success (not before)
      setActedConfirmations(prev => new Set(prev).add(confId));

      await createMessage(currentConversationId!, "CONFIRM", 'user');

      if (res.run_id) {
        // C2: Guard against duplicate execution messages
        const alreadyHasExecMsg = messages.some(
          m => m.run_id === res.run_id && m.metadata_json?.intent === 'TRADE_EXECUTION'
        );
        if (!alreadyHasExecMsg) {
          setCurrentRunId(res.run_id);
          setSteps([]);
          setRunIntents(prev => ({ ...prev, [res.run_id]: res.intent || 'TRADE_EXECUTION' }));
          // Find the confirmation message to get trade info
          const confMsg = messages.find(m => m.metadata_json?.confirmation_id === confId);
          const tradeInfo = confMsg?.metadata_json?.pending_trade;
          const side = tradeInfo?.side?.toUpperCase() || 'TRADE';
          const asset = tradeInfo?.asset || '';
          const amount = typeof tradeInfo?.amount_usd === 'number' && isFinite(tradeInfo.amount_usd) ? `$${tradeInfo.amount_usd.toFixed(2)}` : '';

          // Persist financial insight in execution message so it remains visible after confirmation
          const executionMetadata: any = {
            intent: res.intent || 'TRADE_EXECUTION',
            status: 'EXECUTING'
          };
          const msgPreconfirmInsight =
            confMsg?.metadata_json?.preconfirm_insight ||
            confMsg?.metadata_json?.financial_insight;
          if (msgPreconfirmInsight) {
            executionMetadata.preconfirm_insight = msgPreconfirmInsight;
            executionMetadata.financial_insight = msgPreconfirmInsight;
          }

          await createMessage(
            currentConversationId!,
            `Executing ${side} ${amount} ${asset}...`,
            'assistant',
            res.run_id,
            executionMetadata
          );
        }
      } else if (res.already_confirmed) {
        // P4.3: Idempotent confirm - already processed
        setActedConfirmations(prev => new Set(prev).add(confId));
        await createMessage(
          currentConversationId!,
          'Already confirmed. This trade has already been processed.',
          'assistant',
          res.run_id || undefined,
          { intent: 'INFO', status: 'ALREADY_CONFIRMED' }
        );
      } else if (res.status === 'CONFIRMED' && !res.run_id) {
        // LIVE disabled case: confirmed but no execution
        const confMsg = messages.find(m => m.metadata_json?.confirmation_id === confId);
        const tradeInfo = confMsg?.metadata_json?.pending_trade;
        const mode = tradeInfo?.mode || 'UNKNOWN';
        if (mode === 'LIVE') {
          await createMessage(
            currentConversationId!,
            'Trade confirmed but not executed: LIVE trading is currently disabled. Set TRADING_DISABLE_LIVE=false and ENABLE_LIVE_TRADING=true to enable LIVE execution.',
            'assistant',
            undefined,
            { intent: 'INFO', status: 'LIVE_DISABLED' }
          );
        } else {
          await createMessage(
            currentConversationId!,
            res.content || res.message || 'Trade confirmed but not executed.',
            'assistant'
          );
        }
      } else if (res.status === 'CANCELLED' || res.status === 'EXPIRED') {
        // Already processed by backend, silently dismiss
        if (process.env.NODE_ENV === 'development') console.log('[CONFIRM] Already processed:', res.status);
      } else {
        await createMessage(
          currentConversationId!,
          res.content || res.message,
          'assistant'
        );
      }
      await loadMessagesDebounced(currentConversationId!);
    } catch (e: any) {
      if (process.env.NODE_ENV === 'development') console.error('[CONFIRM] Failed:', {
        confirmation_id: confId,
        statusCode: e.statusCode,
        requestId: e.requestId,
        errorCode: e.errorCode,
        message: e.message,
        remediation: e.error?.remediation,
        fullError: e,
      });
      // Do NOT mark as acted on failure - leave buttons visible for retry
      let detail: string;
      if (e.statusCode === 403 || e.errorCode === 'LIVE_DISABLED') {
        detail = 'LIVE trading is currently disabled. The trade was not executed. Use PAPER mode or enable LIVE trading in your environment.';
      } else if (e.message?.includes('404')) {
        detail = 'Confirmation not found or expired. Please submit a new trade request.';
      } else if (e.statusCode === 409 || e.errorCode === 'RUN_ALREADY_ACTIVE') {
        detail = 'A trade is currently executing. Wait for it to complete before confirming another.';
      } else {
        // Network/unknown error: attempt recovery via status endpoint
        try {
          const { getConfirmationStatus } = await import('@/lib/api');
          const statusRes = await getConfirmationStatus(confId);
          if (statusRes.executed && statusRes.run_id) {
            detail = `Order submitted (pending fill confirmation). Run ID: ${statusRes.run_id}`;
            setActedConfirmations(prev => new Set(prev).add(confId));
            setCurrentRunId(statusRes.run_id);
          } else {
            detail = 'Order not submitted. No trade was placed.';
          }
        } catch {
          detail = `Confirmation failed: ${e.message}`;
        }
      }
      if (currentConversationId) {
        await createMessage(currentConversationId, detail, 'assistant', undefined, { intent: 'ERROR', status: 'FAILED' });
        await loadMessagesDebounced(currentConversationId);
      }
    } finally {
      confirmingRef.current.delete(confId);
      setLoading(false);
    }
  }, [currentConversationId, messages, loadMessagesDebounced]);

  // Handle cancel trade action (called from ConfirmationCard via ChatMessageList)
  const handleCancel = useCallback(async (cid: string) => {
    if (!cid) return;
    try {
      setLoading(true);
      const res = await import('@/lib/api').then(m => m.cancelTrade(cid));
      // Mark as acted AFTER API success
      setActedConfirmations(prev => new Set(prev).add(cid));
      await createMessage(currentConversationId!, "CANCEL", 'user');
      // Check response status to avoid misleading messages
      if (res.status === 'CANCELLED') {
        await createMessage(currentConversationId!, "Trade cancelled.", 'assistant');
      } else if (res.status === 'CONFIRMED') {
        await createMessage(currentConversationId!, "Trade was already confirmed and is executing.", 'assistant');
      } else if (res.status === 'EXPIRED') {
        await createMessage(currentConversationId!, "Trade confirmation had already expired.", 'assistant');
      } else {
        await createMessage(currentConversationId!, res.message || "Trade cancelled.", 'assistant');
      }
      await loadMessagesDebounced(currentConversationId!);
    } catch (e: any) {
      // Do NOT mark as acted on failure - leave buttons visible for retry
      if (process.env.NODE_ENV === 'development') console.error('[CANCEL] Failed:', {
        confirmation_id: cid,
        statusCode: e.statusCode,
        requestId: e.requestId,
        errorCode: e.errorCode,
        message: e.message,
      });
      if (currentConversationId) {
        await createMessage(currentConversationId, `Cancellation failed: ${e.message}`, 'assistant', undefined, { intent: 'ERROR', status: 'FAILED' });
        await loadMessagesDebounced(currentConversationId);
      }
    } finally {
      setLoading(false);
    }
  }, [currentConversationId, loadMessagesDebounced]);

  // Handle retry from TradeProcessingCard
  const handleRetry = useCallback((messageId: string, msgs: Message[]) => {
    const msgIndex = msgs.findIndex(m => m.message_id === messageId);
    let contentToRetry = '';

    if (msgIndex > 0) {
      const triggerMsg = msgs[msgIndex - 1];
      if (triggerMsg.role === 'user') {
        contentToRetry = triggerMsg.content;
      }
    }

    // Fallback to last user message if finding predecessor fails
    if (!contentToRetry) {
      const lastUserMsg = msgs.findLast(m => m.role === 'user');
      if (lastUserMsg) contentToRetry = lastUserMsg.content;
    }

    if (contentToRetry) {
      setInputText(contentToRetry);
      // slight delay to allow state update before send
      setTimeout(() => handleSend(), 100);
    }
  }, [handleSend]);

  // Handle order ticket execution
  const handleTicketExecuted = useCallback(async (ticketId: string, receipt: any) => {
    await submitTicketReceipt(ticketId, receipt);
    setCurrentTicket(prev => prev ? { ...prev, status: 'EXECUTED' } : null);
    if (currentConversationId) {
      await createMessage(
        currentConversationId,
        `Order ticket ${ticketId} marked as executed.`,
        'assistant'
      );
      loadMessagesDebounced(currentConversationId);
    }
  }, [currentConversationId, loadMessagesDebounced]);

  // Handle order ticket cancellation
  const handleTicketCancelled = useCallback(async (ticketId: string) => {
    await cancelTicket(ticketId);
    setCurrentTicket(prev => prev ? { ...prev, status: 'CANCELLED' } : null);
    if (currentConversationId) {
      await createMessage(
        currentConversationId,
        `Order ticket ${ticketId} cancelled.`,
        'assistant'
      );
      loadMessagesDebounced(currentConversationId);
    }
  }, [currentConversationId, loadMessagesDebounced]);

  return (
    <div className="flex flex-col h-full">
      {/* Chat Header */}
      <ChatHeader
        conversationTitle={conversationTitle}
        onNewChat={handleNewChat}
        onToggleSteps={() => setStepsDrawerOpen(!stepsDrawerOpen)}
        stepsOpen={stepsDrawerOpen}
      />

      {/* News Toggle Bar */}
      <div className="px-6 py-2 border-b theme-border theme-bg flex justify-end">
        <NewsToggle onToggle={setNewsEnabled} initialValue={newsEnabled} />
      </div>

      {/* Banners: LIVE-disabled + Health gate */}
      <ChatBanners
        healthStatus={healthStatus}
        healthChecked={healthChecked}
        capabilities={capabilities}
        loadMsgCircuitOpen={loadMsgCircuitOpen}
        onRetryLoad={retryLoadMessages}
        onHealthRecheck={setHealthStatus}
      />

      {/* Main Content Area */}
      <div className={`flex-1 flex overflow-hidden ${healthChecked && healthStatus && !healthStatus.ok ? 'hidden' : ''}`}>
        {/* Messages Area */}
        <div className="flex-1 flex flex-col overflow-hidden">
          {/* Circuit breaker retry banner */}
          <CircuitBreakerBanner
            loadMsgCircuitOpen={loadMsgCircuitOpen}
            onRetryLoad={retryLoadMessages}
          />

          {/* Messages */}
          <ChatMessageList
            messages={messages}
            runIntents={runIntents}
            completedRuns={completedRuns}
            actedConfirmations={actedConfirmations}
            newsEnabled={newsEnabled}
            loading={loading}
            currentRunId={currentRunId}
            currentStepName={currentStepName}
            elapsedTime={elapsedTime}
            steps={steps}
            copiedMessageId={copiedMessageId}
            capabilities={capabilities}
            healthStatus={healthStatus}
            currentTicket={currentTicket}
            sseConnected={sseConnectedRef.current}
            onSuggestionClick={handleSuggestionClick}
            onCopyMessage={handleCopyMessage}
            onConfirm={handleConfirm}
            onCancel={handleCancel}
            onTradeComplete={handleTradeComplete}
            onRetry={handleRetry}
            onTicketExecuted={handleTicketExecuted}
            onTicketCancelled={handleTicketCancelled}
            confirmingIds={new Set(confirmingRef.current)}
            messagesEndRef={messagesEndRef}
          />

          {/* Composer */}
          <ChatComposer
            inputText={inputText}
            onInputChange={(e) => setInputText(e.target.value)}
            onSend={handleSend}
            onKeyDown={handleKeyDown}
            loading={loading}
            textareaRef={textareaRef}
          />
        </div>

        {/* Steps Drawer */}
        <StepsDrawer
          steps={steps}
          isOpen={stepsDrawerOpen}
          onClose={() => setStepsDrawerOpen(false)}
          runId={currentRunId || undefined}
        />
      </div>
    </div>
  );
}
