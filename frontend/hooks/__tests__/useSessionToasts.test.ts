// @vitest-environment happy-dom
import { describe, it, expect, vi, afterEach } from 'vitest';
import { renderHook } from '@testing-library/react';

// Track captured handlers
const capturedHandlers = new Map<string, Function>();

vi.mock('@/lib/ws/WebSocketProvider', () => ({
  useWS: () => ({
    onEvent: (type: string, handler: Function) => {
      capturedHandlers.set(type, handler);
      return () => capturedHandlers.delete(type);
    },
  }),
}));

const { toastMock } = vi.hoisted(() => ({
  toastMock: {
    success: vi.fn(),
    info: vi.fn(),
  },
}));

vi.mock('sonner', () => ({
  toast: toastMock,
}));

// Import after mocks
import { useSessionToasts } from '../useSessionToasts';

describe('useSessionToasts', () => {
  afterEach(() => {
    capturedHandlers.clear();
    vi.clearAllMocks();
  });

  it('registers handlers for session_started and session_closed', () => {
    renderHook(() => useSessionToasts());
    expect(capturedHandlers.has('session_started')).toBe(true);
    expect(capturedHandlers.has('session_closed')).toBe(true);
  });

  it('calls toast.success when session_started event fires', () => {
    renderHook(() => useSessionToasts());
    const handler = capturedHandlers.get('session_started')!;
    handler({ event: 'session_started', data: { session_id: 'sess-1', title: 'My Session' } });
    expect(toastMock.success).toHaveBeenCalledTimes(1);
  });

  it('calls toast.info when session_closed event fires', () => {
    renderHook(() => useSessionToasts());
    const handler = capturedHandlers.get('session_closed')!;
    handler({ event: 'session_closed', data: { session_id: 'sess-1' } });
    expect(toastMock.info).toHaveBeenCalledTimes(1);
  });

  it('cleans up event handlers on unmount', () => {
    const { unmount } = renderHook(() => useSessionToasts());
    expect(capturedHandlers.has('session_started')).toBe(true);
    unmount();
    expect(capturedHandlers.has('session_started')).toBe(false);
  });
});
