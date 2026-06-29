import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import ChatComposer from '../../components/chat/ChatComposer';

describe('ChatComposer', () => {
  const defaultProps = {
    inputText: '',
    onInputChange: vi.fn(),
    onSend: vi.fn(),
    onKeyDown: vi.fn(),
    loading: false,
    textareaRef: { current: null } as React.RefObject<HTMLTextAreaElement>,
  };

  it('renders textarea', () => {
    render(<ChatComposer {...defaultProps} />);
    expect(
      screen.getByPlaceholderText('Ask me anything about trading...')
    ).toBeInTheDocument();
  });

  it('calls onSend on Enter', () => {
    const onKeyDown = vi.fn((e: React.KeyboardEvent<HTMLTextAreaElement>) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        defaultProps.onSend();
      }
    });
    render(
      <ChatComposer {...defaultProps} inputText="buy BTC" onKeyDown={onKeyDown} />
    );
    const textarea = screen.getByPlaceholderText('Ask me anything about trading...');
    fireEvent.keyDown(textarea, { key: 'Enter', shiftKey: false });
    expect(defaultProps.onSend).toHaveBeenCalled();
  });

  it('does NOT call onSend on Shift+Enter', () => {
    const onSend = vi.fn();
    const onKeyDown = vi.fn((e: React.KeyboardEvent<HTMLTextAreaElement>) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        onSend();
      }
    });
    render(
      <ChatComposer
        {...defaultProps}
        inputText="buy BTC"
        onSend={onSend}
        onKeyDown={onKeyDown}
      />
    );
    const textarea = screen.getByPlaceholderText('Ask me anything about trading...');
    fireEvent.keyDown(textarea, { key: 'Enter', shiftKey: true });
    expect(onSend).not.toHaveBeenCalled();
  });

  it('disables send button when loading', () => {
    render(<ChatComposer {...defaultProps} inputText="buy BTC" loading={true} />);
    const sendButton = screen.getByRole('button', { name: /send/i });
    expect(sendButton).toBeDisabled();
  });

  it('disables send button when input is empty', () => {
    render(<ChatComposer {...defaultProps} inputText="" loading={false} />);
    const sendButton = screen.getByRole('button', { name: /send/i });
    expect(sendButton).toBeDisabled();
  });

  it('disables send button when input is only whitespace', () => {
    render(<ChatComposer {...defaultProps} inputText="   " loading={false} />);
    const sendButton = screen.getByRole('button', { name: /send/i });
    expect(sendButton).toBeDisabled();
  });

  it('enables send button when input has text and not loading', () => {
    render(<ChatComposer {...defaultProps} inputText="buy BTC" loading={false} />);
    const sendButton = screen.getByRole('button', { name: /send/i });
    expect(sendButton).not.toBeDisabled();
  });

  it('calls onSend when send button is clicked', () => {
    const onSend = vi.fn();
    render(<ChatComposer {...defaultProps} inputText="buy BTC" onSend={onSend} />);
    const sendButton = screen.getByRole('button', { name: /send/i });
    fireEvent.click(sendButton);
    expect(onSend).toHaveBeenCalled();
  });

  it('calls onInputChange when textarea value changes', () => {
    const onInputChange = vi.fn();
    render(<ChatComposer {...defaultProps} onInputChange={onInputChange} />);
    const textarea = screen.getByPlaceholderText('Ask me anything about trading...');
    fireEvent.change(textarea, { target: { value: 'sell ETH' } });
    expect(onInputChange).toHaveBeenCalled();
  });

  it('disables textarea when loading', () => {
    render(<ChatComposer {...defaultProps} loading={true} />);
    const textarea = screen.getByPlaceholderText('Ask me anything about trading...');
    expect(textarea).toBeDisabled();
  });
});
