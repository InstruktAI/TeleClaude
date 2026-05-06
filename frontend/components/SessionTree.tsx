"use client"

import { memo, type CSSProperties } from "react"
import { ChevronRight, ChevronDown, Brain, Sparkles, Code2, Monitor } from "lucide-react"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Badge } from "@/components/ui/badge"
import type { SessionHighlightViewState } from "@/hooks/useSessionHighlights"
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
import { replaceHomeWithTilde } from "@/lib/utils/path"

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface SessionTreeProps {
  tree: ComputerGroup[]
  expandedSet?: ReadonlySet<NodeId>
  cursorId?: string | null
  activeSessionId?: string | null
  sessionStateMap?: Map<string, SessionHighlightViewState>
  isThemed?: boolean
  currentUserEmail?: string | null
  onToggle?: (nodeId: NodeId) => void
  onSelectSession?: (sessionId: string) => void
  onCursorChange?: (nodeId: string) => void
}

interface SessionPalette {
  normal: string
  muted: string
  highlight: string
  contrast: string
  badgeText: string
  badgeBg: string
  badgeBgFocused: string
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
      highlight: agentVar(agent, "highlight"),
      contrast: "var(--tc-primary-fg)",
      badgeText: "var(--tc-agent-badge-fg)",
      badgeBg: agentVar(agent, "muted"),
      badgeBgFocused: agentVar(agent, "normal"),
      subtleBg: agentVar(agent, "subtle"),
      selectionBg: agentVar(agent, "normal"),
      previewBg: agentVar(agent, "muted"),
      connector: "var(--tc-border-default)",
    }
  }

  return {
    normal: "var(--tc-peaceful-normal)",
    muted: "var(--tc-peaceful-muted)",
    highlight: "var(--tc-primary)",
    contrast: "var(--tc-primary-fg)",
    badgeText: "var(--tc-primary-fg)",
    badgeBg: "var(--tc-peaceful-muted)",
    badgeBgFocused: "var(--tc-peaceful-normal)",
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

function formatSessionTime(timestamp?: string | null): string {
  if (!timestamp) return "--:--:--"
  const date = new Date(timestamp)
  if (Number.isNaN(date.getTime())) return "--:--:--"
  return date.toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  })
}

function inputDetailLine(
  session: SessionTreeNode["session"],
): { timestamp: string; text: string } | null {
  const lastInput = session.last_input?.replace(/\n/g, " ").trim()
  if (!lastInput) return null

  return {
    timestamp: formatSessionTime(session.last_input_at ?? session.last_activity),
    text: `in: ${lastInput}`,
  }
}

function ownerSummaryLine(
  session: SessionTreeNode["session"],
  currentUserEmail?: string | null,
): { label: string; value?: string | null } | null {
  const isOwnedByCurrentUser = Boolean(
    session.human_email &&
      currentUserEmail &&
      session.human_email.toLowerCase() === currentUserEmail.toLowerCase(),
  )

  if (isOwnedByCurrentUser) return null

  if (session.human_name && session.human_role) {
    return {
      label: session.human_role,
      value: session.human_name,
    }
  }

  return null
}

