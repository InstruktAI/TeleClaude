"use client"

import { useState, useMemo, useCallback } from "react"
import {
  computerNodeId,
  projectNodeId,
  sessionNodeId,
  type ComputerGroup,
  type NodeId,
  type SessionTreeNode,
} from "@/lib/sessions/tree"

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

export function useSessionTree(tree: ComputerGroup[]) {
  const [expandedSet, setExpandedSet] = useState<Set<NodeId>>(() => {
    const initial = new Set<NodeId>()
    for (const computer of tree) {
      initial.add(computerNodeId(computer.name))
      for (const project of computer.projects) {
        initial.add(projectNodeId(computer.name, project.path))
      }
    }
    return initial
  })

  const [cursorId, setCursorId] = useState<NodeId | null>(null)

  const visibleNodeIds = useMemo(
    () => flattenVisible(tree, expandedSet),
    [tree, expandedSet],
  )

  const toggleNode = useCallback((id: NodeId) => {
    setExpandedSet((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }, [])

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
    setExpandedSet(new Set(collectAllNodeIds(tree)))
  }, [tree])

  const collapseAll = useCallback(() => {
    setExpandedSet(new Set<NodeId>())
  }, [])

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
    getNodeType,
    getSessionId,
  }
}
