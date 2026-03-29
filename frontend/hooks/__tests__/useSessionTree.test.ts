// @vitest-environment happy-dom
import { describe, it, expect, beforeEach } from 'vitest'
import { renderHook, act, waitFor } from '@testing-library/react'
import {
  SESSION_TREE_STORAGE_KEY,
  useSessionTree,
} from '../useSessionTree'
import type { ComputerGroup } from '@/lib/sessions/tree'

function installLocalStorageMock() {
  const store = new Map<string, string>()

  Object.defineProperty(window, 'localStorage', {
    configurable: true,
    value: {
      getItem: (key: string) => store.get(key) ?? null,
      setItem: (key: string, value: string) => {
        store.set(key, value)
      },
      removeItem: (key: string) => {
        store.delete(key)
      },
      clear: () => {
        store.clear()
      },
    },
  })

  return store
}

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
                project_path: '/home/user/my-project',
                computer: 'local',
              },
              index: 1,
              displayIndex: '1',
              children: [
                {
                  type: 'session',
                  session: {
                    session_id: 'sess-child',
                    title: 'Child Session',
                    status: 'running',
                    active_agent: 'gemini',
                    project_path: '/home/user/my-project',
                    computer: 'local',
                    initiator_session_id: 'sess-1',
                  },
                  index: 1,
                  displayIndex: '1.1',
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
              displayIndex: '2',
              children: [],
            },
          ],
        },
      ],
    },
  ]
}

