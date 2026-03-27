"use client"

import { ChevronRight, ChevronDown, Brain, Sparkles, Code2, Monitor } from "lucide-react"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Badge } from "@/components/ui/badge"
import {
  computerNodeId,
  projectNodeId,
  sessionNodeId,
  type ComputerGroup,
  type NodeId,
  type ProjectGroup,
  type SessionTreeNode,
} from "@/lib/sessions/tree"
import { safeAgent } from "@/lib/theme/tokens"

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface SessionTreeProps {
  tree: ComputerGroup[]
  expandedSet?: ReadonlySet<NodeId>
  cursorId?: string | null
  activeSessionId?: string | null
  activityMap?: Map<string, string>
  onToggle?: (nodeId: NodeId) => void
  onSelectSession?: (sessionId: string) => void
  onCursorChange?: (nodeId: string) => void
}

// ---------------------------------------------------------------------------
// Agent icon
// ---------------------------------------------------------------------------

function AgentIcon({ agent, color }: { agent: string | null | undefined; color: string }) {
  const className = "h-3.5 w-3.5 shrink-0"
  switch (agent) {
    case "gemini":
      return <Sparkles className={className} style={{ color }} />
    case "codex":
      return <Code2 className={className} style={{ color }} />
    default:
      return <Brain className={className} style={{ color }} />
  }
}

// ---------------------------------------------------------------------------
// Expand / collapse chevron
// ---------------------------------------------------------------------------

function ExpandChevron({ expanded }: { expanded: boolean }) {
  return expanded ? (
    <ChevronDown className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
  ) : (
    <ChevronRight className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
  )
}

// ---------------------------------------------------------------------------
// Session detail lines (shown when session node expanded)
// ---------------------------------------------------------------------------

