# Requirements: Cache Unification for Session UI Updates

## Objective

Make the cache the sole source of truth for session list updates in the UI. WebSocket updates must be derived from cache mutations, and all local session lifecycle changes must update the cache. The TUI must refresh only when sessions are added or removed, while session updates remain incremental.

## Outcomes

### O1: Cache is authoritative for session lifecycle

All local session lifecycle changes update the cache, and the cache holds the complete session list that the UI consumes.

### O2: Canonical session lifecycle events

Session lifecycle events are defined once in `teleclaude/core/events.py` and used consistently by cache, WS broadcast, and TUI.

Required session lifecycle events:
- `session_created`
- `session_removed`
- `session_updated`

### O2.1: Single internal event callback

Session lifecycle events are emitted through a single internal callback mechanism. Consumers subscribe by event constants (not string literals).

### O3: WS broadcasts derive only from cache

WebSocket updates for sessions are emitted only from cache mutations. There are no parallel WS event sources for sessions.

### O4: TUI behavior for sessions

- `session_updated` updates a single session in place and does not trigger full refresh.
- `session_created` and `session_removed` trigger a full refresh to rebuild the sessions list and related UI state.
- Preparation view does not subscribe to session events.

## Acceptance Criteria

- [ ] Local session creation results in cache mutation and a `session_created` WS event.
- [ ] Local session removal results in cache mutation and a `session_removed` WS event.
- [ ] Local session updates result in cache mutation and a `session_updated` WS event.
- [ ] WS session events originate only from cache changes.
- [ ] Sessions view refreshes only on `session_created` and `session_removed`.
- [ ] Sessions view applies incremental updates on `session_updated`.
- [ ] Preparation view has no session event subscriptions.
- [ ] Event consumers subscribe using event constants, not string literals.
- [ ] Tests cover session lifecycle WS behavior and pass.
- [ ] Lint passes.
