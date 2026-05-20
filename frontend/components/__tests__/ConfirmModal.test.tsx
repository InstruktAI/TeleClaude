// @vitest-environment happy-dom
import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup } from '@testing-library/react';
import { ConfirmModal } from '../ConfirmModal';

describe('ConfirmModal', () => {
  afterEach(() => cleanup());

  it('renders title and message text', () => {
    render(
      <ConfirmModal
        open={true}
        onOpenChange={vi.fn()}
        title="Confirm Delete"
        message="Are you sure?"
        onConfirm={vi.fn()}
      />,
    );
    expect(screen.getByText('Confirm Delete')).toBeDefined();
    expect(screen.getByText('Are you sure?')).toBeDefined();
  });

  it('clicking Yes calls the onConfirm callback', () => {
    const onConfirm = vi.fn();
    const onOpenChange = vi.fn();
    render(
      <ConfirmModal open={true} onOpenChange={onOpenChange} title="Confirm" message="Proceed?" onConfirm={onConfirm} />,
    );
    fireEvent.click(screen.getByText('Yes'));
    expect(onConfirm).toHaveBeenCalledTimes(1);
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it('clicking No calls onOpenChange(false) without calling onConfirm', () => {
    const onConfirm = vi.fn();
    const onOpenChange = vi.fn();
    render(
      <ConfirmModal open={true} onOpenChange={onOpenChange} title="Confirm" message="Proceed?" onConfirm={onConfirm} />,
    );
    fireEvent.click(screen.getByText('No'));
    expect(onOpenChange).toHaveBeenCalledWith(false);
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it('does not render when open is false', () => {
    render(<ConfirmModal open={false} onOpenChange={vi.fn()} title="Confirm" message="Proceed?" onConfirm={vi.fn()} />);
    expect(screen.queryByText('Confirm')).toBeNull();
  });
});
