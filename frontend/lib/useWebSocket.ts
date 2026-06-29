/**
 * Custom React hook for WebSocket connections with auto-reconnect
 * and exponential backoff.
 *
 * Usage:
 *   const { lastMessage, subscribe, unsubscribe, readyState } = useWebSocket();
 *   useEffect(() => { subscribe('prices:BTC-USD'); }, [subscribe]);
 */
import { useCallback, useEffect, useRef, useState } from 'react';

/** WebSocket ready states mirroring the native enum. */
export const ReadyState = {
  CONNECTING: 0,
  OPEN: 1,
  CLOSING: 2,
  CLOSED: 3,
} as const;

export type ReadyStateValue = (typeof ReadyState)[keyof typeof ReadyState];

export interface WSMessage {
  type: string;
  [key: string]: any;
}

interface UseWebSocketOptions {
  /** Override the WS URL (default: auto-detect from window.location). */
  url?: string;
  /** Tenant ID for dev-mode auth (default: t_default). */
  tenant?: string;
  /** Max reconnection attempts before giving up (default: 10). */
  maxRetries?: number;
  /** Base delay in ms for exponential backoff (default: 1000). */
  baseDelay?: number;
  /** Maximum backoff delay in ms (default: 30000). */
  maxDelay?: number;
}

function buildWsUrl(options: UseWebSocketOptions): string {
  if (options.url) return options.url;
  if (typeof window === 'undefined') return '';

  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  // In dev, the Next.js rewrites proxy HTTP but not WS. Connect directly
  // to the backend (default port 8000).
  const backendHost = process.env.NEXT_PUBLIC_WS_URL
    || `${proto}//localhost:8000`;
  const tenant = options.tenant || 't_default';
  return `${backendHost}/api/v1/ws/market-data?tenant=${tenant}`;
}

export function useWebSocket(options: UseWebSocketOptions = {}) {
  const [readyState, setReadyState] = useState<ReadyStateValue>(ReadyState.CLOSED);
  const [lastMessage, setLastMessage] = useState<WSMessage | null>(null);
  const [connectionId, setConnectionId] = useState<string | null>(null);

  const wsRef = useRef<WebSocket | null>(null);
  const retriesRef = useRef(0);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const subscribedChannelsRef = useRef<Set<string>>(new Set());
  const unmountedRef = useRef(false);

  const maxRetries = options.maxRetries ?? 3;
  const baseDelay = options.baseDelay ?? 2000;
  const maxDelay = options.maxDelay ?? 15000;

  // Stable connect function ------------------------------------------------
  const connect = useCallback(() => {
    if (unmountedRef.current) return;
    const url = buildWsUrl(options);
    if (!url) return;

    // Prevent double-connect
    if (wsRef.current && (wsRef.current.readyState === WebSocket.CONNECTING || wsRef.current.readyState === WebSocket.OPEN)) {
      return;
    }

    setReadyState(ReadyState.CONNECTING);
    const ws = new WebSocket(url);

    ws.onopen = () => {
      if (unmountedRef.current) { ws.close(); return; }
      setReadyState(ReadyState.OPEN);
      retriesRef.current = 0;

      // Re-subscribe to channels that were active before a reconnect
      Array.from(subscribedChannelsRef.current).forEach((ch) => {
        ws.send(JSON.stringify({ action: 'subscribe', channel: ch }));
      });
    };

    ws.onmessage = (event) => {
      if (unmountedRef.current) return;
      try {
        const data: WSMessage = JSON.parse(event.data);
        if (data.type === 'connected') {
          setConnectionId(data.connection_id ?? null);
        }
        // Ignore heartbeats in application state (they are keep-alive only)
        if (data.type !== 'heartbeat') {
          setLastMessage(data);
        }
      } catch {
        // Non-JSON message -- ignore
      }
    };

    ws.onclose = () => {
      if (unmountedRef.current) return;
      setReadyState(ReadyState.CLOSED);
      wsRef.current = null;
      scheduleReconnect();
    };

    ws.onerror = () => {
      // onerror is always followed by onclose; nothing to do here.
    };

    wsRef.current = ws;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [options.url, options.tenant]);

  // Reconnect with exponential backoff ------------------------------------
  const scheduleReconnect = useCallback(() => {
    if (unmountedRef.current) return;
    if (retriesRef.current >= maxRetries) return;

    const delay = Math.min(baseDelay * Math.pow(2, retriesRef.current) + Math.random() * 500, maxDelay);
    retriesRef.current += 1;

    reconnectTimerRef.current = setTimeout(() => {
      connect();
    }, delay);
  }, [connect, maxRetries, baseDelay, maxDelay]);

  // Subscribe / unsubscribe -----------------------------------------------
  const subscribe = useCallback((channel: string) => {
    subscribedChannelsRef.current.add(channel);
    const ws = wsRef.current;
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ action: 'subscribe', channel }));
    }
  }, []);

  const unsubscribe = useCallback((channel: string) => {
    subscribedChannelsRef.current.delete(channel);
    const ws = wsRef.current;
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ action: 'unsubscribe', channel }));
    }
  }, []);

  // Send raw message -------------------------------------------------------
  const sendMessage = useCallback((msg: Record<string, any>) => {
    const ws = wsRef.current;
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify(msg));
    }
  }, []);

  // Lifecycle ---------------------------------------------------------------
  useEffect(() => {
    unmountedRef.current = false;
    connect();

    return () => {
      unmountedRef.current = true;
      if (reconnectTimerRef.current) {
        clearTimeout(reconnectTimerRef.current);
      }
      if (wsRef.current) {
        wsRef.current.close();
        wsRef.current = null;
      }
    };
  }, [connect]);

  return {
    readyState,
    lastMessage,
    connectionId,
    subscribe,
    unsubscribe,
    sendMessage,
  };
}
