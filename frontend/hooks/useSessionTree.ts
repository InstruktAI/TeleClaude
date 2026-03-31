"use client"

import {
  useMemo,
  useCallback,
  useEffect,
  useRef,
  type Dispatch,
  type SetStateAction,
} from "react"
import {
  computerNodeId,
  projectNodeId,
  sessionNodeId,
  type ComputerGroup,
  type NodeId,
  type SessionTreeNode,
} from "@/lib/sessions/tree"
import { usePersistentState } from "@/hooks/usePersistentState"

export const SESSION_TREE_STORAGE_KEY = "teleclaude.chat.session-tree"

interface SessionTreeOptions {
  isReady?: boolean
}

interface SessionTreePersistenceState {
  expandedIds: NodeId[]
  cursorId: NodeId | null
}

function collectAllNodeIds(tree: ComputerGroup[]): NodeId[] {
  const ids: NodeId[] = []
  for (const computer of tree) {
    ids.push(computerNodeId(computer.name))
    for (const project of computer.projects) {
      ids.push(projectNodeId(computer.name, project.path))
      collectSessionIds(project.sessions, ids)
    }
  }
  return ids
}

function collectSessionIds(sessions: SessionTreeNode[], ids: NodeId[]) {
  for (const node of sessions) {
    ids.push(sessionNodeId(node.session.session_id))
    if (node.children.length > 0) {
      collectSessionIds(node.children, ids)
    }
  }
}

function collectDefaultExpandedIds(tree: ComputerGroup[]): NodeId[] {
  const ids: NodeId[] = []
  for (const computer of tree) {
    ids.push(computerNodeId(computer.name))
    for (const project of computer.projects) {
      ids.push(projectNodeId(computer.name, project.path))
    }
  }
  return ids
}

function collectComputerNodeIds(tree: ComputerGroup[]): NodeId[] {
  return tree.map((computer) => computerNodeId(computer.name))
}

function collectProjectNodeIds(tree: ComputerGroup[]): NodeId[] {
  const ids: NodeId[] = []
  for (const computer of tree) {
    for (const project of computer.projects) {
      ids.push(projectNodeId(computer.name, project.path))
    }
  }
  return ids
}

function collectSessionNodeIds(sessions: SessionTreeNode[]): NodeId[] {
  const ids: NodeId[] = []
  for (const node of sessions) {
    ids.push(sessionNodeId(node.session.session_id))
    if (node.children.length > 0) {
      ids.push(...collectSessionNodeIds(node.children))
    }
  }
  return ids
}

function findProjectSessionsForNode(
  tree: ComputerGroup[],
  nodeId: NodeId,
): SessionTreeNode[] | null {
  if (nodeId.startsWith("project:")) {
    for (const computer of tree) {
      for (const project of computer.projects) {
        if (projectNodeId(computer.name, project.path) === nodeId) {
          return project.sessions
        }
      }
    }
    return null
  }

  if (!nodeId.startsWith("session:")) return null
  const targetSessionId = nodeId.slice("session:".length)

  for (const computer of tree) {
    for (const project of computer.projects) {
      if (projectHasSession(project.sessions, targetSessionId)) {
        return project.sessions
      }
    }
  }

  return null
}

function flattenVisible(
  tree: ComputerGroup[],
  expanded: Set<NodeId>,
): NodeId[] {
  const result: NodeId[] = []
  for (const computer of tree) {
    const cId = computerNodeId(computer.name)
    result.push(cId)
    if (!expanded.has(cId)) continue
    for (const project of computer.projects) {
      const pId = projectNodeId(computer.name, project.path)
      result.push(pId)
      if (!expanded.has(pId)) continue
      flattenSessions(project.sessions, expanded, result)
    }
  }
  return result
}

function flattenSessions(
  sessions: SessionTreeNode[],
  expanded: Set<NodeId>,
  result: NodeId[],
) {
  for (const node of sessions) {
    const sId = sessionNodeId(node.session.session_id)
    result.push(sId)
    // Child sessions are always visible when parent project is expanded
    if (node.children.length > 0) {
      flattenSessions(node.children, expanded, result)
    }
  }
}

function sanitizeExpandedIds(
  expandedIds: NodeId[],
  validNodeIds: ReadonlySet<NodeId>,
): NodeId[] {
  const next: NodeId[] = []
  for (const id of expandedIds) {
    if (!validNodeIds.has(id)) continue
    if (next.includes(id)) continue
    next.push(id)
  }
  return next
}

