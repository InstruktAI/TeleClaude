import { describe, it, expect } from 'vitest'
import {
  buildSessionTree,
  buildPrepTree,
  computerId,
  projectId,
  sessionId,
  todoId,
  fileId,
} from '@/lib/tree/builder'
import type { SessionDisplayInfo } from '@/lib/tree/types'
import { flattenTree, findFlatItemById, findFlatItemBySessionId, collectSessionIds, treePrefix } from '@/lib/tree/flatten'
import type { ComputerInfo, ProjectInfo, SessionInfo, ProjectWithTodosInfo, TodoInfo } from '@/lib/api/types'

// ---------------------------------------------------------------------------
// Factories
// ---------------------------------------------------------------------------

function makeComputer(name: string, overrides?: Partial<ComputerInfo>): ComputerInfo {
  return {
    name,
    status: 'online',
    user: null,
    host: null,
    is_local: name === 'local',
    tmux_binary: null,
    ...overrides,
  }
}

function makeProject(computer: string, path: string, name?: string): ProjectInfo {
  return { computer, name: name ?? path.split('/').pop() ?? '', path, description: null }
}

function makeSession(
  id: string,
  computer: string,
  projectPath: string,
  overrides?: Partial<SessionInfo>,
): SessionInfo {
  return {
    session_id: id,
    title: `Session ${id}`,
    status: 'active',
    computer,
    project_path: projectPath,
    created_at: '2025-01-01T00:00:00Z',
    last_activity: null,
    ...overrides,
  }
}

function makeTodo(slug: string, overrides?: Partial<TodoInfo>): TodoInfo {
  return {
    slug,
    status: 'ready',
    has_requirements: false,
    has_impl_plan: false,
    findings_count: 0,
    files: [],
    ...overrides,
  }
}

// ---------------------------------------------------------------------------
// ID helpers
// ---------------------------------------------------------------------------

describe('ID helpers', () => {
  it('computerId creates namespaced ID', () => {
    expect(computerId('mybox')).toBe('computer:mybox')
  })

  it('projectId creates namespaced ID', () => {
    expect(projectId('mybox', '/home/user/project')).toBe('project:mybox:/home/user/project')
  })

  it('sessionId creates namespaced ID', () => {
    expect(sessionId('abc-123')).toBe('session:abc-123')
  })

  it('todoId creates namespaced ID', () => {
    expect(todoId('mybox', '/proj', 'wi-01')).toBe('todo:mybox:/proj:wi-01')
  })

  it('fileId creates namespaced ID', () => {
    expect(fileId('mybox', '/proj', 'wi-01', 'foo.ts')).toBe('file:mybox:/proj:wi-01:foo.ts')
  })
})

// ---------------------------------------------------------------------------
// buildSessionTree
// ---------------------------------------------------------------------------

