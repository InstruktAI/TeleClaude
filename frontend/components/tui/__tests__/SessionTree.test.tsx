// @vitest-environment happy-dom
import { useState } from "react"
import { describe, it, expect, vi, afterEach } from "vitest"
import { render, screen, fireEvent, cleanup } from "@testing-library/react"
import { SessionTree } from "../SessionTree"
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
                subdir: 'packages/core',
                project_path: '/home/user/my-project',
                computer: 'local',
              },
              index: 1,
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

  it("renders subdir slug on session row", () => {
    render(
      <SessionTree
        tree={makeTree()}
        expandedSet={makeExpandedSet(makeTree())}
        onToggle={vi.fn()}
      />,
    )
    expect(screen.getByText("packages/core")).toBeDefined()
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
    const activityMap = new Map([["sess-1", "tool_use"]])
    render(
      <SessionTree
        tree={makeTree()}
        activityMap={activityMap}
        expandedSet={makeExpandedSet(makeTree())}
        onToggle={vi.fn()}
      />,
    )
    const row = screen.getByTestId("session-row-sess-1")
    expect(row.style.backgroundColor).toContain("var(--tc-agent-")
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
})
