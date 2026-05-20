// @vitest-environment happy-dom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, waitFor, cleanup, act } from '@testing-library/react';
import { MyRuntimeProvider } from '../MyRuntimeProvider';

const handlers = new Map<string, (event: unknown) => void>();

const { setMessagesMock, transportSetRuntimeMock, fetchMock } = vi.hoisted(() => ({
  setMessagesMock: vi.fn(),
  transportSetRuntimeMock: vi.fn(),
  fetchMock: vi.fn(),
}));

vi.mock('@assistant-ui/react', () => ({
  AssistantRuntimeProvider: ({ children }: { children: React.ReactNode; runtime: unknown }) => <>{children}</>,
}));

vi.mock('@assistant-ui/react-ai-sdk', () => ({
  AssistantChatTransport: class {
    constructor(_opts: unknown) {}

    setRuntime = transportSetRuntimeMock;
  },
  useAISDKRuntime: () => ({ runtime: 'mock' }),
}));

vi.mock('@ai-sdk/react', () => ({
  useChat: () => ({
    setMessages: setMessagesMock,
    status: 'ready',
  }),
}));

vi.mock('@tanstack/react-query', () => ({
  useQuery: () => ({
    data: [],
  }),
}));

vi.mock('@/hooks/useSessionAgent', () => ({
  SessionAgentProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

vi.mock('@/lib/ws/WebSocketProvider', () => ({
  useWS: () => ({
    onEvent: (type: string, handler: (event: unknown) => void) => {
      handlers.set(type, handler);
      return () => handlers.delete(type);
    },
  }),
}));

function emit(type: string, event: unknown) {
  const handler = handlers.get(type);
  if (!handler) {
    throw new Error(`No handler registered for ${type}`);
  }
  act(() => {
    handler(event);
  });
}

describe('MyRuntimeProvider', () => {
  beforeEach(() => {
    setMessagesMock.mockReset();
    transportSetRuntimeMock.mockReset();
    fetchMock.mockReset();
    handlers.clear();
    vi.stubGlobal('fetch', fetchMock);
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    vi.clearAllMocks();
  });

  it('loads initial history and refreshes the open thread on matching agent activity', async () => {
    fetchMock
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          messages: [
            {
              role: 'assistant',
              type: 'text',
              text: 'Initial output',
              file_index: 0,
              entry_index: 0,
            },
          ],
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          messages: [
            {
              role: 'assistant',
              type: 'text',
              text: 'Initial output',
              file_index: 0,
              entry_index: 0,
            },
            {
              role: 'assistant',
              type: 'text',
              text: 'Fresh output',
              file_index: 0,
              entry_index: 1,
            },
          ],
        }),
      });

    render(
      <MyRuntimeProvider sessionId="sess-1">
        <div>child</div>
      </MyRuntimeProvider>,
    );

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledTimes(1);
    });
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/sessions/sess-1/messages',
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );

    await waitFor(() => {
      expect(setMessagesMock).toHaveBeenCalledTimes(1);
    });
    expect(setMessagesMock.mock.calls[0]?.[0]).toMatchObject([
      {
        role: 'assistant',
        parts: [{ type: 'text', text: 'Initial output' }],
      },
    ]);

    emit('agent_activity', {
      event: 'agent_activity',
      session_id: 'sess-1',
      type: 'agent_stop',
      timestamp: '2026-03-31T17:17:37Z',
    });

    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 300));
    });

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledTimes(2);
    });
    await waitFor(() => {
      expect(setMessagesMock).toHaveBeenCalledTimes(2);
    });
    expect(setMessagesMock.mock.calls[1]?.[0]).toMatchObject([
      {
        role: 'assistant',
        parts: [{ type: 'text', text: 'Initial output\n\nFresh output' }],
      },
    ]);
  });

  it('refreshes the open thread on tool-use activity when the browser chat is idle', async () => {
    fetchMock
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          messages: [
            {
              role: 'assistant',
              type: 'text',
              text: 'Existing output',
              file_index: 0,
              entry_index: 0,
            },
          ],
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          messages: [
            {
              role: 'assistant',
              type: 'text',
              text: 'Existing output',
              file_index: 0,
              entry_index: 0,
            },
            {
              role: 'assistant',
              type: 'text',
              text: 'Tool-triggered output',
              file_index: 0,
              entry_index: 1,
            },
          ],
        }),
      });

    render(
      <MyRuntimeProvider sessionId="sess-1">
        <div>child</div>
      </MyRuntimeProvider>,
    );

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledTimes(1);
    });

    emit('agent_activity', {
      event: 'agent_activity',
      session_id: 'sess-1',
      type: 'tool_use',
      tool_name: 'run_shell_command',
      tool_preview: 'grep -rn',
      timestamp: '2026-03-31T17:17:37Z',
    });

    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 300));
    });

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledTimes(2);
    });
    await waitFor(() => {
      expect(setMessagesMock).toHaveBeenCalledTimes(2);
    });
    expect(setMessagesMock.mock.calls[1]?.[0]).toMatchObject([
      {
        role: 'assistant',
        parts: [{ type: 'text', text: 'Existing output\n\nTool-triggered output' }],
      },
    ]);
  });

  it('ignores agent activity for other sessions', async () => {
    fetchMock.mockResolvedValue({
      ok: true,
      json: async () => ({
        messages: [],
      }),
    });

    render(
      <MyRuntimeProvider sessionId="sess-1">
        <div>child</div>
      </MyRuntimeProvider>,
    );

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledTimes(1);
    });
    await waitFor(() => {
      expect(setMessagesMock).toHaveBeenCalledWith([]);
    });

    emit('agent_activity', {
      event: 'agent_activity',
      session_id: 'sess-2',
      type: 'agent_stop',
      timestamp: '2026-03-31T17:17:37Z',
    });

    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 300));
    });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(setMessagesMock).toHaveBeenCalledTimes(1);
  });
});