function sanitizeCursorId(
  cursorId: NodeId | null,
  validNodeIds: ReadonlySet<NodeId>,
): NodeId | null {
  if (!cursorId) return null
  return validNodeIds.has(cursorId) ? cursorId : null
}

function resolveStateUpdate<T>(
  update: SetStateAction<T>,
  current: T,
): T {
  return typeof update === "function"
    ? (update as (prev: T) => T)(current)
    : update
}

function arraysEqual(left: readonly string[], right: readonly string[]): boolean {
  if (left.length !== right.length) return false
  return left.every((value, index) => value === right[index])
}

function findSessionAncestors(
  tree: ComputerGroup[],
  targetSessionId: string,
): NodeId[] {
  for (const computer of tree) {
    for (const project of computer.projects) {
      const ancestors = [
        computerNodeId(computer.name),
        projectNodeId(computer.name, project.path),
      ]
      if (projectHasSession(project.sessions, targetSessionId)) {
        return ancestors
      }
    }
  }
  return []
}

function projectHasSession(
  sessions: SessionTreeNode[],
  targetSessionId: string,
): boolean {
  for (const node of sessions) {
    if (node.session.session_id === targetSessionId) return true
    if (projectHasSession(node.children, targetSessionId)) return true
  }
  return false
}

export function useSessionTree(
  tree: ComputerGroup[],
  { isReady = true }: SessionTreeOptions = {},
) {
  const defaultExpandedIds = useMemo(
    () => collectDefaultExpandedIds(tree),
    [tree],
  )
  const validNodeIds = useMemo(
    () => new Set(collectAllNodeIds(tree)),
    [tree],
  )
  const [persistedState, setPersistedState, persistence] =
    usePersistentState<SessionTreePersistenceState>(
      SESSION_TREE_STORAGE_KEY,
      () => ({
        expandedIds: defaultExpandedIds,
        cursorId: null,
      }),
    )
  const defaultsBootstrappedRef = useRef(defaultExpandedIds.length > 0)

  useEffect(() => {
    if (!persistence.isHydrated || !isReady) return
    if (validNodeIds.size === 0) return

    setPersistedState((prev) => {
      const expandedIds = sanitizeExpandedIds(prev.expandedIds, validNodeIds)
      const cursorId = sanitizeCursorId(prev.cursorId, validNodeIds)

      if (
        arraysEqual(prev.expandedIds, expandedIds) &&
        prev.cursorId === cursorId
      ) {
        return prev
      }

      return {
        expandedIds,
        cursorId,
      }
    })
  }, [
    isReady,
    persistence.isHydrated,
    setPersistedState,
    validNodeIds,
  ])

  useEffect(() => {
    if (!persistence.isHydrated || !isReady) return
    if (persistence.hasStoredValue) {
      defaultsBootstrappedRef.current = true
      return
    }
    if (defaultsBootstrappedRef.current) return
    if (defaultExpandedIds.length === 0) return

    defaultsBootstrappedRef.current = true
    setPersistedState((prev) => {
      if (prev.expandedIds.length > 0) return prev
      return {
        ...prev,
        expandedIds: defaultExpandedIds,
      }
    })
  }, [
    defaultExpandedIds,
    isReady,
    persistence.hasStoredValue,
    persistence.isHydrated,
    setPersistedState,
  ])

  const expandedSet = useMemo(
    () => new Set<NodeId>(persistedState.expandedIds),
    [persistedState.expandedIds],
  )
  const cursorId = persistedState.cursorId

  const visibleNodeIds = useMemo(
    () => flattenVisible(tree, expandedSet),
    [tree, expandedSet],
  )

  const setCursorId: Dispatch<SetStateAction<NodeId | null>> = useCallback(
    (update) => {
      setPersistedState((prev) => ({
        ...prev,
        cursorId: sanitizeCursorId(
          resolveStateUpdate(update, prev.cursorId),
          validNodeIds,
        ),
      }))
    },
    [setPersistedState, validNodeIds],
  )

  const toggleNode = useCallback((id: NodeId) => {
    setPersistedState((prev) => {
      const next = new Set(prev.expandedIds)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return {
        ...prev,
        expandedIds: sanitizeExpandedIds([...next], validNodeIds),
      }
    })
  }, [setPersistedState, validNodeIds])

  const moveCursor = useCallback(
    (direction: "up" | "down") => {
      setCursorId((prev) => {
        if (visibleNodeIds.length === 0) return null
        if (prev === null) {
          return direction === "down"
            ? visibleNodeIds[0]
            : visibleNodeIds[visibleNodeIds.length - 1]
        }
        const idx = visibleNodeIds.indexOf(prev)
        if (idx === -1) return visibleNodeIds[0]
        if (direction === "down") {
          return visibleNodeIds[(idx + 1) % visibleNodeIds.length]
        } else {
          return visibleNodeIds[(idx - 1 + visibleNodeIds.length) % visibleNodeIds.length]
        }
      })
    },
    [visibleNodeIds],
  )

  const expandAll = useCallback(() => {
    setPersistedState((prev) => ({
      ...prev,
      expandedIds: collectAllNodeIds(tree),
    }))
  }, [setPersistedState, tree])

  const collapseAll = useCallback(() => {
    setPersistedState((prev) => ({
      ...prev,
      expandedIds: [],
    }))
  }, [setPersistedState])

  const setExpandedInScope = useCallback(
    (nodeIds: NodeId[], expanded: boolean) => {
      if (nodeIds.length === 0) return
      setPersistedState((prev) => {
        const next = new Set(prev.expandedIds)
        for (const nodeId of nodeIds) {
          if (expanded) next.add(nodeId)
          else next.delete(nodeId)
        }
        return {
          ...prev,
          expandedIds: sanitizeExpandedIds([...next], validNodeIds),
        }
      })
    },
    [setPersistedState, validNodeIds],
  )

  const expandScope = useCallback(
    (nodeId: NodeId | null) => {
      if (!nodeId) return
      if (nodeId.startsWith("computer:")) {
        setExpandedInScope(collectComputerNodeIds(tree), true)
        return
      }
      if (nodeId.startsWith("project:")) {
        setExpandedInScope(collectProjectNodeIds(tree), true)
        return
      }
      const sessions = findProjectSessionsForNode(tree, nodeId)
      if (!sessions) return
      setExpandedInScope(collectSessionNodeIds(sessions), true)
    },
    [setExpandedInScope, tree],
  )

  const collapseScope = useCallback(
    (nodeId: NodeId | null) => {
      if (!nodeId) return
      if (nodeId.startsWith("computer:")) {
        setExpandedInScope(collectComputerNodeIds(tree), false)
        return
      }
      if (nodeId.startsWith("project:")) {
        setExpandedInScope(collectProjectNodeIds(tree), false)
        return
      }
      const sessions = findProjectSessionsForNode(tree, nodeId)
      if (!sessions) return
      setExpandedInScope(collectSessionNodeIds(sessions), false)
    },
    [setExpandedInScope, tree],
  )

  const revealSession = useCallback(
    (sessionId: string) => {
      const nextCursorId = sessionNodeId(sessionId)
      const ancestors = findSessionAncestors(tree, sessionId)
      setPersistedState((prev) => {
        const expandedIds = sanitizeExpandedIds(
          [...new Set([...prev.expandedIds, ...ancestors])],
          validNodeIds,
        )
        const cursorId = sanitizeCursorId(nextCursorId, validNodeIds)

        if (
          arraysEqual(prev.expandedIds, expandedIds) &&
          prev.cursorId === cursorId
        ) {
          return prev
        }

        return {
          expandedIds,
          cursorId,
        }
      })
    },
    [setPersistedState, tree, validNodeIds],
  )

  const getNodeType = useCallback(
    (id: NodeId): "computer" | "project" | "session" | null => {
      if (id.startsWith("computer:")) return "computer"
      if (id.startsWith("project:")) return "project"
      if (id.startsWith("session:")) return "session"
      return null
    },
    [],
  )

  const getSessionId = useCallback(
    (id: NodeId): string | null => {
      if (!id.startsWith("session:")) return null
      return id.slice("session:".length)
    },
    [],
  )

  return {
    cursorId,
    visibleNodeIds,
    expandedSet,
    setCursorId,
    moveCursor,
    toggleNode,
    expandAll,
    collapseAll,
    expandScope,
    collapseScope,
    revealSession,
    getNodeType,
    getSessionId,
  }
}
