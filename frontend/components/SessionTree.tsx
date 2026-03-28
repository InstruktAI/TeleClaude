"use client"

import type { CSSProperties } from "react"
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
  isThemed?: boolean
  currentUserEmail?: string | null
  onToggle?: (nodeId: NodeId) => void
  onSelectSession?: (sessionId: string) => void
  onCursorChange?: (nodeId: string) => void
}

interface SessionPalette {
  normal: string
  muted: string
  contrast: string
  badgeText: string
  subtleBg: string
  selectionBg: string
  previewBg: string
  connector: string
}

function agentVar(agent: string, token: "subtle" | "muted" | "normal" | "highlight") {
  return `var(--tc-agent-${agent}-${token})`
}

function getSessionPalette(
  agent: string | null,
  isThemed: boolean,
): SessionPalette {
  if (agent && isThemed) {
    return {
      normal: agentVar(agent, "normal"),
      muted: agentVar(agent, "muted"),
      contrast: "var(--tc-primary-fg)",
      badgeText: "#ffffff",
      subtleBg: agentVar(agent, "subtle"),
      selectionBg: agentVar(agent, "normal"),
      previewBg: agentVar(agent, "muted"),
      connector: "var(--tc-border-default)",
    }
  }

  return {
    normal: "var(--tc-peaceful-normal)",
    muted: "var(--tc-peaceful-muted)",
    contrast: "var(--tc-primary-fg)",
    badgeText: "var(--tc-primary-fg)",
    subtleBg: "var(--tc-selection-base)",
    selectionBg: "var(--tc-selection-surface)",
    previewBg: "var(--tc-selection-base)",
    connector: "var(--tc-border-default)",
  }
}

function sessionAgent(agent: string | null | undefined): string | null {
  return agent ? safeAgent(agent) : null
}

function detailOffset(depth: number): string {
  const offset = rowOffset(depth) + 12
  return `${offset}px`
}

function rowOffset(depth: number): number {
  return Math.max(depth - 1, 0) * 16
}

function normalizeSubdir(subdir: string): string {
  return subdir.startsWith("trees/") ? subdir.slice("trees/".length) : subdir
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

function ExpandChevron({ expanded, color }: { expanded: boolean; color?: string }) {
  return expanded ? (
    <ChevronDown className="h-3.5 w-3.5 shrink-0" style={{ color }} />
  ) : (
    <ChevronRight className="h-3.5 w-3.5 shrink-0" style={{ color }} />
  )
}

// ---------------------------------------------------------------------------
// Session detail lines (shown when session node expanded)
// ---------------------------------------------------------------------------

function SessionDetails({
  session,
  depth,
  isThemed,
}: {
  session: SessionTreeNode
  depth: number
  isThemed: boolean
}) {
  const s = session.session
  const palette = getSessionPalette(sessionAgent(s.active_agent), isThemed)
  return (
    <div
      className="space-y-0.5 py-1 pl-3 text-[10px]"
      style={{
        marginLeft: detailOffset(depth),
        borderLeft: `1px solid ${palette.connector}`,
        color: palette.muted,
      }}
    >
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
  isThemed,
  activityType,
  currentUserEmail,
  onSelect,
}: {
  node: SessionTreeNode
  depth: number
  expanded: boolean
  onToggle: () => void
  isCursor: boolean
  isActive: boolean
  isThemed: boolean
  activityType?: string
  currentUserEmail?: string | null
  onSelect?: () => void
}) {
  const s = node.session
  const agent = sessionAgent(s.active_agent)
  const palette = getSessionPalette(agent, isThemed)
  const agentColor = agent ? agentVar(agent, "normal") : palette.normal
  const subdirLabel = s.subdir ? normalizeSubdir(s.subdir) : null
  const rowStyle: CSSProperties = {
    color: palette.normal,
    paddingLeft: `${rowOffset(depth)}px`,
  }
  const isOwnedByCurrentUser = Boolean(
    s.human_email &&
      currentUserEmail &&
      s.human_email.toLowerCase() === currentUserEmail.toLowerCase(),
  )

  let secondaryLine: { label: string; value?: string | null } | null = null
  if (!isOwnedByCurrentUser) {
    if (s.human_name && s.human_role) {
      secondaryLine = {
        label: s.human_role,
        value: s.human_name,
      }
    } else if (s.human_role !== "customer" && s.system_role) {
      secondaryLine = {
        label: s.system_role,
        value: s.job,
      }
    }
  }

  if (activityType) {
    rowStyle.backgroundColor = palette.subtleBg
  }
  if (isActive) {
    rowStyle.backgroundColor = palette.previewBg
    rowStyle.color = palette.contrast
    rowStyle.fontWeight = 600
  }
  if (isCursor) {
    rowStyle.backgroundColor = palette.selectionBg
    rowStyle.color = palette.contrast
    rowStyle.fontWeight = 700
  }

  return (
    <>
      <div
        data-testid={`session-row-${s.session_id}`}
        data-node-id={sessionNodeId(s.session_id)}
        className="flex cursor-pointer items-center gap-1.5 rounded py-1 pr-2 text-xs transition-colors"
        style={rowStyle}
        onClick={() => onSelect?.()}
        onDoubleClick={onToggle}
      >
        <Badge
          data-testid={`session-index-${s.session_id}`}
          variant="outline"
          className="h-4 min-w-[1.25rem] justify-center px-1.5 text-[9px] tabular-nums"
          style={{
            backgroundColor: isCursor || isActive ? palette.contrast : palette.normal,
            borderColor: isCursor || isActive ? palette.contrast : palette.normal,
            color: isCursor || isActive ? palette.selectionBg : palette.badgeText,
          }}
        >
          {node.displayIndex}
        </Badge>
        <AgentIcon agent={s.active_agent} color={agentColor} />
        {s.thinking_mode && (
          <span className="text-[10px]" style={{ color: rowStyle.color ?? palette.muted }}>
            {s.thinking_mode}
          </span>
        )}
        <span className="truncate font-medium">
          {s.title || s.session_id.slice(0, 8)}
        </span>
        {subdirLabel && (
          <Badge
            data-testid={`session-subdir-${s.session_id}`}
            variant="outline"
            className="max-w-[14rem] truncate px-2 py-0 text-[9px] font-semibold"
            style={{
              backgroundColor: isCursor || isActive ? palette.contrast : palette.normal,
              borderColor: isCursor || isActive ? palette.contrast : palette.normal,
              color: isCursor || isActive ? palette.selectionBg : palette.badgeText,
            }}
          >
            {subdirLabel}
          </Badge>
        )}
        {node.children.length > 0 && (
          <button onClick={(e) => { e.stopPropagation(); onToggle() }} className="ml-auto">
            <ExpandChevron
              expanded={expanded}
              color={isCursor || isActive ? rowStyle.color ?? palette.contrast : palette.normal}
            />
          </button>
        )}
      </div>
      {secondaryLine ? (
        <div
          data-testid={`session-identity-${s.session_id}`}
          className="truncate text-[10px]"
          style={{ paddingLeft: `${rowOffset(depth)}px`, color: palette.muted }}
        >
          {secondaryLine.label}
          {secondaryLine.value && <>: <span style={{ color: palette.normal }}>{secondaryLine.value}</span></>}
        </div>
      ) : null}
      {expanded && (
        <SessionDetails session={node} depth={depth} isThemed={isThemed} />
      )}
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
  isThemed = true,
  currentUserEmail,
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
            isThemed={isThemed}
            activityType={activityMap?.get(node.session.session_id)}
            currentUserEmail={currentUserEmail}
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
