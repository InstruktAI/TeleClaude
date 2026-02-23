# Bug: TUI PreparationView Not Refreshing on todo WebSocket Events

## Symptom

When todo files change (state.yaml modifications), the TUI's PreparationView does not refresh with updated todo data despite receiving WebSocket notifications. The todo list shows stale data until manual reload.

## Discovery Context

Reported by: manual
Session: none
Date: 2026-02-23

## Investigation

The TodoWatcher correctly dispatches WebSocket events when todo files change. The TUI's app component receives these events (`todos_updated`, `todo_created`, `todo_updated`, `todo_removed`) and dispatches `SYNC_TODOS` action to the Zustand store. However, `projectsWithTodos` (held in React local state in `frontend/cli/app.tsx`) is only fetched once on component mount during `useEffect(..., [])`. The `SYNC_TODOS` action only prunes `expandedTodos` in the store—it doesn't trigger a re-fetch of `projectsWithTodos`.

## Root Cause

In `frontend/cli/app.tsx`, `projectsWithTodos` state is populated once on mount and never updated when WebSocket todo events arrive. The `SYNC_TODOS` action in the reducer only manages `expandedTodos` pruning, not data refresh.

## Fix Applied

Added `todosRefreshTrigger: number` field to `TuiState.preparation` in the Zustand store. Updated the `SYNC_TODOS` reducer action to increment this counter. In `frontend/cli/app.tsx`, added a new `useEffect` that watches `todosRefreshTrigger` and calls `api.getProjectsWithTodos()` to refresh the data whenever the counter changes. Tests updated to verify counter increments. Commit: ac81602c