function SessionDetails({ session }: { session: SessionTreeNode }) {
  const s = session.session
  return (
    <div className="ml-8 space-y-0.5 py-1 text-[10px] text-muted-foreground">
      <div>ID: {s.session_id}</div>
      <div>Status: {s.status}</div>
      {s.last_activity && (
        <div>Last activity: {new Date(s.last_activity).toLocaleString()}</div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Session row
// ---------------------------------------------------------------------------

function SessionRow({
  node,
  depth,
  expanded,
  onToggle,
  isCursor,
  isActive,
  activityType,
  onSelect,
}: {
  node: SessionTreeNode
  depth: number
  expanded: boolean
  onToggle: () => void
  isCursor: boolean
  isActive: boolean
  activityType?: string
  onSelect?: () => void
}) {
  const s = node.session
  const agent = safeAgent(s.active_agent ?? "")
  const agentColor = `var(--tc-agent-${agent}-normal)`
  const activityBg = activityType ? `var(--tc-agent-${agent}-subtle)` : undefined

  return (
    <>
      <div
        data-testid={`session-row-${s.session_id}`}
        data-node-id={sessionNodeId(s.session_id)}
        className={`flex cursor-pointer items-center gap-1.5 rounded px-2 py-1 text-xs transition-colors ${
          isCursor ? "ring-1 ring-primary" : ""
        } ${
          isActive && !activityBg ? "bg-accent/60" : ""
        }`}
        style={{
          paddingLeft: `${depth * 16 + 8}px`,
          backgroundColor: activityBg,
        }}
        onClick={() => onSelect?.()}
        onDoubleClick={onToggle}
      >
        <Badge variant="outline" className="h-4 w-4 justify-center p-0 text-[9px]">
          {node.index}
        </Badge>
        <AgentIcon agent={s.active_agent} color={agentColor} />
        {s.thinking_mode && (
          <span className="text-[10px] text-muted-foreground">{s.thinking_mode}</span>
        )}
        <span className="truncate font-medium">
          {s.title || s.session_id.slice(0, 8)}
        </span>
        {s.subdir && (
          <span className="truncate text-[10px] text-muted-foreground">{s.subdir}</span>
        )}
        {node.children.length > 0 && (
          <button onClick={(e) => { e.stopPropagation(); onToggle() }} className="ml-auto">
            <ExpandChevron expanded={expanded} />
          </button>
        )}
      </div>
      {expanded && <SessionDetails session={node} />}
    </>
  )
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export function SessionTree({
  tree,
  expandedSet,
  cursorId,
  activeSessionId,
  activityMap,
  onToggle,
  onSelectSession,
  onCursorChange,
}: SessionTreeProps) {
  const isExpanded = (id: NodeId) => expandedSet?.has(id) ?? false
  const toggle = (id: NodeId) => onToggle?.(id)

  function renderSessions(
    sessions: SessionTreeNode[],
    computer: string,
    depth: number,
  ) {
    return sessions.map((node) => {
      const nodeId = sessionNodeId(node.session.session_id)
      const expanded = isExpanded(nodeId)
      return (
        <div key={node.session.session_id}>
          <SessionRow
            node={node}
            depth={depth}
            expanded={expanded}
            onToggle={() => toggle(nodeId)}
            isCursor={cursorId === nodeId}
            isActive={activeSessionId === node.session.session_id}
            activityType={activityMap?.get(node.session.session_id)}
            onSelect={() => {
              onCursorChange?.(nodeId)
              onSelectSession?.(node.session.session_id)
            }}
          />
          {node.children.length > 0 && (
            <div>{renderSessions(node.children, computer, depth + 1)}</div>
          )}
        </div>
      )
    })
  }

  function renderProject(project: ProjectGroup, computer: string) {
    const nodeId = projectNodeId(computer, project.path)
    const expanded = isExpanded(nodeId)
    const projectName = project.name
    const truncatedPath =
      project.path.length > 30
        ? `...${project.path.slice(-27)}`
        : project.path

    return (
      <div key={project.path}>
        <div
          data-testid={`project-header-${project.path}`}
          data-node-id={nodeId}
          className={`flex items-center gap-1.5 px-4 py-1 text-xs cursor-pointer hover:bg-accent/50 ${
            cursorId === nodeId ? "ring-1 ring-primary" : ""
          }`}
          onClick={() => {
            onCursorChange?.(nodeId)
            toggle(nodeId)
          }}
        >
          <ExpandChevron expanded={expanded} />
          <span className="font-medium">{projectName}</span>
          <span className="truncate text-[10px] text-muted-foreground">
            {truncatedPath}
          </span>
          <Badge variant="secondary" className="ml-auto h-4 px-1 text-[9px]">
            {project.sessionCount}
          </Badge>
        </div>
        {expanded && renderSessions(project.sessions, computer, 2)}
      </div>
    )
  }

  function renderComputer(computer: ComputerGroup) {
    const nodeId = computerNodeId(computer.name)
    const expanded = isExpanded(nodeId)

    return (
      <div key={computer.name}>
        <div
          data-testid={`computer-header-${computer.name}`}
          data-node-id={nodeId}
          className={`flex items-center gap-1.5 px-2 py-1.5 text-xs cursor-pointer hover:bg-accent/50 ${
            cursorId === nodeId ? "ring-1 ring-primary" : ""
          }`}
          onClick={() => {
            onCursorChange?.(nodeId)
            toggle(nodeId)
          }}
        >
          <ExpandChevron expanded={expanded} />
          <Monitor className="h-3.5 w-3.5 shrink-0" />
          <span className="font-semibold">{computer.name}</span>
          <Badge
            variant={computer.status === "online" ? "default" : "secondary"}
            className="h-4 px-1 text-[9px]"
          >
            {computer.status}
          </Badge>
          <Badge variant="outline" className="ml-auto h-4 px-1 text-[9px]">
            {computer.sessionCount}
          </Badge>
        </div>
        {expanded &&
          computer.projects.map((project) =>
            renderProject(project, computer.name),
          )}
      </div>
    )
  }

  if (tree.length === 0) {
    return (
      <div className="flex items-center justify-center p-6">
        <p className="text-sm text-muted-foreground">No sessions</p>
      </div>
    )
  }

  return (
    <ScrollArea className="flex-1">
      <div className="py-1">{tree.map(renderComputer)}</div>
    </ScrollArea>
  )
}
