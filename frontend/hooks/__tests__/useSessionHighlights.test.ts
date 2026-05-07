// @vitest-environment happy-dom
import { describe, it, expect, vi, afterEach, beforeEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useSessionHighlights } from "../useSessionHighlights";
import type { SessionInfo } from "@/lib/api/types";

const capturedHandlers = new Map<string, (event: unknown) => void>();

vi.mock("@/lib/ws/WebSocketProvider", () => ({
  useWS: () => ({
    onEvent: (type: string, handler: (event: unknown) => void) => {
      capturedHandlers.set(type, handler);
      return () => capturedHandlers.delete(type);
    },
  }),
}));

const sessions: SessionInfo[] = [
  {
    session_id: "sess-1",
    detached: false,
    title: "Session Alpha",
    status: "running",
    active_agent: "claude",
    last_input: "Run planner",
    project_path: "/work/project",
    computer: "local",
  },
];

function installLocalStorageMock() {
  const store = new Map<string, string>();

  Object.defineProperty(window, "localStorage", {
    configurable: true,
    value: {
      getItem: (key: string) => store.get(key) ?? null,
      setItem: (key: string, value: string) => {
        store.set(key, value);
      },
      removeItem: (key: string) => {
        store.delete(key);
      },
      clear: () => {
        store.clear();
      },
    },
  });

  return store;
}

function emit(type: string, event: unknown) {
  const handler = capturedHandlers.get(type);
  if (!handler) {
    throw new Error(`No handler registered for ${type}`);
  }
  act(() => {
    handler(event);
  });
}

describe("useSessionHighlights", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    installLocalStorageMock();
  });

  afterEach(() => {
    capturedHandlers.clear();
    vi.clearAllMocks();
    vi.useRealTimers();
  });

  it("keeps non-preview output highlights until the session is opened", () => {
    const { result, rerender } = renderHook(
      ({ activeSessionId }: { activeSessionId: string | null }) =>
        useSessionHighlights(sessions, activeSessionId),
      { initialProps: { activeSessionId: null as string | null } },
    );

    emit("agent_activity", {
      event: "agent_activity",
      session_id: "sess-1",
      type: "agent_stop",
      summary: "Build complete",
      timestamp: "2026-03-30T12:05:00Z",
    });

    expect(result.current.get("sess-1")?.highlightType).toBe("output");
    expect(result.current.get("sess-1")?.lastOutputSummary).toBe("Build complete");

    act(() => {
      vi.advanceTimersByTime(3_100);
    });

    expect(result.current.get("sess-1")?.highlightType).toBe("output");

    act(() => {
      rerender({ activeSessionId: "sess-1" });
    });

    expect(result.current.get("sess-1")?.highlightType).toBeNull();
    expect(result.current.get("sess-1")?.lastOutputSummary).toBe("Build complete");
  });

  it("auto-clears preview-session highlights after three seconds", () => {
    const { result } = renderHook(() =>
      useSessionHighlights(sessions, "sess-1"),
    );

    emit("agent_activity", {
      event: "agent_activity",
      session_id: "sess-1",
      type: "user_prompt_submit",
      timestamp: "2026-03-30T12:06:00Z",
    });

    expect(result.current.get("sess-1")?.highlightType).toBe("input");
    expect(result.current.get("sess-1")?.activityEvent).toBe("user_prompt_submit");

    act(() => {
      vi.advanceTimersByTime(3_100);
    });

    expect(result.current.get("sess-1")?.highlightType).toBeNull();
    expect(result.current.get("sess-1")?.activityEvent).toBe("user_prompt_submit");
  });

  it("removes highlight state when the session closes", () => {
    const { result } = renderHook(() =>
      useSessionHighlights(sessions, null),
    );

    emit("agent_activity", {
      event: "agent_activity",
      session_id: "sess-1",
      type: "agent_stop",
      summary: "Done",
      timestamp: "2026-03-30T12:07:00Z",
    });
    expect(result.current.get("sess-1")?.lastOutputSummary).toBe("Done");

    emit("session_closed", {
      event: "session_closed",
      data: { session_id: "sess-1" },
    });

    expect(result.current.get("sess-1")).toBeUndefined();
  });

});
