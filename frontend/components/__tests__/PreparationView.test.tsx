// @vitest-environment happy-dom

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { PreparationView } from '../preparation/PreparationView';
import type { ComputerInfo, ProjectWithTodosInfo, TodoInfo } from '@/lib/api/types';

/**
 * PreparationView render-level specifications for SC-2.
 *
 * These specs prove the user-facing pane renders grouped hierarchy, nests todos
 * under group parents, supports group expand/collapse, and respects dependency
 * ordering in the rendered node list. All tests remain expected failures until
 * the component and tree builder support grouped nodes.
 */

interface PreparationTodoFixture extends TodoInfo {
  after: string[];
  group: string | null;
  lifecycle_phase: string | null;
  integration_phase: string | null;
  finalize_status: string | null;
  delivered_at: string | null;
}

interface TreeNodeSummary {
  label: string;
  type: string;
  depth: number;
  expanded: boolean;
  hasChildren: boolean;
}

const fixtures = vi.hoisted(() => ({
  computers: [] as ComputerInfo[],
  projects: [] as ProjectWithTodosInfo[],
}));

vi.mock('@/lib/hooks/useComputers', () => ({
  useComputers: () => ({
    data: fixtures.computers,
    isLoading: false,
    error: null,
  }),
}));

vi.mock('@/lib/hooks/useProjects', () => ({
  useProjects: () => ({
    data: fixtures.projects,
    isLoading: false,
    error: null,
  }),
}));

vi.mock('@/components/preparation/NewTodoModal', () => ({
  NewTodoModal: () => null,
}));

vi.mock('@/components/preparation/NewBugModal', () => ({
  NewBugModal: () => null,
}));

vi.mock('@/lib/keys/bindings', () => ({
  findBinding: () => null,
}));

vi.mock('@/lib/hooks/useToast', () => ({
  toast: vi.fn(),
}));

vi.mock('@/components/preparation/TreeNode', () => ({
  TreeNode: ({
    label,
    type,
    depth,
    expanded,
    hasChildren,
    isCursor,
    onToggle,
  }: {
    label: string;
    type: string;
    depth: number;
    expanded: boolean;
    hasChildren: boolean;
    isCursor: boolean;
    onToggle: () => void;
  }) => (
    <button
      type="button"
      data-testid="tree-node"
      data-label={label}
      data-type={type}
      data-depth={String(depth)}
      data-expanded={String(expanded)}
      data-has-children={String(hasChildren)}
      data-cursor={String(isCursor)}
      onClick={onToggle}
    >
      {label}
    </button>
  ),
}));

function makeComputer(overrides?: Partial<ComputerInfo>): ComputerInfo {
  return {
    name: 'local',
    status: 'online',
    is_local: true,
    ...overrides,
  };
}

function makeTodo(overrides?: Partial<PreparationTodoFixture>): PreparationTodoFixture {
  return {
    slug: 'todo-default',
    status: 'pending',
    description: null,
    computer: 'local',
    project_path: '/workspace/teleclaude',
    has_requirements: true,
    has_impl_plan: false,
    build_status: null,
    review_status: null,
    deferrals_status: null,
    files: [],
    after: [],
    group: null,
    lifecycle_phase: null,
    integration_phase: null,
    finalize_status: null,
    delivered_at: null,
    ...overrides,
  };
}

function makeProject(todos: readonly PreparationTodoFixture[]): ProjectWithTodosInfo {
  return {
    computer: 'local',
    name: 'teleclaude',
    path: '/workspace/teleclaude',
    todos: todos as unknown as TodoInfo[],
  };
}

function setPreparationData(todos: readonly PreparationTodoFixture[]): void {
  fixtures.computers.splice(0, fixtures.computers.length, makeComputer());
  fixtures.projects.splice(0, fixtures.projects.length, makeProject(todos));
}

function getVisibleNodeSummaries(): TreeNodeSummary[] {
  return screen.getAllByTestId('tree-node').map((node) => {
    const element = node as HTMLButtonElement;
    return {
      label: element.dataset.label ?? '',
      type: element.dataset.type ?? '',
      depth: Number(element.dataset.depth ?? '0'),
      expanded: element.dataset.expanded === 'true',
      hasChildren: element.dataset.hasChildren === 'true',
    };
  });
}

function getNode(label: string, type?: string): HTMLButtonElement {
  const matches = screen
    .getAllByTestId('tree-node')
    .filter((node) => {
      const element = node as HTMLButtonElement;
      return element.dataset.label === label && (type === undefined || element.dataset.type === type);
    })
    .map((node) => node as HTMLButtonElement);

  if (matches.length !== 1) {
    throw new Error(`Expected exactly one node for label=${label} type=${type ?? '*'}, found ${matches.length}`);
  }

  return matches[0];
}

