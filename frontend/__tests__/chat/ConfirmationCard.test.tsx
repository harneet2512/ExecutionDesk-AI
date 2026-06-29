import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import ConfirmationCard from '../../components/chat/ConfirmationCard';

// Mock the child components that ConfirmationCard renders
vi.mock('../../components/SelectionPanel', () => ({
  default: ({ selection }: any) => (
    <div data-testid="selection-panel">{JSON.stringify(selection)}</div>
  ),
}));

vi.mock('../../components/FinancialInsightCard', () => ({
  default: ({ insight, newsEnabled }: any) => (
    <div data-testid="financial-insight-card">
      {insight ? 'insight-present' : 'no-insight'}
    </div>
  ),
}));

describe('ConfirmationCard', () => {
  const baseMetadata = {
    intent: 'TRADE_CONFIRMATION_PENDING' as const,
    confirmation_id: 'conf_abc123',
    pending_trade: {
      side: 'BUY',
      asset: 'BTC',
      amount_usd: 100,
      mode: 'PAPER',
    },
    preconfirm_insight: null,
    financial_insight: null,
    selection_result: null,
    news_enabled: true,
    status: 'PENDING',
  };

  const defaultProps = {
    messageId: 'msg_1',
    metadata: baseMetadata,
    onConfirm: vi.fn(),
    onCancel: vi.fn(),
    confirming: false,
    loading: false,
    capabilities: { live_trading_enabled: true, paper_trading_enabled: true, insights_enabled: true, news_enabled: true, db_ready: true },
    healthStatus: null as any,
    newsEnabled: true,
  };

  it('renders confirm and cancel buttons', () => {
    render(<ConfirmationCard {...defaultProps} />);
    expect(screen.getByRole('button', { name: /confirm trade/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /cancel/i })).toBeInTheDocument();
  });

  it('calls onConfirm with correct confirmation_id', () => {
    const onConfirm = vi.fn();
    render(<ConfirmationCard {...defaultProps} onConfirm={onConfirm} />);
    fireEvent.click(screen.getByRole('button', { name: /confirm trade/i }));
    expect(onConfirm).toHaveBeenCalledWith('conf_abc123');
  });

  it('calls onCancel with correct confirmation_id', () => {
    const onCancel = vi.fn();
    render(<ConfirmationCard {...defaultProps} onCancel={onCancel} />);
    fireEvent.click(screen.getByRole('button', { name: /cancel/i }));
    expect(onCancel).toHaveBeenCalledWith('conf_abc123');
  });

  it('disables buttons when loading', () => {
    render(<ConfirmationCard {...defaultProps} loading={true} />);
    expect(screen.getByRole('button', { name: /confirm trade/i })).toBeDisabled();
    expect(screen.getByRole('button', { name: /cancel/i })).toBeDisabled();
  });

  it('disables buttons when confirming', () => {
    render(<ConfirmationCard {...defaultProps} confirming={true} />);
    expect(screen.getByRole('button', { name: /confirm trade/i })).toBeDisabled();
    expect(screen.getByRole('button', { name: /cancel/i })).toBeDisabled();
  });

  it('disables buttons when confirmation_id is missing', () => {
    const metadata = { ...baseMetadata, confirmation_id: undefined };
    render(<ConfirmationCard {...defaultProps} metadata={metadata as any} />);
    expect(screen.getByRole('button', { name: /confirm trade/i })).toBeDisabled();
    expect(screen.getByRole('button', { name: /cancel/i })).toBeDisabled();
  });

  it('shows LIVE-disabled message instead of buttons for LIVE trades when live trading is off', () => {
    const metadata = {
      ...baseMetadata,
      pending_trade: { ...baseMetadata.pending_trade, mode: 'LIVE' },
    };
    const capabilities = { ...defaultProps.capabilities, live_trading_enabled: false };
    render(
      <ConfirmationCard {...defaultProps} metadata={metadata} capabilities={capabilities} />
    );
    expect(screen.queryByRole('button', { name: /confirm trade/i })).not.toBeInTheDocument();
    expect(screen.getByText(/confirm it in your Coinbase wallet/i)).toBeInTheDocument();
  });

  it('renders SelectionPanel when selection_result is present', () => {
    const metadata = {
      ...baseMetadata,
      selection_result: { selected_symbol: 'BTC', selected_return_pct: 0.95, top_candidates: [], universe_description: 'test', window_description: 'test', why_explanation: 'test', fallback_used: false, lookback_hours: 24, universe_size: 10, evaluated_count: 5 },
    };
    render(<ConfirmationCard {...defaultProps} metadata={metadata} />);
    expect(screen.getByTestId('selection-panel')).toBeInTheDocument();
  });

  it('renders FinancialInsightCard', () => {
    render(<ConfirmationCard {...defaultProps} />);
    expect(screen.getByTestId('financial-insight-card')).toBeInTheDocument();
  });

  it('shows error message when confirmation_id is missing', () => {
    const metadata = { ...baseMetadata, confirmation_id: undefined };
    render(<ConfirmationCard {...defaultProps} metadata={metadata as any} />);
    expect(screen.getByText(/missing confirmation id/i)).toBeInTheDocument();
  });
});
