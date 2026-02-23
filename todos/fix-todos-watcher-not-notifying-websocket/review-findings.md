# Review Findings: fix-todos-watcher-not-notifying-websocket

## Verdict: APPROVE

## Critical

(none)

## Important

(none)

## Suggestions

- **Consider debouncing rapid todo events** (`frontend/cli/app.tsx:277-283`): If multiple todo WebSocket events fire in quick succession (e.g. bulk operations), each increment triggers a separate `getProjectsWithTodos()` fetch. The existing session re-fetch has the same characteristic, so this is consistent — but a debounce could reduce unnecessary API calls in burst scenarios. Low priority; the current behavior is correct and the API calls are lightweight.

## Paradigm-Fit Assessment

1. **Data flow**: The implementation uses the established Zustand store with discriminated union intents (`SYNC_TODOS` → reducer → state change → React re-render). The counter-trigger pattern (`todosRefreshTrigger`) with `useTuiStore` selector + `useEffect` is more idiomatic React/Zustand than the session re-fetch pattern (which uses raw `tuiStore.subscribe`). No bypass of the data layer.
2. **Component reuse**: No copy-paste duplication found. The new code adds a minimal field to the existing `PreparationViewState` type and a single `useEffect` in `app.tsx`. Checked against the session re-fetch effect and the `useCacheInvalidation.ts` web frontend pattern — no duplicated logic.
3. **Pattern consistency**: Follows the established intent → reducer → component subscription pattern. Type additions follow the existing `PreparationViewState` structure. Test additions follow the existing `SYNC_TODOS` describe block pattern.

## Requirements Verification

1. **R1 (re-fetch on todo events)**: Verified. `useWebSocket.ts:116-131` dispatches `SYNC_TODOS` on all four todo event types → reducer increments `todosRefreshTrigger` → `app.tsx:277-283` useEffect triggers `api.getProjectsWithTodos()` → `setProjectsWithTodos` updates React state. Full chain confirmed.
2. **R2 (minimal fix)**: Verified. 1 type field, 1 reducer line, 1 initial state line, 12 lines of effect code, 1 test — total ~16 lines of production code across 4 files. No over-engineering.
3. **R3 (web frontend unaffected)**: Verified. No changes to `frontend/lib/ws/useCacheInvalidation.ts`. Diff scope confirms TUI-only changes.
4. **R4 (tests)**: Verified. Reducer test covers initial state (0), single increment (1), and consecutive increment (2). `freshState()` fixture correctly updated. No integration test for the effect itself, consistent with the existing session re-fetch effect which also lacks one.

## Why No Issues

1. **Paradigm-fit verified**: Checked data flow (Zustand store pattern), component reuse (no duplication with session re-fetch or web cache invalidation), and pattern consistency (discriminated union intents, type extensions, test structure).
2. **Requirements validated**: All four requirements traced through the code with concrete call chains. Each requirement maps to specific lines in the diff.
3. **Copy-paste duplication checked**: The `useEffect` in `app.tsx:277-283` is structurally similar to the session re-fetch effect (252-270) but operates on different state and different API — this is appropriate parallel structure, not duplication. The `useCacheInvalidation.ts` web frontend handles the same events via React Query invalidation — correctly separate implementation for a different rendering paradigm.
