import { render } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import PageSkeleton from '../../components/PageSkeleton';

describe('PageSkeleton', () => {
  it('renders with pulse animation', () => {
    const { container } = render(<PageSkeleton />);
    expect(container.querySelector('.animate-pulse')).toBeInTheDocument();
  });

  it('renders default number of skeleton rows', () => {
    const { container } = render(<PageSkeleton />);
    const rows = container.querySelectorAll('.space-y-3 > div');
    expect(rows.length).toBe(4);
  });

  it('renders custom number of rows', () => {
    const { container } = render(<PageSkeleton rows={6} />);
    const rows = container.querySelectorAll('.space-y-3 > div');
    expect(rows.length).toBe(6);
  });

  it('renders three metric cards', () => {
    const { container } = render(<PageSkeleton />);
    const cards = container.querySelectorAll('.grid > div');
    expect(cards.length).toBe(3);
  });
});
