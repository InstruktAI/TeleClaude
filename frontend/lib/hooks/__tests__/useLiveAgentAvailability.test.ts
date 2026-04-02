// @vitest-environment happy-dom
import { describe, it, expect, vi, afterEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useLiveAgentAvailability } from "../useLiveAgentAvailability";

const capturedHandlers = new Map<string, (event: unknown) => void>();

vi.mock("@/lib/hooks/useAgentAvailability", () => ({
  useAgentAvailability: () => ({
    data: {
      claude: { agent: "claude", available: true, status: "available" },
    },
    isLoading: false,
    error: null,
    refetch: vi.fn(),
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

describe("useLiveAgentAvailability", () => {
  afterEach(() => {
    capturedHandlers.clear();
    vi.clearAllMocks();
  });

  it("starts from the availability query snapshot and applies websocket updates", () => {
    const { result } = renderHook(() => useLiveAgentAvailability());

    expect(result.current.data.claude?.status).toBe("available");

    emit("agent_availability", {
      event: "agent_availability",
      data: {
        agent: "codex",
        available: false,
        status: "unavailable",
        unavailable_until: "2026-04-02T12:00:00Z",
      },
    });

    expect(result.current.data.codex?.status).toBe("unavailable");
    expect(result.current.data.codex?.unavailable_until).toBe("2026-04-02T12:00:00Z");
  });
});