describe('useSessionTree', () => {
  beforeEach(() => {
    installLocalStorageMock()
  })

  it('flattenVisibleNodes returns correct order with default expanded state', () => {
    const { result } = renderHook(() => useSessionTree(makeTree()))
    const ids = result.current.visibleNodeIds
    // Computer and project default expanded, so we see:
    // computer:local, project:local:/home/user/my-project, session:sess-1, session:sess-child, session:sess-2
    expect(ids).toContain('computer:local')
    expect(ids).toContain('project:local:/home/user/my-project')
    expect(ids).toContain('session:sess-1')
    expect(ids).toContain('session:sess-child')
    expect(ids).toContain('session:sess-2')
    // Order: computer before project before sessions
    expect(ids.indexOf('computer:local')).toBeLessThan(
      ids.indexOf('project:local:/home/user/my-project'),
    )
    expect(ids.indexOf('project:local:/home/user/my-project')).toBeLessThan(
      ids.indexOf('session:sess-1'),
    )
  })

  it('moving cursor down advances to next visible node', () => {
    const { result } = renderHook(() => useSessionTree(makeTree()))
    // Cursor starts null, first move goes to first node
    act(() => result.current.moveCursor('down'))
    expect(result.current.cursorId).toBe(result.current.visibleNodeIds[0])
    act(() => result.current.moveCursor('down'))
    expect(result.current.cursorId).toBe(result.current.visibleNodeIds[1])
  })

  it('moving cursor up goes to previous visible node', () => {
    const { result } = renderHook(() => useSessionTree(makeTree()))
    // Move down twice then up once
    act(() => result.current.moveCursor('down'))
    act(() => result.current.moveCursor('down'))
    act(() => result.current.moveCursor('up'))
    expect(result.current.cursorId).toBe(result.current.visibleNodeIds[0])
  })

  it('cursor wraps from last to first', () => {
    const { result } = renderHook(() => useSessionTree(makeTree()))
    const lastIdx = result.current.visibleNodeIds.length - 1
    // Move to last
    for (let i = 0; i <= lastIdx; i++) {
      act(() => result.current.moveCursor('down'))
    }
    expect(result.current.cursorId).toBe(result.current.visibleNodeIds[lastIdx])
    // One more wraps to first
    act(() => result.current.moveCursor('down'))
    expect(result.current.cursorId).toBe(result.current.visibleNodeIds[0])
  })

  it('cursor wraps from first to last', () => {
    const { result } = renderHook(() => useSessionTree(makeTree()))
    // Move to first
    act(() => result.current.moveCursor('down'))
    expect(result.current.cursorId).toBe(result.current.visibleNodeIds[0])
    // Up wraps to last
    act(() => result.current.moveCursor('up'))
    const lastIdx = result.current.visibleNodeIds.length - 1
    expect(result.current.cursorId).toBe(result.current.visibleNodeIds[lastIdx])
  })

  it('collapsing a computer removes its children from flattened list', () => {
    const { result } = renderHook(() => useSessionTree(makeTree()))
    const before = result.current.visibleNodeIds.length
    act(() => result.current.toggleNode('computer:local'))
    const after = result.current.visibleNodeIds.length
    expect(after).toBeLessThan(before)
    expect(result.current.visibleNodeIds).not.toContain('project:local:/home/user/my-project')
    expect(result.current.visibleNodeIds).not.toContain('session:sess-1')
  })

  it('expanding a collapsed node adds children back', () => {
    const { result } = renderHook(() => useSessionTree(makeTree()))
    act(() => result.current.toggleNode('computer:local'))
    act(() => result.current.toggleNode('computer:local'))
    expect(result.current.visibleNodeIds).toContain('session:sess-1')
  })

  it('expandAll makes all nodes visible', () => {
    const { result } = renderHook(() => useSessionTree(makeTree()))
    act(() => result.current.toggleNode('computer:local'))
    act(() => result.current.expandAll())
    expect(result.current.visibleNodeIds).toContain('session:sess-1')
    expect(result.current.visibleNodeIds).toContain('session:sess-child')
  })

  it('collapseAll keeps only top-level nodes visible', () => {
    const { result } = renderHook(() => useSessionTree(makeTree()))
    act(() => result.current.collapseAll())
    expect(result.current.visibleNodeIds).toEqual(['computer:local'])
  })

  it('getNodeType returns correct type for each node', () => {
    const { result } = renderHook(() => useSessionTree(makeTree()))
    expect(result.current.getNodeType('computer:local')).toBe('computer')
    expect(result.current.getNodeType('project:local:/home/user/my-project')).toBe('project')
    expect(result.current.getNodeType('session:sess-1')).toBe('session')
  })

  it('getSessionId extracts session_id from session node id', () => {
    const { result } = renderHook(() => useSessionTree(makeTree()))
    expect(result.current.getSessionId('session:sess-1')).toBe('sess-1')
    expect(result.current.getSessionId('computer:local')).toBeNull()
  })

  it('restores persisted expanded nodes and cursor after hydration', async () => {
    window.localStorage.setItem(
      SESSION_TREE_STORAGE_KEY,
      JSON.stringify({
        expandedIds: ['computer:local'],
        cursorId: 'session:sess-2',
      }),
    )

    const { result } = renderHook(() => useSessionTree(makeTree()))

    await waitFor(() => {
      expect(result.current.expandedSet.has('computer:local')).toBe(true)
      expect(result.current.expandedSet.has('project:local:/home/user/my-project')).toBe(false)
      expect(result.current.cursorId).toBe('session:sess-2')
    })
  })

  it('initializes default expansion when tree data arrives after mount', async () => {
    const { result, rerender } = renderHook(
      ({ tree }: { tree: ComputerGroup[] }) => useSessionTree(tree),
      {
        initialProps: { tree: [] as ComputerGroup[] },
      },
    )

    rerender({ tree: makeTree() })

    await waitFor(() => {
      expect(result.current.expandedSet.has('computer:local')).toBe(true)
      expect(result.current.expandedSet.has('project:local:/home/user/my-project')).toBe(true)
    })
  })

  it('reveals a persisted session by expanding its ancestors', async () => {
    const { result } = renderHook(() => useSessionTree(makeTree()))

    act(() => {
      result.current.collapseAll()
    })

    act(() => {
      result.current.revealSession('sess-2')
    })

    await waitFor(() => {
      expect(result.current.expandedSet.has('computer:local')).toBe(true)
      expect(result.current.expandedSet.has('project:local:/home/user/my-project')).toBe(true)
      expect(result.current.cursorId).toBe('session:sess-2')
    })
  })
})
