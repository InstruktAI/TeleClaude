// @vitest-environment happy-dom
import React, { type ReactNode } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, renderHook } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import type { ProjectWithTodosInfo, TodoInfo, WsEvent } from '@/lib/api/types';
import { useCacheInvalidation } from '../useCacheInvalidation';

const WILDCARD_EVENT_TYPE = '*';
const TODO_RENAMED_EVENT_TYPE = 'todo_renamed';
const TODOS_QUERY_KEY = ['todos'] as const;
const PROJECTS_QUERY_KEY = ['projects', 'all'] as const;
const OLD_SLUG = 'rename-source';
const NEW_SLUG = 'rename-target';
const DEPENDENT_SLUG = 'rename-dependent';
const COMPUTER = 'local';
const PROJECT_PATH = '/workspace/project';
const PROJECT_NAME = 'project';
const TODO_DESCRIPTION = 'preserved todo state';
const TODO_FILE = 'notes.md';

type CapturedHandler = (event: WsEvent) => void;

const capturedHandlers = new Map<string, CapturedHandler>();

vi.mock('../WebSocketProvider', () => ({
  useWS: () => ({
    onEvent: (type: string, handler: CapturedHandler) => {
      capturedHandlers.set(type, handler);
      return () => capturedHandlers.delete(type);
    },
  }),
}));

function makeTodo(slug: string, overrides?: Partial<TodoInfo>): TodoInfo {
  return {
    slug,
    status: 'pending',
    description: null,
    computer: COMPUTER,
    project_path: PROJECT_PATH,
    has_requirements: false,
    has_impl_plan: false,
    build_status: null,
    review_status: null,
    deferrals_status: null,
    files: [],
    version_total: 1,
    after: [],
    group: null,
    delivered_at: null,
    lifecycle_phase: null,
    integration_phase: null,
    finalize_status: null,
    ...overrides,
  };
}

function makeProject(todos: TodoInfo[]): ProjectWithTodosInfo {
  return {
    computer: COMPUTER,
    name: PROJECT_NAME,
    path: PROJECT_PATH,
    description: null,
    todos,
    has_roadmap: true,
  };
}

function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
      },
    },
  });
}

function wrapperFor(queryClient: QueryClient): ({ children }: { children: ReactNode }) => ReactNode {
  return function Wrapper({ children }: { children: ReactNode }): ReactNode {
    return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
  };
}

function emitRename(): void {
  const handler = capturedHandlers.get(WILDCARD_EVENT_TYPE);
  if (!handler) {
    throw new Error('wildcard handler was not registered');
  }
  const event = {
    event: TODO_RENAMED_EVENT_TYPE,
    data: {
      old_slug: OLD_SLUG,
      new_slug: NEW_SLUG,
      computer: COMPUTER,
      project_path: PROJECT_PATH,
    },
  } satisfies WsEvent;
  act(() => {
    handler(event);
  });
}

function requireTodos(queryClient: QueryClient): TodoInfo[] {
  const todos = queryClient.getQueryData<TodoInfo[]>(TODOS_QUERY_KEY);
  if (!todos) {
    throw new Error('todos query data missing');
  }
  return todos;
}

function requireProjects(queryClient: QueryClient): ProjectWithTodosInfo[] {
  const projects = queryClient.getQueryData<ProjectWithTodosInfo[]>(PROJECTS_QUERY_KEY);
  if (!projects) {
    throw new Error('projects query data missing');
  }
  return projects;
}

describe('useCacheInvalidation', () => {
  afterEach(() => {
    capturedHandlers.clear();
    vi.clearAllMocks();
  });

  it('rekeys cached todos when a todo rename frame arrives without invalidating the list', () => {
    const renamedTodo = makeTodo(OLD_SLUG, {
      description: TODO_DESCRIPTION,
      files: [TODO_FILE],
    });
    const dependentTodo = makeTodo(DEPENDENT_SLUG, {
      after: [OLD_SLUG],
      group: OLD_SLUG,
    });
    const queryClient = createQueryClient();
    queryClient.setQueryData<TodoInfo[]>(TODOS_QUERY_KEY, [renamedTodo, dependentTodo]);
    queryClient.setQueryData<ProjectWithTodosInfo[]>(PROJECTS_QUERY_KEY, [makeProject([renamedTodo, dependentTodo])]);
    const invalidateQueries = vi.spyOn(queryClient, 'invalidateQueries');

    renderHook(() => useCacheInvalidation(), {
      wrapper: wrapperFor(queryClient),
    });

    emitRename();

    const todos = requireTodos(queryClient);
    expect(todos.find((todo) => todo.slug === OLD_SLUG)).toBeUndefined();
    expect(todos.find((todo) => todo.slug === NEW_SLUG)).toMatchObject({
      slug: NEW_SLUG,
      description: TODO_DESCRIPTION,
      files: [TODO_FILE],
    });
    expect(todos.find((todo) => todo.slug === DEPENDENT_SLUG)).toMatchObject({
      after: [NEW_SLUG],
      group: NEW_SLUG,
    });
    expect(requireProjects(queryClient)[0]?.todos.find((todo) => todo.slug === OLD_SLUG)).toBeUndefined();
    expect(requireProjects(queryClient)[0]?.todos.find((todo) => todo.slug === NEW_SLUG)).toBeDefined();
    expect(invalidateQueries).not.toHaveBeenCalled();
  });
});
