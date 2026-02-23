# Requirements: fix-todos-watcher-not-notifying-websocket

## Problem

The TodoWatcher correctly detects filesystem changes and sends WebSocket events
to connected clients. The TUI frontend receives these events but never re-fetches
the `projectsWithTodos` data that the PreparationView renders from. The data is
only fetched once on mount.

## Root Cause

In `frontend/cli/app.tsx`, `projectsWithTodos` is held in React local state and
only set during the initial `fetchData()` call. The `useWebSocket` hook dispatches
`SYNC_TODOS` on todo events, but this action only prunes `expandedTodos` in the
store — it doesn't trigger a re-fetch of `projectsWithTodos`.

## Requirements

1. When the TUI receives a todo WebSocket event (`todos_updated`, `todo_created`,
   `todo_updated`, `todo_removed`), the `projectsWithTodos` state in `app.tsx`
   must be re-fetched from the API.
2. The fix must be minimal and follow existing patterns.
3. The web frontend (`useCacheInvalidation.ts`) is not affected — it uses React
   Query invalidation correctly.
4. Tests must cover the new behavior.

## Constraints

- No changes to the backend (Python) code required.
- The fix is TUI-specific (frontend/cli/).