describe('buildSessionTree', () => {
  it('should return empty tree for no inputs', () => {
    const tree = buildSessionTree([], [], [])
    expect(tree).toEqual([])
  })

  it('should create computer nodes from computer list', () => {
    const computers = [makeComputer('alpha'), makeComputer('beta')]
    const tree = buildSessionTree(computers, [], [])
    expect(tree).toHaveLength(2)
    expect(tree[0].label).toBe('alpha')
    expect(tree[1].label).toBe('beta')
  })

  it('should sort computers alphabetically', () => {
    const computers = [makeComputer('zeta'), makeComputer('alpha')]
    const tree = buildSessionTree(computers, [], [])
    expect(tree[0].label).toBe('alpha')
    expect(tree[1].label).toBe('zeta')
  })

  it('should nest sessions under their project', () => {
    const computers = [makeComputer('box')]
    const projects = [makeProject('box', '/project')]
    const sessions = [makeSession('s1', 'box', '/project')]
    const tree = buildSessionTree(computers, projects, sessions)

    expect(tree).toHaveLength(1)
    const compNode = tree[0]
    expect(compNode.children).toHaveLength(1)
    const projNode = compNode.children[0]
    expect(projNode.type).toBe('project')
    expect(projNode.children).toHaveLength(1)
    expect(projNode.children[0].type).toBe('session')
    expect(projNode.children[0].id).toBe('session:s1')
  })

  it('should sort sticky sessions to the top', () => {
    const computers = [makeComputer('box')]
    const projects = [makeProject('box', '/project')]
    const sessions = [
      makeSession('s1', 'box', '/project', { created_at: '2025-01-03T00:00:00Z' }),
      makeSession('s2', 'box', '/project', { created_at: '2025-01-02T00:00:00Z' }),
      makeSession('s3', 'box', '/project', { created_at: '2025-01-01T00:00:00Z' }),
    ]
    const stickyIds = new Set(['s3'])
    const tree = buildSessionTree(computers, projects, sessions, stickyIds)

    const projNode = tree[0].children[0]
    expect(projNode.children[0].id).toBe('session:s3') // sticky first
    expect(projNode.children[1].id).toBe('session:s1') // then newest
    expect(projNode.children[2].id).toBe('session:s2')
  })

  it('should create synthetic parent for orphan sessions', () => {
    const computers = [makeComputer('box')]
    const projects: ProjectInfo[] = [] // no known projects
    const sessions = [makeSession('s1', 'box', '/unknown/path')]
    const tree = buildSessionTree(computers, projects, sessions)

    const compNode = tree[0]
    expect(compNode.children).toHaveLength(1)
    const projNode = compNode.children[0]
    expect(projNode.type).toBe('project')
    expect(projNode.label).toBe('/unknown/path')
    expect(projNode.children).toHaveLength(1)
  })

  it('should create synthetic computer for orphan sessions', () => {
    const computers: ComputerInfo[] = [] // no known computers
    const sessions = [makeSession('s1', 'ghost', '/proj')]
    const tree = buildSessionTree(computers, [], sessions)

    expect(tree).toHaveLength(1)
    expect(tree[0].label).toBe('ghost')
    expect(tree[0].data.computer.status).toBe('offline')
  })

  it('should nest AI-to-AI child sessions under their initiator', () => {
    const computers = [makeComputer('box')]
    const projects = [makeProject('box', '/project')]
    const sessions = [
      makeSession('parent', 'box', '/project'),
      makeSession('child', 'box', '/project', { initiator_session_id: 'parent' }),
    ]
    const tree = buildSessionTree(computers, projects, sessions)

    const projNode = tree[0].children[0]
    expect(projNode.children).toHaveLength(1) // only parent at project level
    const parentNode = projNode.children[0]
    expect(parentNode.id).toBe('session:parent')
    expect(parentNode.children).toHaveLength(1)
    expect(parentNode.children[0].id).toBe('session:child')
  })

  it('should assign display indices', () => {
    const computers = [makeComputer('box')]
    const projects = [makeProject('box', '/project')]
    const sessions = [
      makeSession('s1', 'box', '/project', { created_at: '2025-01-02T00:00:00Z' }),
      makeSession('s2', 'box', '/project', { created_at: '2025-01-01T00:00:00Z' }),
    ]
    const tree = buildSessionTree(computers, projects, sessions)
    const projNode = tree[0].children[0]
    expect((projNode.children[0].data as SessionDisplayInfo).displayIndex).toBe('1')
    expect((projNode.children[1].data as SessionDisplayInfo).displayIndex).toBe('2')
  })

  it('should compute session counts per computer', () => {
    const computers = [makeComputer('box')]
    const projects = [makeProject('box', '/project')]
    const sessions = [
      makeSession('s1', 'box', '/project'),
      makeSession('s2', 'box', '/project'),
    ]
    const tree = buildSessionTree(computers, projects, sessions)
    expect(tree[0].data.sessionCount).toBe(2)
  })

  it('should detect recent activity within 5 minutes', () => {
    const computers = [makeComputer('box')]
    const projects = [makeProject('box', '/project')]
    const recentTime = new Date(Date.now() - 60_000).toISOString() // 1 min ago
    const sessions = [makeSession('s1', 'box', '/project', { last_activity: recentTime })]
    const tree = buildSessionTree(computers, projects, sessions)
    expect(tree[0].data.recentActivity).toBe(true)
  })

  it('should not flag old activity as recent', () => {
    const computers = [makeComputer('box')]
    const projects = [makeProject('box', '/project')]
    const oldTime = new Date(Date.now() - 600_000).toISOString() // 10 min ago
    const sessions = [makeSession('s1', 'box', '/project', { last_activity: oldTime })]
    const tree = buildSessionTree(computers, projects, sessions)
    expect(tree[0].data.recentActivity).toBe(false)
  })
})

// ---------------------------------------------------------------------------
// buildPrepTree
// ---------------------------------------------------------------------------

