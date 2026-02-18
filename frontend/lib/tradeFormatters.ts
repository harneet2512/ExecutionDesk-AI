/**
 * Trade formatting utilities for consistent display across the UI.
 * Fixes Bug 1: SELL flow showing "BUY BTC" due to fallback defaults.
 */

export type TradeSide = 'BUY' | 'SELL' | '';

/**
 * Normalizes trade side to uppercase.
 * Returns empty string if side is missing/invalid rather than defaulting to BUY.
 */
export function formatTradeSide(side: string | undefined | null): TradeSide {
  if (!side) return '';
  const normalized = side.trim().toUpperCase();
  if (normalized === 'BUY' || normalized === 'SELL') {
    return normalized;
  }
  return '';
}

/**
 * Formats trade title for display in banners/cards.
 * Shows "Processing trade..." when side is unknown instead of defaulting to BUY.
 */
export function formatTradeTitle(params: {
  side?: string;
  symbol?: string;
  notional?: number;
  mode?: string;
}): string {
  const { side, symbol, notional, mode } = params;
  const normalizedSide = formatTradeSide(side);
  
  if (!normalizedSide) {
    return 'Processing trade...';
  }
  
  const fmtAmount = typeof notional === 'number' && isFinite(notional) && notional > 0
    ? `$${notional.toFixed(2)} `
    : '';
  const fmtSymbol = symbol || 'ASSET';
  
  return `${normalizedSide} ${fmtAmount}${fmtSymbol}`;
}

/**
 * Maps order status to human-readable outcome text.
 * Used by TradeReceipt and completion banners.
 */
export function formatTradeOutcome(orderStatus: string | undefined | null): {
  text: string;
  type: 'success' | 'pending' | 'failed' | 'cancelled' | 'unknown';
} {
  if (!orderStatus) {
    return { text: 'Unknown', type: 'unknown' };
  }
  
  const status = orderStatus.toUpperCase();
  
  switch (status) {
    case 'FILLED':
    case 'COMPLETED':
      return { text: 'Trade Executed', type: 'success' };
    case 'SUBMITTED':
    case 'PENDING':
    case 'OPEN':
      return { text: 'Order submitted (pending fill confirmation).', type: 'pending' };
    case 'FAILED':
    case 'REJECTED':
      return { text: 'Trade Failed', type: 'failed' };
    case 'CANCELED':
    case 'CANCELLED':
    case 'EXPIRED':
      return { text: 'Order Cancelled', type: 'cancelled' };
    default:
      return { text: 'Processing', type: 'unknown' };
  }
}

/**
 * Formats order ID for display.
 * For PAPER mode, shows truncated internal ID.
 * For LIVE mode, shows full broker ID.
 */
export function formatOrderId(orderId: string | undefined | null, mode?: string): string {
  if (!orderId) return 'N/A';
  
  // Check if it's an internal paper order ID (typically UUID format)
  const isPaperFormat = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(orderId);
  
  if (isPaperFormat && mode?.toUpperCase() === 'PAPER') {
    // Truncate internal UUIDs for display
    return orderId.substring(0, 8) + '...';
  }
  
  // LIVE orders: show full broker ID
  return orderId;
}

/**
 * Gets side display color class.
 */
export function getSideColorClass(side: TradeSide, variant: 'text' | 'bg' = 'text'): string {
  if (variant === 'bg') {
    if (side === 'SELL') return 'bg-[var(--color-status-error)]/20';
    if (side === 'BUY') return 'bg-[var(--color-status-success)]/20';
    return 'bg-neutral-500/20';
  }

  if (side === 'SELL') return 'text-[var(--color-status-error)]';
  if (side === 'BUY') return 'text-[var(--color-status-success)]';
  return 'theme-text-secondary';
}
