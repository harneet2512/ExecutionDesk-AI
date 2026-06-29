import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import IconRail from '../../components/IconRail';

// Mock next/navigation
const pushMock = vi.fn();
const pathnameMock = vi.fn(() => '/');

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: pushMock }),
  usePathname: () => pathnameMock(),
}));

describe('IconRail', () => {
  const defaultProps = {
    darkMode: true,
    onToggleDarkMode: vi.fn(),
    chatPanelOpen: false,
    onToggleChatPanel: vi.fn(),
  };

  beforeEach(() => {
    pushMock.mockClear();
    pathnameMock.mockReturnValue('/');
    defaultProps.onToggleDarkMode.mockClear();
    defaultProps.onToggleChatPanel.mockClear();
  });

  it('renders all navigation items with SVG icons (no emoji)', () => {
    const { container } = render(<IconRail {...defaultProps} />);
    const svgs = container.querySelectorAll('svg');
    // 8 nav icons + 1 chat panel toggle + 1 dark mode toggle = 10 SVGs minimum
    expect(svgs.length).toBeGreaterThanOrEqual(10);
    // No emoji text nodes in nav buttons
    const buttons = screen.getAllByRole('button');
    buttons.forEach((btn) => {
      const textContent = btn.textContent || '';
      // Should not contain common emoji characters
      expect(textContent).not.toMatch(/[\u{1F600}-\u{1F64F}\u{1F300}-\u{1F5FF}\u{1F680}-\u{1F6FF}\u{2600}-\u{26FF}\u{2700}-\u{27BF}]/u);
    });
  });

  it('renders all navigation labels', () => {
    render(<IconRail {...defaultProps} />);
    expect(screen.getByLabelText('Home')).toBeInTheDocument();
    expect(screen.getByLabelText('Chats')).toBeInTheDocument();
    expect(screen.getByLabelText('Trades')).toBeInTheDocument();
    expect(screen.getByLabelText('Evals')).toBeInTheDocument();
    expect(screen.getByLabelText('Telemetry')).toBeInTheDocument();
    expect(screen.getByLabelText('Operations')).toBeInTheDocument();
    expect(screen.getByLabelText('Markets')).toBeInTheDocument();
    expect(screen.getByLabelText('Clients')).toBeInTheDocument();
  });

  it('calls router.push when a nav item is clicked', () => {
    render(<IconRail {...defaultProps} />);
    fireEvent.click(screen.getByLabelText('Trades'));
    expect(pushMock).toHaveBeenCalledWith('/runs');
  });

  it('navigates to correct routes for each nav item', () => {
    render(<IconRail {...defaultProps} />);

    fireEvent.click(screen.getByLabelText('Home'));
    expect(pushMock).toHaveBeenCalledWith('/');

    fireEvent.click(screen.getByLabelText('Chats'));
    expect(pushMock).toHaveBeenCalledWith('/chat');

    fireEvent.click(screen.getByLabelText('Evals'));
    expect(pushMock).toHaveBeenCalledWith('/evals');

    fireEvent.click(screen.getByLabelText('Telemetry'));
    expect(pushMock).toHaveBeenCalledWith('/performance');

    fireEvent.click(screen.getByLabelText('Operations'));
    expect(pushMock).toHaveBeenCalledWith('/ops');

    fireEvent.click(screen.getByLabelText('Markets'));
    expect(pushMock).toHaveBeenCalledWith('/markets');

    fireEvent.click(screen.getByLabelText('Clients'));
    expect(pushMock).toHaveBeenCalledWith('/clients');
  });

  it('highlights the active nav item based on pathname', () => {
    pathnameMock.mockReturnValue('/evals');
    render(<IconRail {...defaultProps} />);
    const evalsBtn = screen.getByLabelText('Evals');
    expect(evalsBtn.className).toContain('theme-elevated');
  });

  it('highlights Home only for exact "/" pathname', () => {
    pathnameMock.mockReturnValue('/');
    render(<IconRail {...defaultProps} />);
    const homeBtn = screen.getByLabelText('Home');
    expect(homeBtn.className).toContain('theme-elevated');
    // Chats should not be highlighted
    const chatsBtn = screen.getByLabelText('Chats');
    expect(chatsBtn.className).not.toContain('theme-elevated');
  });

  it('highlights sub-routes correctly', () => {
    pathnameMock.mockReturnValue('/runs/abc-123');
    render(<IconRail {...defaultProps} />);
    const tradesBtn = screen.getByLabelText('Trades');
    expect(tradesBtn.className).toContain('theme-elevated');
  });

  it('renders dark mode toggle with aria-label', () => {
    render(<IconRail {...defaultProps} darkMode={true} />);
    expect(screen.getByLabelText('Switch to light mode')).toBeInTheDocument();
  });

  it('calls onToggleDarkMode when toggle is clicked', () => {
    render(<IconRail {...defaultProps} />);
    fireEvent.click(screen.getByLabelText('Switch to light mode'));
    expect(defaultProps.onToggleDarkMode).toHaveBeenCalled();
  });

  it('renders chat panel toggle button', () => {
    render(<IconRail {...defaultProps} chatPanelOpen={false} />);
    expect(screen.getByLabelText('Show Chat Panel')).toBeInTheDocument();
  });

  it('calls onToggleChatPanel when chat panel toggle is clicked', () => {
    render(<IconRail {...defaultProps} />);
    fireEvent.click(screen.getByLabelText('Show Chat Panel'));
    expect(defaultProps.onToggleChatPanel).toHaveBeenCalled();
  });

  it('shows correct label when chat panel is open', () => {
    render(<IconRail {...defaultProps} chatPanelOpen={true} />);
    expect(screen.getByLabelText('Hide Chat Panel')).toBeInTheDocument();
  });
});
