// @vitest-environment happy-dom
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest"
import { render, screen, fireEvent, cleanup, waitFor } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"

function renderChatPage() {
  const testQueryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={testQueryClient}>
      <ChatPage />
    </QueryClientProvider>
  )
}

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
  subscribeMock,
  unsubscribeMock,
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
  subscribeMock: vi.fn(),
  unsubscribeMock: vi.fn(),
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
            let resolved: React.ComponentType<Record<string, unknown>> | null = null
            const isFunction = typeof mod === ("function" as string)
            const isObject = typeof mod === ("object" as string)
            if (isFunction) {
              resolved = mod as unknown as React.ComponentType<Record<string, unknown>>
            } else if (mod && isObject) {
              resolved =
                (mod.default as React.ComponentType<Record<string, unknown>> | undefined) ??
                (Object.values(mod)[0] as React.ComponentType<Record<string, unknown>> | undefined) ??
                null
            }
            setComponent(() => resolved)
          })

          return () => {
            cancelled = true
          }
        }, [])

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
  PreparationView: () => <div data-testid="preparation-view" />,
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

vi.mock("@/components/ConfirmModal", () => ({
  ConfirmModal: ({ open }: { open: boolean }) => open ? <div data-testid="confirm-modal" /> : null,
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
    subscribe: subscribeMock,
    unsubscribe: unsubscribeMock,
  }),
}))

vi.mock("sonner", () => ({
  toast: {
    success: toastSuccessMock,
    info: toastInfoMock,
    error: toastErrorMock,
  },
}))

const EXPECTED_TRUE = "true"
const EXPECTED_LOCAL = "local"
const EXPECTED_PROJECT = "/home/user/my-project"
const SESS_2_KEY = "session:sess-2"

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
      get: () => null,
    })
    endSessionMutateAsyncMock.mockResolvedValue({})
    restartMutateAsyncMock.mockResolvedValue({})
  })

  afterEach(() => {
    cleanup()
    vi.clearAllMocks()
  })

  it("subscribes the chat page to live session events for each computer", async () => {
    renderChatPage()

    await screen.findByTestId("computer-header-local")

    expect(subscribeMock).toHaveBeenCalledWith("local", ["sessions"])
  })

  it("renders the real session tree and footer instead of placeholder shell text", async () => {
    renderChatPage()

    expect(await screen.findByTestId("computer-header-local")).toBeDefined()
    expect(screen.getByTestId("session-row-sess-1")).toBeDefined()
    expect(screen.getAllByRole("tablist")).toHaveLength(1)
    expect(screen.getAllByTestId("footer-hint").length).toBeGreaterThan(0)
            expect(sessionToastsMock).toHaveBeenCalled()
  })

  it("restores the persisted left tab instead of rendering the old right-pane tabs", async () => {
    storage.set(
      "teleclaude.chat.layout",
      JSON.stringify({ activeTab: "preparation" }),
    )

    renderChatPage()

    expect(await screen.findByTestId("preparation-view")).toBeDefined()
    expect(screen.getAllByRole("tablist")).toHaveLength(1)
    const preparationTab = screen.getAllByRole("tab")[1]
    expect(preparationTab?.getAttribute("aria-selected")).toBe(EXPECTED_TRUE)
  })

  it("routes to the selected session when a tree row is clicked", async () => {
    renderChatPage()

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

    renderChatPage()

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

    renderChatPage()

    expect(await screen.findByTestId("session-detail-id-sess-2")).toBeDefined()
  })

  it("persists session row expansion changes from the real route", async () => {
    renderChatPage()

    fireEvent.click(await screen.findByTestId("session-toggle-sess-2"))

    await waitFor(() => {
      expect(storage.get("teleclaude.chat.session-tree")?.includes(SESS_2_KEY)).toBe(true)
    })
  })

  it("uses +/- on a selected session to expand and collapse that parent project's sessions", async () => {
    renderChatPage()

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
    renderChatPage()

    fireEvent.keyDown(document, { key: "ArrowDown" })
    fireEvent.keyDown(document, { key: "ArrowDown" })

    fireEvent.keyDown(document, { key: "-" })

    await waitFor(() => {
      expect(screen.getByTestId("computer-header-local")).toBeDefined()
      expect(screen.queryByTestId("session-row-sess-1")).toBeNull()
    })

    fireEvent.keyDown(document, { key: "=" })

    expect(await screen.findByTestId("session-row-sess-1")).toBeDefined()
  })

  it("switches tabs from the keyboard and opens a prefilled new-session dialog from a project node", async () => {
    renderChatPage()

    fireEvent.keyDown(document, { key: "2" })
    expect(await screen.findByTestId("preparation-view")).toBeDefined()
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
    expect(dialog.dataset.open).toBe(EXPECTED_TRUE)
    expect(dialog.dataset.prefillComputer).toBe(EXPECTED_LOCAL)
    expect(dialog.dataset.prefillProject).toBe(EXPECTED_PROJECT)
  })

  it("keeps a single tab system after switching views", async () => {
    renderChatPage()

    fireEvent.keyDown(document, { key: "4" })

    const jobsTab = screen.getAllByRole("tab")[3]
    expect(jobsTab.getAttribute("aria-selected")).toBe(EXPECTED_TRUE)
    expect(screen.getAllByRole("tablist")).toHaveLength(1)
  })

  it("opens the confirm modal for the selected session and restarts the session from the keyboard", async () => {
    renderChatPage()

    fireEvent.keyDown(document, { key: "ArrowDown" })
    fireEvent.keyDown(document, { key: "ArrowDown" })
    fireEvent.keyDown(document, { key: "ArrowDown" })
    fireEvent.keyDown(document, { key: "k" })

    expect(await screen.findByTestId("confirm-modal")).toBeDefined()

    fireEvent.keyDown(document, { key: "R", shiftKey: true })
    expect(restartMutateAsyncMock).toHaveBeenCalledWith("sess-1")
    await waitFor(() => {
      expect(toastSuccessMock).toHaveBeenCalled()
      expect(toastSuccessMock.mock.calls[0][0]).toBeTruthy()
    })
  })
})
