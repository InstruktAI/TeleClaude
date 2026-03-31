// @vitest-environment happy-dom
import { useState } from "react"
import { describe, it, expect, vi, afterEach } from "vitest"
import { render, screen, fireEvent, cleanup } from "@testing-library/react"
import { SessionTree } from "../SessionTree"
import type { SessionHighlightViewState } from "@/hooks/useSessionHighlights"
import {
  computerNodeId,
  projectNodeId,
  type ComputerGroup,
  type NodeId,
} from "@/lib/sessions/tree"

function makeTree(): ComputerGroup[] {
  return [
    {
      type: 'computer',
      name: 'local',
      status: 'online',
      isLocal: true,
      sessionCount: 3,
      projects: [
        {
          type: 'project',
          name: 'my-project',
          path: '/home/user/my-project',
          sessionCount: 2,
          sessions: [
            {
              type: 'session',
              session: {
                session_id: 'sess-1',
                title: 'Session Alpha',
                status: 'running',
                active_agent: 'claude',
                thinking_mode: 'med',
                subdir: 'trees/web-tui-panels',
                last_input: 'Run the planner',
                project_path: '/home/user/my-project',
                computer: 'local',
              },
              index: 1,
              displayIndex: "1",
              children: [
                {
                  type: 'session',
                  session: {
                    session_id: 'sess-child',
                    title: 'Child Session',
                    status: 'running',
                    active_agent: 'gemini',
                    thinking_mode: 'fast',
                    project_path: '/home/user/my-project',
                    computer: 'local',
                    initiator_session_id: 'sess-1',
                  },
                  index: 1,
                  displayIndex: "1.1",
                  children: [],
                },
              ],
            },
            {
              type: 'session',
              session: {
                session_id: 'sess-2',
                title: 'Session Beta',
                status: 'idle',
                active_agent: 'codex',
                project_path: '/home/user/my-project',
                computer: 'local',
              },
              index: 2,
              displayIndex: "2",
              children: [],
            },
          ],
        },
        {
          type: 'project',
          name: '\u2014',
          path: '__orphan__',
          sessionCount: 1,
          sessions: [
            {
              type: 'session',
              session: {
                session_id: 'sess-orphan',
                title: 'Orphan Session',
                status: 'running',
                project_path: null,
                computer: 'local',
              },
              index: 1,
              displayIndex: "1",
              children: [],
            },
          ],
        },
      ],
    },
  ]
}

function makeExpandedSet(tree: ComputerGroup[]): Set<NodeId> {
  const expanded = new Set<NodeId>()
  for (const computer of tree) {
    expanded.add(computerNodeId(computer.name))
    for (const project of computer.projects) {
      expanded.add(projectNodeId(computer.name, project.path))
    }
  }
  return expanded
}

function renderWithControlledExpansion(
  tree: ComputerGroup[] = makeTree(),
  props: Partial<React.ComponentProps<typeof SessionTree>> = {},
) {
  function Wrapper() {
    const [expandedSet, setExpandedSet] = useState(makeExpandedSet(tree))
    return (
      <SessionTree
        tree={tree}
        expandedSet={expandedSet}
        onToggle={(nodeId) => {
          setExpandedSet((prev) => {
            const next = new Set(prev)
            if (next.has(nodeId)) next.delete(nodeId)
            else next.add(nodeId)
            return next
          })
        }}
        {...props}
      />
    )
  }

  return render(<Wrapper />)
}