describe('buildPrepTree', () => {
  it('should return empty tree for no projects', () => {
    const tree = buildPrepTree([])
    expect(tree).toEqual([])
  })

  it('should build project -> todo -> file hierarchy', () => {
    const projects: ProjectWithTodosInfo[] = [
      {
        computer: 'box',
        name: 'MyProject',
        path: '/project',
        description: null,
        todos: [
          makeTodo('wi-01', { files: ['main.ts', 'utils.ts'] }),
        ],
      },
    ]
    const tree = buildPrepTree(projects)
    expect(tree).toHaveLength(1)
    expect(tree[0].type).toBe('project')
    expect(tree[0].children).toHaveLength(1)
    const todoNode = tree[0].children[0]
    expect(todoNode.type).toBe('todo')
    expect(todoNode.children).toHaveLength(2)
    expect(todoNode.children[0].type).toBe('file')
    expect(todoNode.children[0].label).toBe('main.ts')
    expect(todoNode.children[1].label).toBe('utils.ts')
  })

  it('should add requirements.md and implementation-plan.md when flagged', () => {
    const projects: ProjectWithTodosInfo[] = [
      {
        computer: 'box',
        name: 'P',
        path: '/p',
        description: null,
        todos: [
          makeTodo('wi-01', {
            has_requirements: true,
            has_impl_plan: true,
            files: ['code.ts'],
          }),
        ],
      },
    ]
    const tree = buildPrepTree(projects)
    const todoNode = tree[0].children[0]
    const labels = todoNode.children.map((c) => c.label)
    expect(labels).toContain('requirements.md')
    expect(labels).toContain('implementation-plan.md')
    // Special files first
    expect(labels.indexOf('requirements.md')).toBeLessThan(labels.indexOf('code.ts'))
  })

  it('should not duplicate special files if already in file list', () => {
    const projects: ProjectWithTodosInfo[] = [
      {
        computer: 'box',
        name: 'P',
        path: '/p',
        description: null,
        todos: [
          makeTodo('wi-01', {
            has_requirements: true,
            files: ['requirements.md', 'code.ts'],
          }),
        ],
      },
    ]
    const tree = buildPrepTree(projects)
    const todoNode = tree[0].children[0]
    const labels = todoNode.children.map((c) => c.label)
    const reqCount = labels.filter((l) => l === 'requirements.md').length
    expect(reqCount).toBe(1)
  })

  it('should sort projects by path', () => {
    const projects: ProjectWithTodosInfo[] = [
      { computer: 'box', name: 'B', path: '/z', description: null, todos: [] },
      { computer: 'box', name: 'A', path: '/a', description: null, todos: [] },
    ]
    const tree = buildPrepTree(projects)
    expect(tree[0].label).toBe('A')
    expect(tree[1].label).toBe('B')
  })
})

// ---------------------------------------------------------------------------
// flattenTree
// ---------------------------------------------------------------------------

describe('flattenTree', () => {
  it('should return empty list for empty roots', () => {
    expect(flattenTree([])).toEqual([])
  })

  it('should flatten single-level tree', () => {
    const computers = [makeComputer('box')]
    const tree = buildSessionTree(computers, [], [])
    const flat = flattenTree(tree)
    expect(flat).toHaveLength(1)
    expect(flat[0].depth).toBe(0)
    expect(flat[0].index).toBe(0)
    expect(flat[0].isLast).toBe(true)
    expect(flat[0].parentId).toBeNull()
  })

  it('should assign increasing global indices', () => {
    const computers = [makeComputer('a'), makeComputer('b')]
    const tree = buildSessionTree(computers, [], [])
    const flat = flattenTree(tree)
    expect(flat[0].index).toBe(0)
    expect(flat[1].index).toBe(1)
  })

  it('should set depth for nested nodes', () => {
    const computers = [makeComputer('box')]
    const projects = [makeProject('box', '/project')]
    const sessions = [makeSession('s1', 'box', '/project')]
    const tree = buildSessionTree(computers, projects, sessions)
    const flat = flattenTree(tree)

    const depths = flat.map((f) => f.depth)
    expect(depths).toEqual([0, 1, 2]) // computer, project, session
  })

  it('should skip children of collapsed nodes', () => {
    const computers = [makeComputer('box')]
    const projects = [makeProject('box', '/project')]
    const sessions = [makeSession('s1', 'box', '/project')]
    const tree = buildSessionTree(computers, projects, sessions)

    const compId = computerId('box')
    const flat = flattenTree(tree, new Set([compId]))
    // The computer node itself is present, but project/session are skipped
    expect(flat).toHaveLength(1)
    expect(flat[0].node.id).toBe(compId)
  })

  it('should skip grandchildren when a middle node is collapsed', () => {
    const computers = [makeComputer('box')]
    const projects = [makeProject('box', '/project')]
    const sessions = [makeSession('s1', 'box', '/project')]
    const tree = buildSessionTree(computers, projects, sessions)

    const projId = projectId('box', '/project')
    const flat = flattenTree(tree, new Set([projId]))
    // computer + project visible; session hidden
    expect(flat).toHaveLength(2)
    expect(flat.find((f) => f.node.type === 'session')).toBeUndefined()
  })

  it('should set parentId for child nodes', () => {
    const computers = [makeComputer('box')]
    const projects = [makeProject('box', '/project')]
    const tree = buildSessionTree(computers, projects, [])
    const flat = flattenTree(tree)

    const projItem = flat.find((f) => f.node.type === 'project')
    expect(projItem?.parentId).toBe(computerId('box'))
  })

  it('should mark last child correctly', () => {
    const computers = [makeComputer('a'), makeComputer('b')]
    const tree = buildSessionTree(computers, [], [])
    const flat = flattenTree(tree)
    expect(flat[0].isLast).toBe(false)
    expect(flat[1].isLast).toBe(true)
  })
})