function queryNode(label: string, type?: string): HTMLButtonElement | null {
  const matches = screen
    .queryAllByTestId('tree-node')
    .filter((node) => {
      const element = node as HTMLButtonElement;
      return element.dataset.label === label && (type === undefined || element.dataset.type === type);
    })
    .map((node) => node as HTMLButtonElement);

  if (matches.length === 0) {
    return null;
  }

  if (matches.length > 1) {
    throw new Error(`Expected at most one node for label=${label} type=${type ?? '*'}, found ${matches.length}`);
  }

  return matches[0];
}

function expandProjectTree(): void {
  fireEvent.click(getNode('local', 'computer'));
  fireEvent.click(getNode('teleclaude', 'project'));
}

describe('PreparationView', () => {
  beforeEach(() => {
    fixtures.computers.splice(0, fixtures.computers.length);
    fixtures.projects.splice(0, fixtures.projects.length);
    HTMLElement.prototype.scrollIntoView = vi.fn();
  });

  afterEach(() => {
    cleanup();
  });

  it('renders explicit group nodes at the project level instead of flattening grouped todos into peer rows', () => {
    setPreparationData([makeTodo({ slug: 'release-anchor', group: 'release' }), makeTodo({ slug: 'root-todo' })]);

    render(<PreparationView isActive={false} />);
    expandProjectTree();

    expect(getVisibleNodeSummaries()).toEqual([
      {
        label: 'local',
        type: 'computer',
        depth: 0,
        expanded: true,
        hasChildren: true,
      },
      {
        label: 'teleclaude',
        type: 'project',
        depth: 1,
        expanded: true,
        hasChildren: true,
      },
      {
        label: 'release',
        type: 'group',
        depth: 2,
        expanded: false,
        hasChildren: true,
      },
      {
        label: 'root-todo',
        type: 'todo',
        depth: 2,
        expanded: false,
        hasChildren: false,
      },
    ]);
  });

  it('renders grouped todos as nested children under their group node in dependency order', () => {
    setPreparationData([
      makeTodo({ slug: 'release-child', group: 'release', after: ['release-anchor'] }),
      makeTodo({ slug: 'release-anchor', group: 'release' }),
    ]);

    render(<PreparationView isActive={false} />);
    expandProjectTree();
    fireEvent.click(getNode('release', 'group'));

    expect(getVisibleNodeSummaries()).toEqual([
      {
        label: 'local',
        type: 'computer',
        depth: 0,
        expanded: true,
        hasChildren: true,
      },
      {
        label: 'teleclaude',
        type: 'project',
        depth: 1,
        expanded: true,
        hasChildren: true,
      },
      {
        label: 'release',
        type: 'group',
        depth: 2,
        expanded: true,
        hasChildren: true,
      },
      {
        label: 'release-anchor',
        type: 'todo',
        depth: 3,
        expanded: false,
        hasChildren: false,
      },
      {
        label: 'release-child',
        type: 'todo',
        depth: 3,
        expanded: false,
        hasChildren: false,
      },
    ]);
  });

  it('collapses and re-expands a group node without affecting peer root todos', () => {
    setPreparationData([
      makeTodo({ slug: 'release-anchor', group: 'release' }),
      makeTodo({ slug: 'release-child', group: 'release', after: ['release-anchor'] }),
      makeTodo({ slug: 'ungrouped-peer' }),
    ]);

    render(<PreparationView isActive={false} />);
    expandProjectTree();

    const groupNode = getNode('release', 'group');
    fireEvent.click(groupNode);
    expect(queryNode('release-anchor', 'todo')).not.toBeNull();
    expect(queryNode('release-child', 'todo')).not.toBeNull();
    expect(queryNode('ungrouped-peer', 'todo')).not.toBeNull();

    fireEvent.click(getNode('release', 'group'));
    expect(queryNode('release-anchor', 'todo')).toBeNull();
    expect(queryNode('release-child', 'todo')).toBeNull();
    expect(queryNode('ungrouped-peer', 'todo')).not.toBeNull();
  });

  it('orders root nodes so a group containing a dependency renders before its dependent ungrouped todo', () => {
    setPreparationData([
      makeTodo({ slug: 'root-after-release', after: ['release-anchor'] }),
      makeTodo({ slug: 'release-anchor', group: 'release' }),
      makeTodo({ slug: 'root-independent' }),
    ]);

    render(<PreparationView isActive={false} />);
    expandProjectTree();

    const projectChildren = getVisibleNodeSummaries().slice(2);
    expect(projectChildren).toEqual([
      {
        label: 'release',
        type: 'group',
        depth: 2,
        expanded: false,
        hasChildren: true,
      },
      {
        label: 'root-after-release',
        type: 'todo',
        depth: 2,
        expanded: false,
        hasChildren: false,
      },
      {
        label: 'root-independent',
        type: 'todo',
        depth: 2,
        expanded: false,
        hasChildren: false,
      },
    ]);
  });
});
