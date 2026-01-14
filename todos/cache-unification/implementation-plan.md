# Implementation Plan: Cache Unification for Session UI Updates

## Phase 1: Canonical session events

- [ ] Add `session_created` and `session_removed` to `teleclaude/core/events.py` alongside `session_updated`.
- [ ] Ensure the cache emits these three events as the canonical session lifecycle events.
- [ ] Define a single internal event callback that dispatches these events to subscribers by event constants.
 - [ ] Implement the callback as a DB-layer post-commit hook on session lifecycle methods (`create_session`, `update_session`, `delete_session`) so cache updates are centralized.

## Phase 2: Cache is authoritative for local sessions

- [ ] On local session creation, update cache with the new session summary and emit `session_created`.
- [ ] On local session removal, remove the session from cache and emit `session_removed`.
- [ ] On local session updates, update cache and emit `session_updated`.
- [ ] Ensure local session summaries match the shape used by remote session summaries.

## Phase 3: WS broadcasts from cache only

- [ ] REST WS broadcasts session events only from cache notifications.
- [ ] Initial snapshot responses (`sessions_initial`) remain as subscribe responses.

## Phase 4: TUI session behavior

- [ ] Sessions view subscribes to `session_created`, `session_removed`, `session_updated`.
- [ ] Sessions view triggers full refresh only on `session_created` and `session_removed`.
- [ ] Sessions view applies incremental updates on `session_updated`.
- [ ] Preparation view remains unchanged and does not subscribe to session events.

## Phase 5: Tests

- [ ] Add tests for cache mutation on local create, update, remove.
- [ ] Add tests that WS session events are emitted from cache changes.
- [ ] Add tests for TUI session refresh vs incremental update behavior.

## Phase 6: Validation

- [ ] Verify local create emits `session_created` and triggers refresh.
- [ ] Verify local remove emits `session_removed` and triggers refresh.
- [ ] Verify local updates emit `session_updated` and do not trigger refresh.