// ---------------------------------------------------------------------------
// Flatten utility functions
// ---------------------------------------------------------------------------

describe('findFlatItemById', () => {
  it('should find item by node ID', () => {
    const computers = [makeComputer('box')]
    const tree = buildSessionTree(computers, [], [])
    const flat = flattenTree(tree)
    const found = findFlatItemById(flat, computerId('box'))
    expect(found).toBeDefined()
    expect(found!.node.label).toBe('box')
  })

  it('should return undefined for missing ID', () => {
    const flat = flattenTree([])
    expect(findFlatItemById(flat, 'nope')).toBeUndefined()
  })
})

describe('findFlatItemBySessionId', () => {
  it('should find session by raw session ID', () => {
    const computers = [makeComputer('box')]
    const projects = [makeProject('box', '/proj')]
    const sessions = [makeSession('abc', 'box', '/proj')]
    const tree = buildSessionTree(computers, projects, sessions)
    const flat = flattenTree(tree)
    const found = findFlatItemBySessionId(flat, 'abc')
    expect(found).toBeDefined()
    expect(found!.node.id).toBe('session:abc')
  })
})

describe('collectSessionIds', () => {
  it('should collect raw session IDs from flat list', () => {
    const computers = [makeComputer('box')]
    const projects = [makeProject('box', '/proj')]
    const sessions = [
      makeSession('s1', 'box', '/proj'),
      makeSession('s2', 'box', '/proj'),
    ]
    const tree = buildSessionTree(computers, projects, sessions)
    const flat = flattenTree(tree)
    const ids = collectSessionIds(flat)
    expect(ids).toContain('s1')
    expect(ids).toContain('s2')
    expect(ids).toHaveLength(2)
  })

  it('should return empty for tree with no sessions', () => {
    const computers = [makeComputer('box')]
    const tree = buildSessionTree(computers, [], [])
    const flat = flattenTree(tree)
    expect(collectSessionIds(flat)).toEqual([])
  })
})

describe('treePrefix', () => {
  it('should return empty string for depth 0', () => {
    const computers = [makeComputer('box')]
    const tree = buildSessionTree(computers, [], [])
    const flat = flattenTree(tree)
    expect(treePrefix(flat[0])).toBe('')
  })

  it('should return branch connector for non-last child', () => {
    const computers = [makeComputer('box')]
    const projects = [makeProject('box', '/a'), makeProject('box', '/b')]
    const tree = buildSessionTree(computers, projects, [])
    const flat = flattenTree(tree)
    const firstProj = flat.find((f) => f.node.type === 'project' && !f.isLast)
    expect(firstProj).toBeDefined()
    expect(treePrefix(firstProj!)).toContain('\u251C')
  })

  it('should return end connector for last child', () => {
    const computers = [makeComputer('box')]
    const projects = [makeProject('box', '/a')]
    const tree = buildSessionTree(computers, projects, [])
    const flat = flattenTree(tree)
    const projItem = flat.find((f) => f.node.type === 'project')
    expect(projItem).toBeDefined()
    expect(treePrefix(projItem!)).toContain('\u2514')
  })
})
