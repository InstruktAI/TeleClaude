// @vitest-environment happy-dom
import { describe, it, expect, vi, afterEach, beforeEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useLiveSessions } from "../useLiveSessions";

const capturedHandlers = new Map<string, (event: unknown) => void>();

const {
  sessionsData,
  refetchMock,
} = vi.hoisted(() => ({
  sessionsData: [
    {
      session_id: "sess-1",
      title: "Session Alpha",
      status: "running",
      active_agent: "claude",
      project_path: "/work/project",
      computer: "local",
      last_activity: "2026-03-30T12:00:00Z",
    },
  ],
  refetchMock: vi.fn(),
}));

vi.mock("@/lib/hooks/useSessions", () => ({
  useSessions: () => ({
    data: sessionsData,
    isLoading: false,
    error: null,
    refetch: refetchMock,
  }),
}));

vi.mock("@/lib/ws/WebSocketProvider", () => ({
  useWS: () => ({
    onEvent: (type: string, handler: (event: unknown) => void) => {
      capturedHandlers.set(type, handler);
      return () => capturedHandlers.delete(type);
    },
  }),
}));

function emit(type: string, event: unknown) {
  const handler = capturedHandlers.get(type);
  if (!handler) {
    throw new Error(`No handler registered for ${type}`);
  }
  act(() => {
    handler(event);
  });
}

describe("useLiveSessions", () => {
  beforeEach(() => {
    refetchMock.mockReset();
  });

  afterEach(() => {
    capturedHandlers.clear();
    vi.clearAllMocks();
  });

  it("starts from the query snapshot", () => {
    const { result } = renderHook(() => useLiveSessions());
    expect(result.current.data).toHaveLength(1);
    expect(result.current.data[0]?.session_id).toBe("sess-1");
  });

  it("upserts session updates from websocket events", () => {
    const { result } = renderHook(() => useLiveSessions());

    emit("session_updated", {
      event: "session_updated",
      data: {
        session_id: "sess-1",
        title: "Renamed Session",
        status: "active",
        active_agent: "claude",
        project_path: "/work/project",
        computer: "local",
      },
    });

    expect(result.current.data[0]?.title).toBe("Renamed Session");
    expect(result.current.data[0]?.status).toBe("active");
  });

  it("patches lifecycle status events without refetching", () => {
    const { result } = renderHook(() => useLiveSessions());

    emit("session_status", {
      event: "session_status",
      session_id: "sess-1",
      status: "active_output",
      reason: "agent_output",
      timestamp: "2026-03-30T12:03:00Z",
      last_activity_at: "2026-03-30T12:03:00Z",
    });

    expect(result.current.data[0]?.status).toBe("active_output");
    expect(result.current.data[0]?.last_activity).toBe("2026-03-30T12:03:00Z");
  });

  it("applies agent_stop activity to last activity and summary", () => {
    const { result } = renderHook(() => useLiveSessions());

    emit("agent_activity", {
      event: "agent_activity",
      session_id: "sess-1",
      type: "agent_stop",
      summary: "Build complete",
      timestamp: "2026-03-30T12:04:00Z",
    });

    expect(result.current.data[0]?.last_activity).toBe("2026-03-30T12:04:00Z");
    expect(result.current.data[0]?.last_output_summary).toBe("Build complete");
    expect(result.current.data[0]?.last_output_summary_at).toBe("2026-03-30T12:04:00Z");
  });

  it("removes closed sessions from the live list", () => {
    const { result } = renderHook(() => useLiveSessions());

    emit("session_closed", {
      event: "session_closed",
      data: { session_id: "sess-1" },
    });

    expect(result.current.data).toHaveLength(0);
  });
});
