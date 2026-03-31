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

vi.mock("next-auth/react", () => ({
  useSession: () => ({
    data: {
      user: {
        email: "member@example.com",
        role: "admin",
      },
    },
  }),
}))

vi.mock("next/dynamic", async () => {
  const React = await import("react")

  return {
    default: (loader: () => Promise<Record<string, unknown>>) =>
      function MockDynamicComponent(props: Record<string, unknown>) {
        const [Component, setComponent] = React.useState<React.ComponentType<Record<string, unknown>> | null>(null)

        React.useEffect(() => {
          let cancelled = false

          void loader().then((mod) => {
            if (cancelled) return
            const resolved =
              (mod.default as React.ComponentType<Record<string, unknown>> | undefined) ??
              (Object.values(mod)[0] as React.ComponentType<Record<string, unknown>> | undefined) ??
              null
            setComponent(() => resolved)
          })

          return () => {
            cancelled = true
          }
        }, [loader])

        return Component ? <Component {...props} /> : null
      },
  }
})

vi.mock("@/components/assistant/Chat", () => ({
  default: ({ sessionId }: { sessionId: string }) => (
    <div data-testid="chat-panel">Chat for {sessionId}</div>
  ),
}))

vi.mock("@/components/preparation/PreparationView", () => ({
  PreparationView: () => <div>Start work</div>,
}))

vi.mock("@/components/configuration/ConfigView", () => ({
  ConfigView: () => <div>Configuration view</div>,
}))

