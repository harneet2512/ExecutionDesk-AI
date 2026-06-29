'use client';

import { useEffect, useState } from 'react';
import { useWebSocket, ReadyState } from '@/lib/useWebSocket';

interface OrderBookLevel {
  price: number;
  size: number;
}

interface OrderBookProps {
  /** Symbol to display, e.g. "BTC-USD". */
  symbol: string;
  /** Max number of levels to show on each side (default: 10). */
  depth?: number;
}

/**
 * Real-time order book display with color-coded bids (green) and asks (red),
 * size bars, and mid-price / spread display.
 *
 * Subscribes to the `book:<symbol>` WebSocket channel and updates in place.
 */
export default function OrderBook({ symbol, depth = 10 }: OrderBookProps) {
  const [bids, setBids] = useState<OrderBookLevel[]>([]);
  const [asks, setAsks] = useState<OrderBookLevel[]>([]);
  const { lastMessage, subscribe, unsubscribe, readyState } = useWebSocket();

  // Subscribe on mount / symbol change
  useEffect(() => {
    const channel = `book:${symbol}`;
    subscribe(channel);
    return () => { unsubscribe(channel); };
  }, [symbol, subscribe, unsubscribe]);

  // Process incoming messages
  useEffect(() => {
    if (!lastMessage) return;
    if (lastMessage.type !== 'book' && lastMessage.type !== 'price') return;
    if (lastMessage.symbol !== symbol) return;

    if (lastMessage.bids) {
      setBids(
        (lastMessage.bids as OrderBookLevel[])
          .slice(0, depth)
          .sort((a, b) => b.price - a.price)
      );
    }
    if (lastMessage.asks) {
      setAsks(
        (lastMessage.asks as OrderBookLevel[])
          .slice(0, depth)
          .sort((a, b) => a.price - b.price)
      );
    }
  }, [lastMessage, symbol, depth]);

  // Derived values
  const bestBid = bids.length > 0 ? bids[0].price : null;
  const bestAsk = asks.length > 0 ? asks[0].price : null;
  const spread = bestBid !== null && bestAsk !== null ? bestAsk - bestBid : null;
  const midPrice = bestBid !== null && bestAsk !== null ? (bestBid + bestAsk) / 2 : null;
  const maxSize = Math.max(
    ...bids.map((l) => l.size),
    ...asks.map((l) => l.size),
    1
  );

  const formatPrice = (p: number) =>
    typeof p === 'number' && isFinite(p) ? p.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : '—';
  const formatSize = (s: number) =>
    typeof s === 'number' && isFinite(s) ? s.toFixed(4) : '—';

  const isConnected = readyState === ReadyState.OPEN;

  return (
    <div className="rounded-lg border bg-neutral-surface text-neutral-text-primary border-neutral-border p-4">
      {/* Header */}
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-semibold text-neutral-text-primary">
          Order Book &middot; {symbol}
        </h3>
        <span
          className={`inline-block h-2 w-2 rounded-full ${isConnected ? 'bg-[var(--color-status-success)]' : 'bg-[var(--color-status-error)]'}`}
          title={isConnected ? 'Connected' : 'Disconnected'}
        />
      </div>

      {/* Spread / mid-price bar */}
      {midPrice !== null && (
        <div className="flex justify-between text-xs text-neutral-text-muted mb-2">
          <span>Mid: {formatPrice(midPrice)}</span>
          {spread !== null && (
            <span>Spread: {formatPrice(spread)}</span>
          )}
        </div>
      )}

      {/* Asks (reversed so lowest ask is at bottom, closest to mid) */}
      <div className="space-y-px mb-1">
        {(asks.length > 0 ? [...asks].reverse() : ([] as (OrderBookLevel | null)[])).map((level, i) => {
          const price = level?.price;
          const size = level?.size ?? 0;
          const barWidth = maxSize > 0 ? (size / maxSize) * 100 : 0;
          return (
            <div key={`ask-${i}`} className="relative flex justify-between text-xs font-mono py-0.5 px-2">
              <div
                className="absolute inset-y-0 right-0 opacity-15"
                style={{
                  width: `${barWidth}%`,
                  backgroundColor: 'var(--color-status-error)',
                }}
              />
              <span className="relative z-10" style={{ color: 'var(--color-status-error)' }}>
                {price != null ? formatPrice(price) : '—'}
              </span>
              <span className="relative z-10 text-neutral-text-secondary">
                {size > 0 ? formatSize(size) : '—'}
              </span>
            </div>
          );
        })}
      </div>

      {/* Bids */}
      <div className="space-y-px mt-1">
        {(bids.length > 0 ? bids : ([] as (OrderBookLevel | null)[])).map((level, i) => {
          const price = level?.price;
          const size = level?.size ?? 0;
          const barWidth = maxSize > 0 ? (size / maxSize) * 100 : 0;
          return (
            <div key={`bid-${i}`} className="relative flex justify-between text-xs font-mono py-0.5 px-2">
              <div
                className="absolute inset-y-0 right-0 opacity-15"
                style={{
                  width: `${barWidth}%`,
                  backgroundColor: 'var(--color-status-success)',
                }}
              />
              <span className="relative z-10" style={{ color: 'var(--color-status-success)' }}>
                {price != null ? formatPrice(price) : '—'}
              </span>
              <span className="relative z-10 text-neutral-text-secondary">
                {size > 0 ? formatSize(size) : '—'}
              </span>
            </div>
          );
        })}
      </div>

      {/* Disconnected notice */}
      {!isConnected && (
        <div className="mt-2 text-xs text-neutral-text-muted text-center">
          Reconnecting...
        </div>
      )}
    </div>
  );
}
