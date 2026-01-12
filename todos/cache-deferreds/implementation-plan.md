# Implementation Plan: Cache Population Completion

## Overview

This plan completes the deferred work from data-caching-pushing. The cache infrastructure exists but was never wired up to actually populate with remote data.

---

## Phase 1: Computers from Heartbeats

**Goal:** Remote computers appear in TUI via heartbeat-driven cache population.

- [ ] **Task 1.1:** Parse heartbeat and populate cache
  - File: `teleclaude/adapters/redis_adapter.py`
  - Location: Add to `_poll_session_events()` or create new `_poll_heartbeats()` task
  - Changes:
    1. When receiving heartbeat from remote (already parsed in `_get_interested_computers`)
    2. Call `cache.update_computer()` with computer info
    3. Cache auto-expires via existing TTL mechanism

- [ ] **Task 1.2:** Verify REST endpoint returns cached computers
  - File: `teleclaude/adapters/rest_adapter.py`
  - Verify: `GET /computers` already calls `cache.get_computers()`
  - Test: Remote computers should now appear

### Verification:
- Start TUI, remote computers appear within heartbeat interval (30s)
- Computer disappears after heartbeat TTL expires (60s)

---

## Phase 2: Initial Session Pull

**Goal:** Remote sessions appear on TUI startup, not just after events.

- [ ] **Task 2.1:** Pull sessions when interest registered
  - File: `teleclaude/adapters/redis_adapter.py`
  - Location: When `cache.has_interest("sessions")` first becomes true
  - Changes:
    1. For each known remote computer (from heartbeats)
    2. Call `list_sessions` MCP handler via Redis request
    3. Store results in cache via `cache.update_session()`

- [ ] **Task 2.2:** Trigger pull from REST adapter on WebSocket subscribe
  - File: `teleclaude/adapters/rest_adapter.py`
  - Location: `_handle_websocket()` when receiving subscription
  - Changes:
    1. After calling `cache.set_interest()`
    2. If "sessions" interest is new, trigger pull via redis adapter

### Verification:
- Start TUI, remote sessions appear within 1-2 seconds
- Not just after remote creates new session

---

## Phase 3: Remote Projects Pull

**Goal:** Remote projects appear when Sessions or Preparation view opens.

- [ ] **Task 3.1:** Add pull trigger on view access
  - File: `teleclaude/adapters/rest_adapter.py`
  - Location: `GET /projects` or `GET /projects-with-todos`
  - Changes:
    1. Check if remote project data is stale (TTL 5 min)
    2. If stale, trigger background pull from remotes
    3. Return cached data immediately (don't wait)

- [ ] **Task 3.2:** Implement remote project pull
  - File: `teleclaude/adapters/redis_adapter.py`
  - Changes:
    1. Add `pull_remote_projects(computer: str)` method
    2. Call `list_projects` MCP handler via Redis
    3. Store results via `cache.set_projects(computer, projects)`

### Verification:
- Open TUI, remote projects appear (possibly after short delay on first access)
- After 5 min, re-access triggers refresh

---

## Phase 4: Todos Pull

**Goal:** Remote todos appear in Preparation view.

- [ ] **Task 4.1:** Add pull trigger for todos
  - File: `teleclaude/adapters/rest_adapter.py`
  - Location: `GET /projects-with-todos`
  - Changes:
    1. For each remote project, check if todos are stale
    2. If stale, trigger background pull
    3. Merge local + cached remote data

- [ ] **Task 4.2:** Implement remote todos pull
  - File: `teleclaude/adapters/redis_adapter.py`
  - Changes:
    1. Add `pull_remote_todos(computer: str, project_path: str)` method
    2. Call `list_todos` MCP handler via Redis
    3. Store results via `cache.set_todos(computer, project_path, todos)`

### Verification:
- Open Preparation view, remote todos appear
- After 5 min TTL, re-access triggers refresh

---

## Phase 5: Manual Refresh Re-Fetch

**Goal:** 'r' key in TUI invalidates AND re-fetches.

- [ ] **Task 5.1:** Add re-fetch after invalidation
  - File: `teleclaude/cli/tui/app.py` or WebSocket message handler
  - Location: Where 'r' key triggers refresh
  - Changes:
    1. Call `cache.invalidate_all()`
    2. Trigger pull for all data types (computers, sessions, projects, todos)
    3. Send WebSocket message to signal refresh in progress

- [ ] **Task 5.2:** Handle refresh request in REST adapter
  - File: `teleclaude/adapters/rest_adapter.py`
  - Location: WebSocket message handler for `{"refresh": true}`
  - Changes:
    1. Invalidate cache
    2. Trigger pulls via redis adapter
    3. Send updated data once pulled

### Verification:
- Press 'r' in TUI
- All data refreshes from remotes
- Updated data appears within 2-3 seconds

---

## Phase 6: TTL-Based Auto-Refresh

**Goal:** Stale data triggers background refresh automatically.

- [ ] **Task 6.1:** Check staleness before returning data
  - File: `teleclaude/adapters/rest_adapter.py`
  - Changes:
    1. Before returning projects/todos, check `cache.is_stale()`
    2. If stale, trigger background pull
    3. Return current cached data (don't wait)

- [ ] **Task 6.2:** Add periodic staleness check
  - File: `teleclaude/adapters/redis_adapter.py`
  - Changes:
    1. Add background task to check cache staleness
    2. Trigger pulls for stale data
    3. Only when cache has interest

### Verification:
- Wait 5+ minutes with TUI open
- Projects/todos auto-refresh in background

---

## Testing Strategy

### Unit Tests
- `test_cache.py` - Already has tests for cache methods
- Add tests for population triggers

### Integration Tests
- Test heartbeat → cache.update_computer() flow
- Test WebSocket subscribe → initial pull flow
- Test manual refresh → re-fetch flow

### Manual Testing
- Start TUI, verify remote computers appear (heartbeat)
- Verify remote sessions appear on startup (initial pull)
- Verify remote projects appear in tree (pull on access)
- Press 'r', verify all data refreshes
- Wait 5 min, verify stale data refreshes

---

## File Change Summary

| File | Changes |
|------|---------|
| `teleclaude/adapters/redis_adapter.py` | Heartbeat → cache, pull methods, staleness polling |
| `teleclaude/adapters/rest_adapter.py` | Pull triggers on view access, refresh handling |
| `teleclaude/cli/tui/app.py` | Re-fetch after 'r' key |
| `teleclaude/core/cache.py` | No changes needed (methods exist) |

---

## Dependencies

- Requires Redis connection for remote pulls
- Requires MCP handlers to be working (they are)
- Cache infrastructure already exists (just needs callers)

## Estimated Effort

- Phase 1 (Computers): Small - just wire heartbeat to cache
- Phase 2 (Sessions): Medium - need initial pull mechanism
- Phase 3 (Projects): Medium - pull trigger + method
- Phase 4 (Todos): Medium - similar to projects
- Phase 5 (Manual Refresh): Small - add re-fetch after invalidate
- Phase 6 (Auto-Refresh): Medium - background staleness check
