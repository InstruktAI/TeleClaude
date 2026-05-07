/**
 * Test specifications for session tree builder.
 *
 * Behavioral contract: buildSessionTree transforms a flat array of SessionInfo
 * and ComputerInfo into a hierarchical tree: Computer → Project → Session,
 * with AI-to-AI child sessions nesting under their parent.
 *
 * All tests are marked as expected failures (it.fails) until implementation exists.
 */

import { describe, it, expect, beforeEach } from 'vitest'
import type { SessionInfo, ComputerInfo } from '@/lib/api/types'

// ---------------------------------------------------------------------------
// Factories
// ---------------------------------------------------------------------------

let idCounter = 0

beforeEach(() => {
  idCounter = 0
})

function makeSession(overrides?: Partial<SessionInfo>): SessionInfo {
  idCounter++
  return {
    session_id: `sess-${idCounter}`,
    detached: false,
    title: `Session ${idCounter}`,
    status: 'running',
    computer: 'local',
    project_path: '/home/user/project',
    ...overrides,
  }
}

function makeComputer(overrides?: Partial<ComputerInfo>): ComputerInfo {
  return {
    name: 'local',
    status: 'online',
    is_local: true,
    ...overrides,
  }
}

// ---------------------------------------------------------------------------
// Empty / edge cases
// ---------------------------------------------------------------------------