describe("SessionTree", () => {
  afterEach(() => cleanup())

  it("renders computer header with name and status badge", () => {
    render(
      <SessionTree
        tree={makeTree()}
        expandedSet={makeExpandedSet(makeTree())}
        onToggle={vi.fn()}
      />,
    )
    expect(screen.getByTestId("computer-header-local")).toBeDefined()
  })

  it("renders project header with session count", () => {
    render(
      <SessionTree
        tree={makeTree()}
        expandedSet={makeExpandedSet(makeTree())}
        onToggle={vi.fn()}
      />,
    )
    const projectHeader = screen.getByTestId("project-header-/home/user/my-project")
    expect(projectHeader).toBeDefined()
    expect(projectHeader.textContent).toContain("my-project")
    expect(projectHeader.textContent).toContain("/home/user/my-project")
  })

  it("renders session rows with titles", () => {
    render(
      <SessionTree
        tree={makeTree()}
        expandedSet={makeExpandedSet(makeTree())}
        onToggle={vi.fn()}
      />,
    )
    expect(screen.getByTestId("session-row-sess-1")).toBeDefined()
    expect(screen.getByText("Session Alpha")).toBeDefined()
    expect(screen.getByText("Session Beta")).toBeDefined()
  })

  it("renders orphan project node", () => {
    render(
      <SessionTree
        tree={makeTree()}
        expandedSet={makeExpandedSet(makeTree())}
        onToggle={vi.fn()}
      />,
    )
    expect(screen.getByTestId("project-header-__orphan__")).toBeDefined()
  })

  it("renders child sessions nested under parent", () => {
    render(
      <SessionTree
        tree={makeTree()}
        expandedSet={makeExpandedSet(makeTree())}
        onToggle={vi.fn()}
      />,
    )
    expect(screen.getByText("Child Session")).toBeDefined()
  })

  it("renders dotted display indices for child sessions", () => {
    render(
      <SessionTree
        tree={makeTree()}
        expandedSet={makeExpandedSet(makeTree())}
        onToggle={vi.fn()}
      />,
    )

    expect(screen.getByText("1.1")).toBeDefined()
  })

  it("renders subdir slug on session row", () => {
    render(
      <SessionTree
        tree={makeTree()}
        expandedSet={makeExpandedSet(makeTree())}
        onToggle={vi.fn()}
      />,
    )
    expect(screen.getByText("web-tui-panels")).toBeDefined()
    expect(screen.queryByText("trees/web-tui-panels")).toBeNull()
  })

  it("renders thinking mode on session row", () => {
    render(
      <SessionTree
        tree={makeTree()}
        expandedSet={makeExpandedSet(makeTree())}
        onToggle={vi.fn()}
      />,
    )
    expect(screen.getByText("med")).toBeDefined()
  })

  it("toggles computer expand/collapse on click", () => {
    renderWithControlledExpansion()
    const header = screen.getByTestId("computer-header-local")
    expect(screen.getByText("Session Alpha")).toBeDefined()
    fireEvent.click(header)
    expect(screen.queryByText("Session Alpha")).toBeNull()
    fireEvent.click(header)
    expect(screen.getByText("Session Alpha")).toBeDefined()
  })

  it("uses agent color CSS variable, not hardcoded hex", () => {
    const { container } = render(
      <SessionTree
        tree={makeTree()}
        expandedSet={makeExpandedSet(makeTree())}
        onToggle={vi.fn()}
      />,
    )
    const svgs = container.querySelectorAll("svg")
    const agentSvgs = Array.from(svgs).filter(
      (svg) => svg.style.color && svg.style.color.includes("var(--tc-agent-"),
    )
    expect(agentSvgs.length).toBeGreaterThan(0)
  })

  it("applies activity highlight background when session is active", () => {
    const sessionStateMap = new Map<string, SessionHighlightViewState>([
      ["sess-1", { activityEvent: "tool_use", activityText: "bash: telec todo work" }],
    ])
    render(
      <SessionTree
        tree={makeTree()}
        sessionStateMap={sessionStateMap}
        expandedSet={makeExpandedSet(makeTree())}
        onToggle={vi.fn()}
      />,
    )
    const row = screen.getByTestId("session-row-sess-1")
    expect(row.style.backgroundColor).toContain("var(--tc-agent-")
  })

  it("renders persisted output summaries in the collapsed session summary", () => {
    const sessionStateMap = new Map<string, SessionHighlightViewState>([
      ["sess-2", { lastOutputSummary: "Build complete", highlightType: "output" }],
    ])

    render(
      <SessionTree
        tree={makeTree()}
        sessionStateMap={sessionStateMap}
        expandedSet={makeExpandedSet(makeTree())}
        onToggle={vi.fn()}
      />,
    )

    expect(screen.getByTestId("session-summary-output-sess-2").textContent).toContain("out: Build complete")
  })

  it("renders input and output activity in the collapsed session summary", () => {
    const sessionStateMap = new Map<string, SessionHighlightViewState>([
      ["sess-1", { highlightType: "input", activityEvent: "user_prompt_submit" }],
    ])

    render(
      <SessionTree
        tree={makeTree()}
        sessionStateMap={sessionStateMap}
        expandedSet={makeExpandedSet(makeTree())}
        onToggle={vi.fn()}
      />,
    )

    expect(screen.getByTestId("session-summary-input-sess-1").textContent).toContain("in: Run the planner")
    expect(screen.getByTestId("session-summary-output-sess-1").textContent).toContain("out: ...")
  })

  it("keeps technical session ids in the expanded detail block only", () => {
    render(
      <SessionTree
        tree={makeTree()}
        expandedSet={makeExpandedSet(makeTree())}
        onToggle={vi.fn()}
      />,
    )

    expect(screen.queryByTestId("session-detail-id-sess-2")).toBeNull()
  })

  it("expands a leaf session row through its toggle button", () => {
    renderWithControlledExpansion()

    expect(screen.queryByTestId("session-detail-id-sess-2")).toBeNull()
    fireEvent.click(screen.getByTestId("session-toggle-sess-2"))
    expect(screen.getByTestId("session-detail-id-sess-2").textContent).toContain("sess-2")
  })

  it("shows created time in the expanded technical id row", () => {
    const tree = makeTree()
    tree[0].projects[0].sessions[0].session.created_at = "2026-03-31T12:00:00Z"
    const createdTime = new Date("2026-03-31T12:00:00Z").toLocaleTimeString([], {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    })

    renderWithControlledExpansion(tree)
    fireEvent.click(screen.getByTestId("session-toggle-sess-1"))

    expect(screen.getByTestId("session-detail-id-sess-1").textContent).toContain(createdTime)
  })

  it("renders the expanded technical id row before summary lines", () => {
    renderWithControlledExpansion()
    fireEvent.click(screen.getByTestId("session-toggle-sess-1"))

    const detail = screen.getByTestId("session-detail-id-sess-1")
    const input = screen.getByTestId("session-summary-input-sess-1")

    expect(
      Boolean(detail.compareDocumentPosition(input) & Node.DOCUMENT_POSITION_FOLLOWING),
    ).toBe(true)
  })

  it("applies agent-specific cursor highlight colors when themed", () => {
    render(
      <SessionTree
        tree={makeTree()}
        cursorId="session:sess-1"
        expandedSet={makeExpandedSet(makeTree())}
        onToggle={vi.fn()}
      />,
    )

    const row = screen.getByTestId("session-row-sess-1")
    expect(row.style.backgroundColor).toContain("var(--tc-agent-claude-normal)")
    expect(row.style.color).toContain("var(--tc-primary-fg)")
    const subdirBadge = screen.getByTestId("session-subdir-sess-1")
    expect(subdirBadge.style.backgroundColor).toContain("var(--tc-primary-fg)")
    expect(subdirBadge.style.color).toContain("var(--tc-agent-claude-normal)")
  })

  it("renders the session badge column aligned under the project chevron", () => {
    render(
      <SessionTree
        tree={makeTree()}
        expandedSet={makeExpandedSet(makeTree())}
        onToggle={vi.fn()}
      />,
    )

    const row = screen.getByTestId("session-row-sess-1")
    expect(row.style.paddingLeft).toBe("16px")
  })

  it("calls onSelectSession when session row clicked", () => {
    const onSelect = vi.fn()
    render(
      <SessionTree
        tree={makeTree()}
        onSelectSession={onSelect}
        expandedSet={makeExpandedSet(makeTree())}
        onToggle={vi.fn()}
      />,
    )
    fireEvent.click(screen.getByTestId("session-row-sess-2"))
    expect(onSelect).toHaveBeenCalledWith("sess-2")
  })

  it("calls onCursorChange with the clicked node id", () => {
    const onCursorChange = vi.fn()
    render(
      <SessionTree
        tree={makeTree()}
        onCursorChange={onCursorChange}
        expandedSet={makeExpandedSet(makeTree())}
        onToggle={vi.fn()}
      />,
    )

    fireEvent.click(screen.getByTestId("session-row-sess-2"))

    expect(onCursorChange).toHaveBeenCalledWith("session:sess-2")
  })

  it("delegates expansion state to the caller via expandedSet and onToggle", () => {
    const onToggle = vi.fn()
    const tree = makeTree()
    const expandedSet = new Set<NodeId>([computerNodeId("local")])

    render(
      <SessionTree tree={tree} expandedSet={expandedSet} onToggle={onToggle} />,
    )

    expect(screen.queryByText("Session Alpha")).toBeNull()
    fireEvent.click(screen.getByTestId("project-header-/home/user/my-project"))
    expect(onToggle).toHaveBeenCalledWith("project:local:/home/user/my-project")
    expect(screen.queryByText("Session Alpha")).toBeNull()
  })

  it("shows empty state when tree is empty", () => {
    render(<SessionTree tree={[]} expandedSet={new Set()} onToggle={vi.fn()} />)
    expect(screen.getByText("No sessions")).toBeDefined()
  })

  it("renders the human identity line from role and name only", () => {
    const tree = makeTree()
    tree[0].projects[0].sessions[0].session.human_name = "Maurice Faber"
    tree[0].projects[0].sessions[0].session.human_role = "admin"

    render(
      <SessionTree
        tree={tree}
        expandedSet={makeExpandedSet(tree)}
        onToggle={vi.fn()}
      />,
    )
    expect(screen.getByText("Maurice Faber")).toBeDefined()
    expect(screen.getByText(/^admin:/)).toBeDefined()
  })

  it("hides the identity line for the logged-in user's own session", () => {
    const tree = makeTree()
    tree[0].projects[0].sessions[0].session.human_name = "Maurice Faber"
    tree[0].projects[0].sessions[0].session.human_role = "admin"
    tree[0].projects[0].sessions[0].session.human_email = "maurice@instrukt.ai"

    render(
      <SessionTree
        tree={tree}
        currentUserEmail="maurice@instrukt.ai"
        expandedSet={makeExpandedSet(tree)}
        onToggle={vi.fn()}
      />,
    )
    expect(screen.queryByTestId("session-identity-sess-1")).toBeNull()
  })

  it("hides unresolved customer sessions", () => {
    const tree = makeTree()
    tree[0].projects[0].sessions[0].session.human_role = "customer"
    tree[0].projects[0].sessions[0].session.system_role = "worker"
    tree[0].projects[0].sessions[0].session.job = "next-build"

    render(
      <SessionTree
        tree={tree}
        expandedSet={makeExpandedSet(tree)}
        onToggle={vi.fn()}
      />,
    )
    expect(screen.queryByTestId("session-identity-sess-1")).toBeNull()
  })

  it("does not render the system fallback for unresolved non-customer sessions", () => {
    const tree = makeTree()
    tree[0].projects[0].sessions[0].session.human_role = "member"
    tree[0].projects[0].sessions[0].session.system_role = "worker"
    tree[0].projects[0].sessions[0].session.job = "next-build"

    render(
      <SessionTree
        tree={tree}
        expandedSet={makeExpandedSet(tree)}
        onToggle={vi.fn()}
      />,
    )
    expect(screen.queryByTestId("session-identity-sess-1")).toBeNull()
  })
})
