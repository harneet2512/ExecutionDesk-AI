'use client';

import { useEffect, useState, useRef } from 'react';
import { useWebSocket, ReadyState } from '@/lib/useWebSocket';

interface TickerItem {
  symbol: string;
  price: number | null;
  changePct: number | null;
}

interface PriceTickerProps {
  /** Symbols to track, e.g. ["BTC-USD", "ETH-USD", "SOL-USD"]. */
  symbols: string[];
}

/**
 * Horizontal ticker bar showing symbol, price, and change %.
 *
 * Subscribes to `prices:<symbol>` for each symbol and updates in real-time.
 * Positive changes are displayed in green, negative in red.
 */
export default function PriceTicker({ symbols }: PriceTickerProps) {
  const [tickers, setTickers] = useState<Record<string, TickerItem>>({});
  const { lastMessage, subscribe, unsubscribe, readyState } = useWebSocket();
  const prevSymbolsRef = useRef<string[]>([]);

  // Subscribe to each symbol on mount / change
  useEffect(() => {
    const prev = prevSymbolsRef.current;
    // Unsubscribe removed symbols
    for (const s of prev) {
      if (!symbols.includes(s)) {
        unsubscribe(`prices:${s}`);
      }
    }
    // Subscribe new symbols
    for (const s of symbols) {
      if (!prev.includes(s)) {
        subscribe(`prices:${s}`);
      }
    }
    prevSymbolsRef.current = [...symbols];

    return () => {
      for (const s of symbols) {
        unsubscribe(`prices:${s}`);
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [symbols.join(','), subscribe, unsubscribe]);

  // Process price messages
  useEffect(() => {
    if (!lastMessage) return;
    if (lastMessage.type !== 'price') return;
    const sym = lastMessage.symbol as string;
    if (!sym) return;
    setTickers((prev) => ({
      ...prev,
      [sym]: {
        symbol: sym,
        price: typeof lastMessage.price === 'number' ? lastMessage.price : null,
        changePct: typeof lastMessage.change_pct === 'number' ? lastMessage.change_pct : null,
      },
    }));
  }, [lastMessage]);

  const isConnected = readyState === ReadyState.OPEN;

  const formatPrice = (p: number | null) =>
    p !== null && typeof p === 'number' && isFinite(p)
      ? p.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })
      : '—';

  const formatChange = (c: number | null) => {
    if (c === null || typeof c !== 'number' || !isFinite(c)) return '—';
    const sign = c >= 0 ? '+' : '';
    return `${sign}${c.toFixed(2)}%`;
  };

  return (
    <div className="flex items-center gap-4 overflow-x-auto py-2 px-3 rounded-lg border bg-neutral-surface border-neutral-border text-xs font-mono">
      {/* Connection indicator */}
      <span
        className={`flex-shrink-0 inline-block h-1.5 w-1.5 rounded-full ${isConnected ? 'bg-[var(--color-status-success)]' : 'bg-[var(--color-status-error)]'}`}
        title={isConnected ? 'Live' : 'Disconnected'}
      />

      {symbols.map((sym) => {
        const t = tickers[sym];
        const price = t?.price ?? null;
        const changePct = t?.changePct ?? null;
        const changeColor =
          changePct !== null && changePct >= 0
            ? 'var(--color-status-success)'
            : 'var(--color-status-error)';

        return (
          <div key={sym} className="flex items-center gap-1.5 flex-shrink-0">
            <span className="text-neutral-text-secondary font-semibold">{sym}</span>
            <span className="text-neutral-text-primary">{formatPrice(price)}</span>
            {changePct !== null && (
              <span style={{ color: changeColor }}>{formatChange(changePct)}</span>
            )}
          </div>
        );
      })}

      {symbols.length === 0 && (
        <span className="text-neutral-text-muted">No symbols configured</span>
      )}
    </div>
  );
}