function outputDetailLine(
  session: SessionTreeNode["session"],
  state?: SessionHighlightViewState,
): { timestamp: string; text: string; emphasized: boolean } | null {
  if (state?.activityEvent === "tool_use" && state.activityText) {
    return {
      timestamp: formatSessionTime(session.last_activity),
      text: `out: ${state.activityText}`,
      emphasized: true,
    }
  }

  if (state?.activityEvent === "user_prompt_submit") {
    return {
      timestamp: formatSessionTime(session.last_activity),
      text: "out: ...",
      emphasized: true,
    }
  }

  if (state?.activityEvent === "agent_stop" && state.activityText) {
    return {
      timestamp: formatSessionTime(
        state?.lastOutputSummaryAt ?? session.last_output_summary_at ?? session.last_activity,
      ),
      text: `out: ${state.activityText}`,
      emphasized: true,
    }
  }

  const summary = state?.lastOutputSummary?.replace(/\n/g, " ").trim()
  if (summary) {
    return {
      timestamp: formatSessionTime(
        state?.lastOutputSummaryAt ?? session.last_output_summary_at ?? session.last_activity,
      ),
      text: `out: ${summary}`,
      emphasized: state?.highlightType === "output",
    }
  }

  return null
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
// Session summary lines (always visible beneath the session header)
// ---------------------------------------------------------------------------

function SessionSummary({
  session,
  depth,
  isThemed,
  sessionState,
  currentUserEmail,
}: {
  session: SessionTreeNode
  depth: number
  isThemed: boolean
  sessionState?: SessionHighlightViewState
  currentUserEmail?: string | null
}) {
  const s = session.session
  const palette = getSessionPalette(sessionAgent(s.active_agent), isThemed)
  const ownerLine = ownerSummaryLine(s, currentUserEmail)
  const inputLine = inputDetailLine(s)
  const outputLine = outputDetailLine(s, sessionState)
  if (!ownerLine && !inputLine && !outputLine) {
    return null
  }
  return (
    <div
      className="space-y-0.5 py-1 pl-3 text-[11px] leading-4"
      style={{
        marginLeft: detailOffset(depth),
        borderLeft: `1px solid ${palette.connector}`,
        color: palette.normal,
      }}
    >
      {ownerLine ? (
        <div
          data-testid={`session-identity-${s.session_id}`}
          className="truncate"
          style={{ color: palette.muted }}
        >
          {ownerLine.label}
          {ownerLine.value ? (
            <>
              : <span style={{ color: palette.normal }}>{ownerLine.value}</span>
            </>
          ) : null}
        </div>
      ) : null}
      {inputLine ? (
        <div
          data-testid={`session-summary-input-${s.session_id}`}
          className="truncate font-mono"
          style={{ color: sessionState?.highlightType === "input" ? palette.highlight : palette.normal }}
          title={`${inputLine.timestamp} ${inputLine.text}`}
        >
          {inputLine.timestamp} {inputLine.text}
        </div>
      ) : null}
      {outputLine ? (
        <div
          data-testid={`session-summary-output-${s.session_id}`}
          className="truncate font-mono"
          style={{ color: outputLine.emphasized ? palette.highlight : palette.normal }}
          title={`${outputLine.timestamp} ${outputLine.text}`}
        >
          {outputLine.timestamp} {outputLine.text}
        </div>
      ) : null}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Session technical detail lines (shown only when session node expanded)
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
  const idLine = `${formatSessionTime(s.created_at)} ${s.session_id} / ${s.native_session_id ?? "-"}`

  return (
    <div
      className="space-y-0.5 py-1 pl-3 text-[11px] leading-4"
      style={{
        marginLeft: detailOffset(depth),
        borderLeft: `1px solid ${palette.connector}`,
        color: palette.muted,
      }}
    >
      <div
        data-testid={`session-detail-id-${s.session_id}`}
        className="truncate font-mono"
        title={idLine}
      >
        {idLine}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Session row
// ---------------------------------------------------------------------------

const SessionRow = memo(function SessionRow({
  node,
  depth,
  expanded,
  onToggle,
  isCursor,
  isActive,
  isThemed,
  sessionState,
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
  sessionState?: SessionHighlightViewState
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

  if (expanded && (sessionState?.highlightType || sessionState?.activityEvent === "tool_use")) {
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
    <div
      data-testid={`session-block-${s.session_id}`}
      className="cursor-pointer"
      onClick={() => onSelect?.()}
      onDoubleClick={onToggle}
    >
      <div
        data-testid={`session-row-${s.session_id}`}
        data-node-id={sessionNodeId(s.session_id)}
        className="flex items-center gap-1.5 rounded py-1 pr-2 text-xs transition-colors"
        style={rowStyle}
      >
        <Badge
          data-testid={`session-index-${s.session_id}`}
          variant="outline"
          className="h-4 min-w-[1.25rem] justify-center px-1.5 text-[9px] tabular-nums"
          style={{
            backgroundColor:
              isCursor || isActive ? palette.badgeBgFocused : palette.badgeBg,
            borderColor:
              isCursor || isActive ? palette.badgeBgFocused : palette.badgeBg,
            color: palette.badgeText,
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
              backgroundColor:
                isCursor || isActive ? palette.badgeBgFocused : palette.badgeBg,
              borderColor:
                isCursor || isActive ? palette.badgeBgFocused : palette.badgeBg,
              color: palette.badgeText,
            }}
          >
            {subdirLabel}
          </Badge>
        )}
        <button
          data-testid={`session-toggle-${s.session_id}`}
          onClick={(e) => {
            e.stopPropagation()
            onToggle()
          }}
          onDoubleClick={(e) => {
            e.stopPropagation()
          }}
          className="ml-auto"
        >
          <ExpandChevron
            expanded={expanded}
            color={isCursor || isActive ? rowStyle.color ?? palette.contrast : palette.normal}
          />
        </button>
      </div>
      {expanded && (
        <SessionDetails
          session={node}
          depth={depth}
          isThemed={isThemed}
        />
      )}
      <SessionSummary
        session={node}
        depth={depth}
        isThemed={isThemed}
        sessionState={sessionState}
        currentUserEmail={currentUserEmail}
      />
    </div>
  )
})

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export function SessionTree({
  tree,
  expandedSet,
  cursorId,
  activeSessionId,
  sessionStateMap,
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
            sessionState={sessionStateMap?.get(node.session.session_id)}
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
    const displayPath = replaceHomeWithTilde(project.path)

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
          <div className="flex min-w-0 flex-1 items-baseline gap-2 overflow-hidden">
            <span className="shrink-0 font-medium">{project.name}</span>
            <span
              className="truncate text-xs text-muted-foreground"
              title={displayPath}
            >
              {displayPath}
            </span>
          </div>
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