describe('buildSessionTree', () => {
  describe('empty and edge cases', () => {
    it('returns empty array for no sessions and no computers', async () => {
      const { buildSessionTree } = await import('@/lib/sessions/tree')
      const tree = buildSessionTree([], [])
      expect(tree).toEqual([])
    })

    it('returns computer node with empty projects when no sessions exist', async () => {
      const { buildSessionTree } = await import('@/lib/sessions/tree')
      const computers = [
        makeComputer({ name: 'remote-1', status: 'online', is_local: false }),
      ]
      const tree = buildSessionTree([], computers)
      expect(tree).toHaveLength(1)
      expect(tree[0].name).toBe('remote-1')
      expect(tree[0].status).toBe('online')
      expect(tree[0].isLocal).toBe(false)
      expect(tree[0].sessionCount).toBe(0)
      expect(tree[0].projects).toEqual([])
    })

    it('creates computer node from session even without matching ComputerInfo', async () => {
      const { buildSessionTree } = await import('@/lib/sessions/tree')
      const sessions = [makeSession({ computer: 'unknown-box' })]
      const tree = buildSessionTree(sessions, [])
      expect(tree).toHaveLength(1)
      expect(tree[0].name).toBe('unknown-box')
      expect(tree[0].sessionCount).toBe(1)
    })
  })

  // ---------------------------------------------------------------------------
  // Grouping by computer
  // ---------------------------------------------------------------------------

  describe('grouping by computer', () => {
    it('groups sessions into separate computer nodes', async () => {
      const { buildSessionTree } = await import('@/lib/sessions/tree')
      const sessions = [
        makeSession({ computer: 'alpha', project_path: '/p1' }),
        makeSession({ computer: 'beta', project_path: '/p2' }),
        makeSession({ computer: 'alpha', project_path: '/p3' }),
      ]
      const computers = [
        makeComputer({ name: 'alpha' }),
        makeComputer({ name: 'beta' }),
      ]
      const tree = buildSessionTree(sessions, computers)
      expect(tree).toHaveLength(2)
      const alphaNode = tree.find((c: { name: string }) => c.name === 'alpha')
      const betaNode = tree.find((c: { name: string }) => c.name === 'beta')
      expect(alphaNode).toBeDefined()
      expect(betaNode).toBeDefined()
      expect(alphaNode!.sessionCount).toBe(2)
      expect(betaNode!.sessionCount).toBe(1)
    })
  })

  // ---------------------------------------------------------------------------
  // Grouping by project within computer
  // ---------------------------------------------------------------------------

  describe('grouping by project', () => {
    it('groups sessions by project_path within a computer', async () => {
      const { buildSessionTree } = await import('@/lib/sessions/tree')
      const sessions = [
        makeSession({ computer: 'local', project_path: '/home/user/project-a' }),
        makeSession({ computer: 'local', project_path: '/home/user/project-b' }),
        makeSession({ computer: 'local', project_path: '/home/user/project-a' }),
      ]
      const computers = [makeComputer()]
      const tree = buildSessionTree(sessions, computers)
      expect(tree).toHaveLength(1)
      expect(tree[0].projects).toHaveLength(2)
      const projA = tree[0].projects.find(
        (p: { path: string }) => p.path === '/home/user/project-a',
      )
      const projB = tree[0].projects.find(
        (p: { path: string }) => p.path === '/home/user/project-b',
      )
      expect(projA).toBeDefined()
      expect(projB).toBeDefined()
      expect(projA!.sessionCount).toBe(2)
      expect(projB!.sessionCount).toBe(1)
    })

    it('derives project name from last segment of project_path', async () => {
      const { buildSessionTree } = await import('@/lib/sessions/tree')
      const sessions = [
        makeSession({ computer: 'local', project_path: '/home/user/my-project' }),
      ]
      const computers = [makeComputer()]
      const tree = buildSessionTree(sessions, computers)
      expect(tree[0].projects[0].name).toBe('my-project')
    })
  })

  // ---------------------------------------------------------------------------
  // Orphaned sessions (no project_path)
  // ---------------------------------------------------------------------------

  describe('orphaned sessions', () => {
    it('groups sessions without project_path under synthetic orphan project', async () => {
      const { buildSessionTree } = await import('@/lib/sessions/tree')
      const sessions = [
        makeSession({ computer: 'local', project_path: null }),
        makeSession({ computer: 'local', project_path: undefined }),
        makeSession({ computer: 'local', project_path: '/home/user/proj' }),
      ]
      const computers = [makeComputer()]
      const tree = buildSessionTree(sessions, computers)
      expect(tree).toHaveLength(1)
      expect(tree[0].projects).toHaveLength(2)
      const orphan = tree[0].projects.find(
        (p: { name: string }) => p.name === '\u2014',
      )
      expect(orphan).toBeDefined()
      expect(orphan!.sessionCount).toBe(2)
    })

    it('places orphan project last in the project list', async () => {
      const { buildSessionTree } = await import('@/lib/sessions/tree')
      const sessions = [
        makeSession({ computer: 'local', project_path: null }),
        makeSession({ computer: 'local', project_path: '/aaa' }),
      ]
      const computers = [makeComputer()]
      const tree = buildSessionTree(sessions, computers)
      const lastProject = tree[0].projects[tree[0].projects.length - 1]
      expect(lastProject.name).toBe('\u2014')
    })
  })

  // ---------------------------------------------------------------------------
  // Child session nesting via initiator_session_id
  // ---------------------------------------------------------------------------

  describe('child session nesting', () => {
    it('nests child sessions under parent via initiator_session_id', async () => {
      const { buildSessionTree } = await import('@/lib/sessions/tree')
      const parent = makeSession({
        session_id: 'parent-1',
        computer: 'local',
        project_path: '/proj',
      })
      const child = makeSession({
        session_id: 'child-1',
        computer: 'local',
        project_path: '/proj',
        initiator_session_id: 'parent-1',
      })
      const sessions = [parent, child]
      const computers = [makeComputer()]
      const tree = buildSessionTree(sessions, computers)
      const project = tree[0].projects[0]
      // Only parent at top level
      expect(project.sessions).toHaveLength(1)
      expect(project.sessions[0].session.session_id).toBe('parent-1')
      // Child nested under parent
      expect(project.sessions[0].children).toHaveLength(1)
      expect(project.sessions[0].children[0].session.session_id).toBe('child-1')
    })

    it('handles deeply nested children (grandchild sessions)', async () => {
      const { buildSessionTree } = await import('@/lib/sessions/tree')
      const grandparent = makeSession({
        session_id: 'gp',
        computer: 'local',
        project_path: '/proj',
      })
      const parent = makeSession({
        session_id: 'p',
        computer: 'local',
        project_path: '/proj',
        initiator_session_id: 'gp',
      })
      const child = makeSession({
        session_id: 'c',
        computer: 'local',
        project_path: '/proj',
        initiator_session_id: 'p',
      })
      const sessions = [grandparent, parent, child]
      const computers = [makeComputer()]
      const tree = buildSessionTree(sessions, computers)
      const project = tree[0].projects[0]
      expect(project.sessions).toHaveLength(1)
      expect(project.sessions[0].children).toHaveLength(1)
      expect(project.sessions[0].children[0].children).toHaveLength(1)
      expect(project.sessions[0].children[0].children[0].session.session_id).toBe(
        'c',
      )
    })

    it('treats child with non-existent parent as top-level session', async () => {
      const { buildSessionTree } = await import('@/lib/sessions/tree')
      const orphanChild = makeSession({
        session_id: 'orphan-child',
        computer: 'local',
        project_path: '/proj',
        initiator_session_id: 'non-existent-parent',
      })
      const sessions = [orphanChild]
      const computers = [makeComputer()]
      const tree = buildSessionTree(sessions, computers)
      const project = tree[0].projects[0]
      expect(project.sessions).toHaveLength(1)
      expect(project.sessions[0].session.session_id).toBe('orphan-child')
    })

    it('nests multiple children under the same parent', async () => {
      const { buildSessionTree } = await import('@/lib/sessions/tree')
      const parent = makeSession({
        session_id: 'parent',
        computer: 'local',
        project_path: '/proj',
      })
      const child1 = makeSession({
        session_id: 'child-1',
        computer: 'local',
        project_path: '/proj',
        initiator_session_id: 'parent',
        created_at: '2024-03-01T00:00:00Z',
      })
      const child2 = makeSession({
        session_id: 'child-2',
        computer: 'local',
        project_path: '/proj',
        initiator_session_id: 'parent',
        created_at: '2024-02-01T00:00:00Z',
      })
      const sessions = [parent, child1, child2]
      const computers = [makeComputer()]
      const tree = buildSessionTree(sessions, computers)
      const project = tree[0].projects[0]
      expect(project.sessions).toHaveLength(1)
      expect(project.sessions[0].children).toHaveLength(2)
      // Children sorted by created_at descending
      expect(project.sessions[0].children[0].session.session_id).toBe('child-1')
      expect(project.sessions[0].children[1].session.session_id).toBe('child-2')
    })
  })

  // ---------------------------------------------------------------------------
  // Sorting
  // ---------------------------------------------------------------------------

  describe('sorting', () => {
    it('sorts computers alphabetically by name', async () => {
      const { buildSessionTree } = await import('@/lib/sessions/tree')
      const sessions = [
        makeSession({ computer: 'charlie', project_path: '/p' }),
        makeSession({ computer: 'alpha', project_path: '/p' }),
        makeSession({ computer: 'bravo', project_path: '/p' }),
      ]
      const computers = [
        makeComputer({ name: 'charlie' }),
        makeComputer({ name: 'alpha' }),
        makeComputer({ name: 'bravo' }),
      ]
      const tree = buildSessionTree(sessions, computers)
      expect(tree.map((c: { name: string }) => c.name)).toEqual([
        'alpha',
        'bravo',
        'charlie',
      ])
    })

    it('sorts projects alphabetically by name within computer', async () => {
      const { buildSessionTree } = await import('@/lib/sessions/tree')
      const sessions = [
        makeSession({ computer: 'local', project_path: '/zebra' }),
        makeSession({ computer: 'local', project_path: '/apple' }),
        makeSession({ computer: 'local', project_path: '/mango' }),
      ]
      const computers = [makeComputer()]
      const tree = buildSessionTree(sessions, computers)
      expect(tree[0].projects.map((p: { name: string }) => p.name)).toEqual([
        'apple',
        'mango',
        'zebra',
      ])
    })

    it('sorts sessions by created_at descending within project', async () => {
      const { buildSessionTree } = await import('@/lib/sessions/tree')
      const sessions = [
        makeSession({
          computer: 'local',
          project_path: '/proj',
          session_id: 'oldest',
          created_at: '2024-01-01T00:00:00Z',
        }),
        makeSession({
          computer: 'local',
          project_path: '/proj',
          session_id: 'newest',
          created_at: '2024-03-01T00:00:00Z',
        }),
        makeSession({
          computer: 'local',
          project_path: '/proj',
          session_id: 'middle',
          created_at: '2024-02-01T00:00:00Z',
        }),
      ]
      const computers = [makeComputer()]
      const tree = buildSessionTree(sessions, computers)
      const sessionIds = tree[0].projects[0].sessions.map(
        (s: { session: SessionInfo }) => s.session.session_id,
      )
      expect(sessionIds).toEqual(['newest', 'middle', 'oldest'])
    })

    it('handles sessions with null created_at (sorted last)', async () => {
      const { buildSessionTree } = await import('@/lib/sessions/tree')
      const sessions = [
        makeSession({
          computer: 'local',
          project_path: '/proj',
          session_id: 'no-activity',
          created_at: null,
        }),
        makeSession({
          computer: 'local',
          project_path: '/proj',
          session_id: 'has-activity',
          created_at: '2024-01-01T00:00:00Z',
        }),
      ]
      const computers = [makeComputer()]
      const tree = buildSessionTree(sessions, computers)
      const sessionIds = tree[0].projects[0].sessions.map(
        (s: { session: SessionInfo }) => s.session.session_id,
      )
      expect(sessionIds[0]).toBe('has-activity')
      expect(sessionIds[1]).toBe('no-activity')
    })

    it('does not reshuffle sessions when only last_activity changes', async () => {
      const { buildSessionTree } = await import('@/lib/sessions/tree')
      const sessions = [
        makeSession({
          computer: 'local',
          project_path: '/proj',
          session_id: 'first-created',
          created_at: '2024-03-01T00:00:00Z',
          last_activity: '2024-01-01T00:00:00Z',
        }),
        makeSession({
          computer: 'local',
          project_path: '/proj',
          session_id: 'second-created',
          created_at: '2024-02-01T00:00:00Z',
          last_activity: '2024-12-01T00:00:00Z',
        }),
      ]
      const computers = [makeComputer()]
      const tree = buildSessionTree(sessions, computers)
      const sessionIds = tree[0].projects[0].sessions.map(
        (s: { session: SessionInfo }) => s.session.session_id,
      )
      expect(sessionIds).toEqual(['first-created', 'second-created'])
    })
  })

  // ---------------------------------------------------------------------------
  // Indexing
  // ---------------------------------------------------------------------------

  describe('session indexing', () => {
    it('assigns 1-based index to top-level sessions within project', async () => {
      const { buildSessionTree } = await import('@/lib/sessions/tree')
      const sessions = [
        makeSession({
          computer: 'local',
          project_path: '/proj',
          last_activity: '2024-03-01T00:00:00Z',
        }),
        makeSession({
          computer: 'local',
          project_path: '/proj',
          last_activity: '2024-02-01T00:00:00Z',
        }),
        makeSession({
          computer: 'local',
          project_path: '/proj',
          last_activity: '2024-01-01T00:00:00Z',
        }),
      ]
      const computers = [makeComputer()]
      const tree = buildSessionTree(sessions, computers)
      const indices = tree[0].projects[0].sessions.map(
        (s: { index: number }) => s.index,
      )
      expect(indices).toEqual([1, 2, 3])
    })

    it('does not count child sessions in top-level index sequence', async () => {
      const { buildSessionTree } = await import('@/lib/sessions/tree')
      const sessions = [
        makeSession({
          session_id: 'parent-1',
          computer: 'local',
          project_path: '/proj',
          last_activity: '2024-03-01T00:00:00Z',
        }),
        makeSession({
          session_id: 'child-of-1',
          computer: 'local',
          project_path: '/proj',
          initiator_session_id: 'parent-1',
        }),
        makeSession({
          session_id: 'parent-2',
          computer: 'local',
          project_path: '/proj',
          last_activity: '2024-02-01T00:00:00Z',
        }),
      ]
      const computers = [makeComputer()]
      const tree = buildSessionTree(sessions, computers)
      const topLevel = tree[0].projects[0].sessions
      expect(topLevel).toHaveLength(2)
      expect(topLevel[0].index).toBe(1)
      expect(topLevel[1].index).toBe(2)
    })
  })

  // ---------------------------------------------------------------------------
  // Computer enrichment from ComputerInfo
  // ---------------------------------------------------------------------------

  describe('computer enrichment', () => {
    it('enriches computer nodes with ComputerInfo metadata', async () => {
      const { buildSessionTree } = await import('@/lib/sessions/tree')
      const sessions = [makeSession({ computer: 'remote-box' })]
      const computers = [
        makeComputer({ name: 'remote-box', status: 'offline', is_local: false }),
      ]
      const tree = buildSessionTree(sessions, computers)
      expect(tree[0].status).toBe('offline')
      expect(tree[0].isLocal).toBe(false)
    })

    it('defaults unknown computer status when no ComputerInfo provided', async () => {
      const { buildSessionTree } = await import('@/lib/sessions/tree')
      const sessions = [makeSession({ computer: 'mystery' })]
      const tree = buildSessionTree(sessions, [])
      expect(tree[0].name).toBe('mystery')
      // Should have a reasonable default status, not crash
      expect(tree[0].status).toBeDefined()
    })
  })

  // ---------------------------------------------------------------------------
  // Session count accuracy
  // ---------------------------------------------------------------------------

  describe('session counts', () => {
    it('computer sessionCount includes all sessions across projects', async () => {
      const { buildSessionTree } = await import('@/lib/sessions/tree')
      const sessions = [
        makeSession({ computer: 'local', project_path: '/proj-a' }),
        makeSession({ computer: 'local', project_path: '/proj-a' }),
        makeSession({ computer: 'local', project_path: '/proj-b' }),
      ]
      const computers = [makeComputer()]
      const tree = buildSessionTree(sessions, computers)
      expect(tree[0].sessionCount).toBe(3)
    })

    it('computer sessionCount includes child sessions', async () => {
      const { buildSessionTree } = await import('@/lib/sessions/tree')
      const sessions = [
        makeSession({
          session_id: 'p1',
          computer: 'local',
          project_path: '/proj',
        }),
        makeSession({
          session_id: 'c1',
          computer: 'local',
          project_path: '/proj',
          initiator_session_id: 'p1',
        }),
        makeSession({
          session_id: 'c2',
          computer: 'local',
          project_path: '/proj',
          initiator_session_id: 'p1',
        }),
      ]
      const computers = [makeComputer()]
      const tree = buildSessionTree(sessions, computers)
      expect(tree[0].sessionCount).toBe(3)
    })

    it('project sessionCount includes child sessions', async () => {
      const { buildSessionTree } = await import('@/lib/sessions/tree')
      const sessions = [
        makeSession({
          session_id: 'p1',
          computer: 'local',
          project_path: '/proj',
        }),
        makeSession({
          session_id: 'c1',
          computer: 'local',
          project_path: '/proj',
          initiator_session_id: 'p1',
        }),
      ]
      const computers = [makeComputer()]
      const tree = buildSessionTree(sessions, computers)
      expect(tree[0].projects[0].sessionCount).toBe(2)
    })
  })
})
