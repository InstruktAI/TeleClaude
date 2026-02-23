# Implementation Plan: fix-todos-watcher-not-notifying-websocket

## Approach

Add a `todosRefreshTrigger` counter to the Zustand store that increments on
`SYNC_TODOS`. In `app.tsx`, subscribe to this counter and re-fetch
`projectsWithTodos` when it changes.

## Tasks

- [x] 1. Add `todosRefreshTrigger: number` field to `TuiState.preparation` in `frontend/lib/store/types.ts`
- [x] 2. Increment `todosRefreshTrigger` in `SYNC_TODOS` handler in `frontend/lib/store/reducer.ts`
- [x] 3. Initialize `todosRefreshTrigger: 0` in the store's initial state in `frontend/lib/store/index.ts`
- [x] 4. In `frontend/cli/app.tsx`, subscribe to `todosRefreshTrigger` and re-fetch `projectsWithTodos` when it changes
- [x] 5. Update reducer tests in `frontend/lib/__tests__/reducer.test.ts` to verify `todosRefreshTrigger` increments on `SYNC_TODOS`
