'use client';

import { useEffect } from 'react';
import { useQueryClient, type QueryClient } from '@tanstack/react-query';
import { useWS } from './WebSocketProvider';
import type { ProjectInfo, ProjectWithTodosInfo, TodoInfo, TodoRenamedEvent } from '../api/types';
import type { WsEvent } from './types';

const TODOS_QUERY_KEY = ['todos'] as const;
const PROJECTS_QUERY_KEY = ['projects'] as const;

type ProjectCacheEntry = ProjectInfo | ProjectWithTodosInfo;

function renameSlugReference(slug: string, event: TodoRenamedEvent): string {
  return slug === event.data.old_slug ? event.data.new_slug : slug;
}

function renameOptionalSlugReference(slug: string | null | undefined, event: TodoRenamedEvent): string | null | undefined {
  return slug === event.data.old_slug ? event.data.new_slug : slug;
}

function renameTodo(todo: TodoInfo, event: TodoRenamedEvent): TodoInfo {
  const nextSlug = renameSlugReference(todo.slug, event);
  const nextAfter = todo.after?.map((slug) => renameSlugReference(slug, event));
  const nextGroup = renameOptionalSlugReference(todo.group, event);
  const afterChanged = nextAfter !== undefined && nextAfter.some((slug, index) => slug !== todo.after?.[index]);

  if (nextSlug === todo.slug && !afterChanged && nextGroup === todo.group) {
    return todo;
  }

  return {
    ...todo,
    slug: nextSlug,
    after: nextAfter,
    group: nextGroup,
  };
}

function renameTodosCache(todos: TodoInfo[] | undefined, event: TodoRenamedEvent): TodoInfo[] | undefined {
  if (!todos) return todos;

  let changed = false;
  const nextTodos = todos.map((todo) => {
    const nextTodo = renameTodo(todo, event);
    if (nextTodo !== todo) {
      changed = true;
    }
    return nextTodo;
  });

  return changed ? nextTodos : todos;
}

function hasTodos(project: ProjectCacheEntry): project is ProjectWithTodosInfo {
  return 'todos' in project && Array.isArray(project.todos);
}

function renameProjectsCache(
  projects: ProjectCacheEntry[] | undefined,
  event: TodoRenamedEvent,
): ProjectCacheEntry[] | undefined {
  if (!projects) return projects;

  let changed = false;
  const nextProjects = projects.map((project) => {
    if (!hasTodos(project)) {
      return project;
    }

    const nextTodos = renameTodosCache(project.todos, event);
    if (nextTodos === project.todos || nextTodos === undefined) {
      return project;
    }

    changed = true;
    return {
      ...project,
      todos: nextTodos,
    };
  });

  return changed ? nextProjects : projects;
}

function applyTodoRename(queryClient: QueryClient, event: TodoRenamedEvent): void {
  queryClient.setQueriesData<TodoInfo[]>({ queryKey: TODOS_QUERY_KEY }, (todos) => renameTodosCache(todos, event));
  queryClient.setQueriesData<ProjectCacheEntry[]>({ queryKey: PROJECTS_QUERY_KEY }, (projects) =>
    renameProjectsCache(projects, event),
  );
}

/**
 * Listens to WebSocket events and updates or invalidates relevant React Query caches.
 * Should be mounted once inside the chat layout (after both QueryProvider
 * and WebSocketProvider).
 */
export function useCacheInvalidation(): void {
  const { onEvent } = useWS();
  const queryClient = useQueryClient();

  useEffect(() => {
    const unsub = onEvent('*', (event: WsEvent) => {
      switch (event.event) {
        case 'projects_initial':
        case 'project_updated':
        case 'projects_updated':
          queryClient.invalidateQueries({ queryKey: ['projects'] });
          break;

        case 'computer_updated':
          queryClient.invalidateQueries({ queryKey: ['computers'] });
          break;

        case 'todos_updated':
        case 'todo_created':
        case 'todo_updated':
        case 'todo_removed':
          queryClient.invalidateQueries({ queryKey: ['todos'] });
          break;

        case 'todo_renamed':
          applyTodoRename(queryClient, event);
          break;
      }
    });

    return unsub;
  }, [onEvent, queryClient]);
}