vi.mock("@/components/jobs/JobsView", () => ({
  JobsView: () => <div>Jobs view</div>,
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

vi.mock("@/hooks/useAgentTheming", () => ({
  useAgentTheming: () => ({
    isThemed: true,
    setThemed: vi.fn(),
  }),
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

vi.mock("@/lib/hooks/useProjects", () => ({
  useProjects: () => ({
    data: [],
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
  let storage: Map<string, string>

  beforeEach(() => {
    storage = new Map<string, string>()
    Object.defineProperty(window, "localStorage", {
      configurable: true,
      value: {
        getItem: vi.fn((key: string) => storage.get(key) ?? null),
        setItem: vi.fn((key: string, value: string) => {
          storage.set(key, value)
        }),
        removeItem: vi.fn((key: string) => {
          storage.delete(key)
        }),
      },
    })
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
    expect(screen.getAllByRole("tablist")).toHaveLength(1)
    expect(screen.getAllByTestId("footer-hint").length).toBeGreaterThan(0)
    expect(screen.queryByText("Sessions tree loading...")).toBeNull()
    expect(screen.queryByText("Press ? for help")).toBeNull()
    expect(sessionToastsMock).toHaveBeenCalled()
  })

  it("restores the persisted left tab instead of rendering the old right-pane tabs", async () => {
    storage.set(
      "teleclaude.chat.layout",
      JSON.stringify({ activeTab: "preparation" }),
    )

    render(<ChatPage />)

    expect(await screen.findByText("Start work")).toBeDefined()
    expect(screen.getAllByRole("tablist")).toHaveLength(1)
    const preparationTab = screen
      .getAllByRole("tab")
      .find((tab) => tab.textContent?.includes("Preparation"))
    expect(preparationTab?.getAttribute("aria-selected")).toBe("true")
  })

  it("routes to the selected session when a tree row is clicked", async () => {
    render(<ChatPage />)

    fireEvent.click(await screen.findByTestId("session-row-sess-1"))

    expect(pushMock).toHaveBeenCalledWith("/?sessionId=sess-1")
    expect(storage.get("teleclaude.chat.layout")).toBe(
      JSON.stringify({
        activeTab: "sessions",
        lastSessionId: "sess-1",
      }),
    )
  })

  it("restores the last active session when the route opens without a session id", async () => {
    storage.set(
      "teleclaude.chat.layout",
      JSON.stringify({
        activeTab: "sessions",
        lastSessionId: "sess-2",
      }),
    )

    render(<ChatPage />)

    await waitFor(() => {
      expect(pushMock).toHaveBeenCalledWith("/?sessionId=sess-2")
    })
  })

  it("restores the persisted session-tree expansion state on the real route", async () => {
    storage.set(
      "teleclaude.chat.session-tree",
      JSON.stringify({
        expandedIds: [
          "computer:local",
          "project:local:/home/user/my-project",
          "session:sess-2",
        ],
        cursorId: "session:sess-2",
      }),
    )

    render(<ChatPage />)

    expect(await screen.findByTestId("session-detail-id-sess-2")).toBeDefined()
  })

  it("persists session row expansion changes from the real route", async () => {
    render(<ChatPage />)

    fireEvent.click(await screen.findByTestId("session-toggle-sess-2"))

    await waitFor(() => {
      expect(storage.get("teleclaude.chat.session-tree")).toContain("session:sess-2")
    })
  })

  it("uses +/- on a selected session to expand and collapse that parent project's sessions", async () => {
    render(<ChatPage />)

    fireEvent.keyDown(document, { key: "ArrowDown" })
    fireEvent.keyDown(document, { key: "ArrowDown" })
    fireEvent.keyDown(document, { key: "ArrowDown" })

    fireEvent.keyDown(document, { key: "=" })

    expect(await screen.findByTestId("session-detail-id-sess-1")).toBeDefined()
    expect(screen.getByTestId("session-detail-id-sess-2")).toBeDefined()

    fireEvent.keyDown(document, { key: "-" })

    await waitFor(() => {
      expect(screen.queryByTestId("session-detail-id-sess-1")).toBeNull()
      expect(screen.queryByTestId("session-detail-id-sess-2")).toBeNull()
    })
  })

  it("uses +/- on a selected project to expand and collapse project visibility without collapsing computers", async () => {
    render(<ChatPage />)

    fireEvent.keyDown(document, { key: "ArrowDown" })
    fireEvent.keyDown(document, { key: "ArrowDown" })

    fireEvent.keyDown(document, { key: "-" })

    await waitFor(() => {
      expect(screen.getByTestId("computer-header-local")).toBeDefined()
      expect(screen.queryByText("Session Alpha")).toBeNull()
    })

    fireEvent.keyDown(document, { key: "=" })

    expect(await screen.findByText("Session Alpha")).toBeDefined()
  })

  it("switches tabs from the keyboard and opens a prefilled new-session dialog from a project node", async () => {
    render(<ChatPage />)

    fireEvent.keyDown(document, { key: "2" })
    expect(await screen.findByText("Start work")).toBeDefined()
    expect(storage.get("teleclaude.chat.layout")).toBe(
      JSON.stringify({ activeTab: "preparation", lastSessionId: null }),
    )

    fireEvent.keyDown(document, { key: "1" })
    expect(await screen.findByTestId("computer-header-local")).toBeDefined()
    expect(storage.get("teleclaude.chat.layout")).toBe(
      JSON.stringify({ activeTab: "sessions", lastSessionId: null }),
    )

    fireEvent.keyDown(document, { key: "ArrowDown" })
    fireEvent.keyDown(document, { key: "ArrowDown" })
    fireEvent.keyDown(document, { key: "Enter" })

    const dialog = screen.getByTestId("new-session-dialog")
    expect(dialog.dataset.open).toBe("true")
    expect(dialog.dataset.prefillComputer).toBe("local")
    expect(dialog.dataset.prefillProject).toBe("/home/user/my-project")
  })

  it("keeps a single tab system after switching views", async () => {
    render(<ChatPage />)

    fireEvent.keyDown(document, { key: "4" })

    const jobsTab = await screen.findByRole("tab", { name: /Jobs/i })
    expect(jobsTab.getAttribute("aria-selected")).toBe("true")
    expect(screen.getAllByRole("tablist")).toHaveLength(1)
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
