// @vitest-environment happy-dom
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest"
import { render, screen, fireEvent, cleanup, waitFor } from "@testing-library/react"
import ChatPage from "@/app/(chat)/page"

const {
  computersData,
  sessionsData,
  pushMock,
  searchParamsMock,
  sessionToastsMock,
  endSessionMutateAsyncMock,
  restartMutateAsyncMock,
  refreshMock,
  toastSuccessMock,
  toastInfoMock,
  toastErrorMock,
} = vi.hoisted(() => ({
  computersData: [
    {
      name: "local",
      status: "online",
      is_local: true,
    },
  ],
  sessionsData: [
    {
      session_id: "sess-1",
      title: "Session Alpha",
      status: "running",
      active_agent: "claude",
      project_path: "/home/user/my-project",
      computer: "local",
    },
    {
      session_id: "sess-2",
      title: "Session Beta",
      status: "idle",
      active_agent: "codex",
      project_path: "/home/user/my-project",
      computer: "local",
    },
  ],
  pushMock: vi.fn(),
  searchParamsMock: vi.fn(),
  sessionToastsMock: vi.fn(),
  endSessionMutateAsyncMock: vi.fn(),
  restartMutateAsyncMock: vi.fn(),
  refreshMock: vi.fn(),
  toastSuccessMock: vi.fn(),
  toastInfoMock: vi.fn(),
  toastErrorMock: vi.fn(),
}))

vi.mock("next/dynamic", () => ({
  default: () =>
    function MockChat({ sessionId }: { sessionId: string }) {
      return <div data-testid="chat-panel">Chat for {sessionId}</div>
    },
}))

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: pushMock }),
  useSearchParams: () => searchParamsMock(),
}))

vi.mock("@/components/sidebar/SessionHeader", () => ({
  SessionHeader: ({ sessionId }: { sessionId: string }) => (
    <div data-testid="session-header">{sessionId}</div>
  ),
}))

vi.mock("@/components/parts/DarkModeToggle", () => ({
  DarkModeToggle: () => <div data-testid="dark-mode-toggle" />,
}))

vi.mock("@/components/parts/ThemingToggle", () => ({
  ThemingToggle: () => <div data-testid="theming-toggle" />,
}))

vi.mock("@/components/sidebar/NewSessionDialog", () => ({
  NewSessionDialog: ({
    open,
    prefill,
  }: {
    open: boolean
    prefill?: { computer?: string; project?: string }
  }) => (
    <div
      data-testid="new-session-dialog"
      data-open={String(open)}
      data-prefill-computer={prefill?.computer ?? ""}
      data-prefill-project={prefill?.project ?? ""}
    />
  ),
}))

vi.mock("@/lib/hooks/useSessions", () => ({
  useSessions: () => ({
    data: sessionsData,
    isLoading: false,
    error: null,
  }),
}))

vi.mock("@/lib/hooks/useComputers", () => ({
  useComputers: () => ({
    data: computersData,
    isLoading: false,
    error: null,
  }),
}))

vi.mock("@/hooks/useSessionToasts", () => ({
  useSessionToasts: sessionToastsMock,
}))

vi.mock("@/lib/hooks/useSessionActions", () => ({
  useEndSession: () => ({
    mutateAsync: endSessionMutateAsyncMock,
  }),
  useAgentRestart: () => ({
    mutateAsync: restartMutateAsyncMock,
  }),
}))

vi.mock("@/lib/ws/WebSocketProvider", () => ({
  useWS: () => ({
    onEvent: () => () => undefined,
    refresh: refreshMock,
  }),
}))

vi.mock("sonner", () => ({
  toast: {
    success: toastSuccessMock,
    info: toastInfoMock,
    error: toastErrorMock,
  },
}))

describe("ChatPage", () => {
  beforeEach(() => {
    searchParamsMock.mockReturnValue({
      get: (key: string) => (key === "sessionId" ? null : null),
    })
    endSessionMutateAsyncMock.mockResolvedValue({})
    restartMutateAsyncMock.mockResolvedValue({})
  })

  afterEach(() => {
    cleanup()
    vi.clearAllMocks()
  })

  it("renders the real session tree and footer instead of placeholder shell text", async () => {
    render(<ChatPage />)

    expect(await screen.findByTestId("computer-header-local")).toBeDefined()
    expect(screen.getByText("Session Alpha")).toBeDefined()
    expect(screen.getAllByTestId("footer-hint").length).toBeGreaterThan(0)
    expect(screen.queryByText("Sessions tree loading...")).toBeNull()
    expect(screen.queryByText("Press ? for help")).toBeNull()
    expect(sessionToastsMock).toHaveBeenCalledTimes(1)
  })

  it("routes to the selected session when a tree row is clicked", async () => {
    render(<ChatPage />)

    fireEvent.click(await screen.findByTestId("session-row-sess-1"))

    expect(pushMock).toHaveBeenCalledWith("/?sessionId=sess-1")
  })

  it("switches tabs from the keyboard and opens a prefilled new-session dialog from a project node", async () => {
    render(<ChatPage />)

    fireEvent.keyDown(document, { key: "2" })
    expect(await screen.findByText("Not yet implemented")).toBeDefined()

    fireEvent.keyDown(document, { key: "1" })
    expect(await screen.findByTestId("computer-header-local")).toBeDefined()

    fireEvent.keyDown(document, { key: "ArrowDown" })
    fireEvent.keyDown(document, { key: "ArrowDown" })
    fireEvent.keyDown(document, { key: "Enter" })

    const dialog = screen.getByTestId("new-session-dialog")
    expect(dialog.dataset.open).toBe("true")
    expect(dialog.dataset.prefillComputer).toBe("local")
    expect(dialog.dataset.prefillProject).toBe("/home/user/my-project")
  })

  it("opens the confirm modal for the selected session and restarts the session from the keyboard", async () => {
    render(<ChatPage />)

    fireEvent.keyDown(document, { key: "ArrowDown" })
    fireEvent.keyDown(document, { key: "ArrowDown" })
    fireEvent.keyDown(document, { key: "ArrowDown" })
    fireEvent.keyDown(document, { key: "k" })

    expect(await screen.findByText("End session?")).toBeDefined()

    fireEvent.keyDown(document, { key: "R", shiftKey: true })
    expect(restartMutateAsyncMock).toHaveBeenCalledWith("sess-1")
    await waitFor(() => {
      expect(toastSuccessMock).toHaveBeenCalledWith("Session restarted")
    })
  })
})
