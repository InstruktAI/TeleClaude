# Bug:

## Symptom

Right now when I'm changing state.yaml files, there is no feedback coming via the web socket. I don't see the front end in the TUI change its data. What is going on? Also, there's another thing which is that for a bug to be started it shows a pop-up that the DOR score is too low. But that should not happen for bugs. Bugs should just be able to be started. No gating. It is just a bug report and it will just enter the pipeline.

## Discovery Context

Reported by: manual
Session: none
Date: 2026-02-23

## Investigation

TodoWatcher correctly dispatches WebSocket events on file changes. The TUI frontend receives these events (`todos_updated`, `todo_created`, `todo_updated`, `todo_removed`) and dispatches `SYNC_TODOS` to the Zustand store. However, `projectsWithTodos` (React local state in `app.tsx`) is only fetched once on component mount and never refreshed when todo events arrive.

## Root Cause

The `SYNC_TODOS` action only prunes `expandedTodos` in the store but does not trigger a re-fetch of `projectsWithTodos`. The data in `app.tsx` local state becomes stale and the UI does not reflect changes.

## Fix Applied

Added `todosRefreshTrigger` counter field to TuiState. When `SYNC_TODOS` dispatches, the counter increments. In `app.tsx`, a new `useEffect` watches this counter and re-fetches `projectsWithTodos` whenever it changes. Integrated into existing Zustand store pattern. Commit: 2afae57a
