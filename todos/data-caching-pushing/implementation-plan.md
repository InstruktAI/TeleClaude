# Implementation Plan: Data Caching & Push Architecture

## Overview

This plan implements the caching and push architecture defined in `requirements.md`. Work is divided into phases that can be implemented and tested incrementally.

---

## Phase 0: Fix REST/MCP Separation (Prerequisite)

**Goal:** Fix the architectural violation where REST adapter calls MCP server methods.

- [x] **Task 0.1:** Refactor REST adapter to use command handlers directly
  - Files: `teleclaude/adapters/rest_adapter.py`
  - Changes:
    1. Remove `MCPServerProtocol` class and `set_mcp_server()` method
    2. Remove `self.mcp_server` attribute
    3. Import `command_handlers` from `teleclaude.core`
    4. Replace MCP calls with command handler calls
    5. REST endpoints now return LOCAL data only

- [x] **Task 0.2:** Update daemon to not wire MCP server to REST adapter
  - Files: `teleclaude/daemon.py`
  - Changes: Remove call to `rest_adapter.set_mcp_server(mcp_server)`

- [x] **Task 0.3:** Update endpoint for ending sessions
  - Files: `teleclaude/adapters/rest_adapter.py`
  - Changes: `DELETE /sessions/{session_id}` calls `command_handlers.handle_end_session()` directly

### Verification:
- `make lint` passes
- `make test` passes
- TUI shows local sessions/projects instantly
- TUI no longer times out on startup

---

## Phase 1: DaemonCache Foundation

**Goal:** Create central cache with TTL support.

- [x] **Task 1.1:** Create DaemonCache class
  - File: `teleclaude/core/cache.py` (new)
- [ ] **Task 1.2:** Wire heartbeat data into cache (deferred to Phase 2+)
  - Files: `teleclaude/adapters/redis_adapter.py`
- [x] **Task 1.3:** Instantiate cache in daemon
  - Files: `teleclaude/daemon.py`

```python
class DaemonCache:
    """Central cache for remote data with TTL management."""

    def __init__(self):
        self._computers: dict[str, CachedComputer] = {}
        self._projects: dict[str, CachedProject] = {}  # key: f"{computer}:{path}"
        self._sessions: dict[str, CachedSession] = {}  # key: session_id
        self._todos: dict[str, list[CachedTodo]] = {}  # key: f"{computer}:{project_path}"
        self._subscribers: set[Callable] = set()
        self._interest: set[str] = set()  # "sessions", "preparation"

    # TTL management
    def is_stale(self, key: str, ttl_seconds: int) -> bool
    def invalidate(self, key: str) -> None
    def invalidate_all(self) -> None

    # Data access
    def get_computers(self) -> list[ComputerInfo]
    def get_projects(self, computer: str | None = None) -> list[ProjectInfo]
    def get_sessions(self, computer: str | None = None) -> list[SessionInfo]
    def get_todos(self, computer: str, project_path: str) -> list[TodoInfo]

    # Data updates (from events)
    def update_computer(self, computer: ComputerInfo) -> None
    def update_session(self, session: SessionInfo) -> None
    def remove_session(self, session_id: str) -> None
    def set_projects(self, computer: str, projects: list[ProjectInfo]) -> None
    def set_todos(self, computer: str, project_path: str, todos: list[TodoInfo]) -> None

    # Interest management
    def set_interest(self, interests: set[str]) -> None
    def get_interest(self) -> set[str]
    def has_interest(self, interest: str) -> bool

    # Change notifications
    def subscribe(self, callback: Callable[[str, object], None]) -> None
    def unsubscribe(self, callback: Callable) -> None
    def _notify(self, event: str, data: object) -> None
```

### Task 1.2: Wire heartbeat data into cache

**Files:** `teleclaude/adapters/redis_adapter.py`

**Changes:**
1. When heartbeat received from remote, update `cache.update_computer()`
2. Heartbeats already flow; just need to populate cache

### Task 1.3: Instantiate cache in daemon

**Files:** `teleclaude/daemon.py`

**Changes:**
1. Create `DaemonCache` instance
2. Pass to adapters that need it

### Verification:
- Cache stores computer info from heartbeats
- Cache auto-expires stale computers after 60s
- Unit tests for cache TTL logic

---

## Phase 2: REST Reads from Cache

**Goal:** REST endpoints read remote data from cache instead of querying remotes.

- [x] **Task 2.1:** Update REST endpoints to merge local + cached data
  - Files: `teleclaude/adapters/rest_adapter.py`
  - Changes:
    1. `GET /sessions`: Return local sessions + remote sessions from cache
    2. `GET /computers`: Return local computer + remote computers from cache
    3. `GET /projects`: Return local projects + remote projects from cache
  - Note: `/projects-with-todos` deferred (requires complex todo fetching logic)

- [ ] **Task 2.2:** Add cache population on first access (DEFERRED)
  - Files: `teleclaude/adapters/rest_adapter.py`
  - Changes: Background pull from remotes, cache invalidation triggers
  - Status: Deferred to Phase 4+ (requires peer discovery integration)

### Verification:
- ✅ TUI can load instantly (shows local data immediately)
- ⏸️ Remote data population requires heartbeat integration (Phase 4+)

---

## Phase 3: WebSocket Server

**Goal:** Push updates from daemon to TUI via WebSocket.

**Status:** ✅ Complete

- [x] **Task 3.1:** Add WebSocket endpoint to REST adapter
  - Files: `teleclaude/adapters/rest_adapter.py`
  - Changes:
    1. ✅ Added `/ws` endpoint accepting WebSocket connections
    2. ✅ Track connected clients in `_ws_clients` set
    3. ✅ Handle subscription messages: `{"subscribe": "sessions"}`, `{"subscribe": "preparation"}`
    4. ✅ Handle refresh messages: `{"refresh": true}`

- [x] **Task 3.2:** Push cache changes to WebSocket clients
  - Files: `teleclaude/adapters/rest_adapter.py`
  - Changes:
    1. ✅ Subscribe to `cache.subscribe()` in `__init__()`
    2. ✅ `_on_cache_change()` pushes to all connected WebSocket clients
    3. ✅ Message format: `{"event": "session_updated", "data": {...}}`

- [ ] **Task 3.3:** Update TUI to use WebSocket
  - Files: `teleclaude/cli/tui/app.py`, `teleclaude/cli/api_client.py`
  - Status: Deferred (TUI client-side implementation)
  - Changes:
    1. Add WebSocket client to `TelecAPIClient`
    2. Connect on startup, subscribe to relevant view
    3. Render from pushed data instead of polling REST

### Verification:
- ✅ WebSocket endpoint available at `/ws`
- ✅ Cache changes trigger notifications to WebSocket clients
- ⏸️ TUI WebSocket client deferred to future work

---

## Phase 4: Interest Management

**Goal:** Advertise interest in heartbeat so remotes know who wants events.

**Status:** ✅ Complete

- [x] **Task 4.1:** Track TUI interest in cache
  - Files: `teleclaude/adapters/rest_adapter.py`
  - Changes:
    1. ✅ When WebSocket client subscribes, call `cache.set_interest()` via `_update_cache_interest()`
    2. ✅ When WebSocket client disconnects, update interest to remove it

- [x] **Task 4.2:** Include interest in heartbeat
  - Files: `teleclaude/adapters/redis_adapter.py`, `teleclaude/daemon.py`
  - Changes:
    1. ✅ Redis adapter receives cache reference from daemon
    2. ✅ Heartbeat payload includes `interested_in: ["sessions"]` when cache has interest
    3. ⏸️ Parse `interested_in` from received heartbeats (deferred to Phase 5+)

### Verification:
- ✅ Cache interest tracked when WebSocket clients subscribe
- ✅ Heartbeat includes interest flags when cache has interest
- ✅ Interest flags removed when all WebSocket clients disconnect

---

## Phase 5: Event Push (Remote → Local)

**Goal:** Remote daemons push session events to interested peers.

**Status:** ✅ Complete

- [x] **Task 5.1:** Add event emitter to Redis adapter
  - Files: `teleclaude/adapters/redis_adapter.py`
  - Changes:
    1. ✅ Added cache property setter that subscribes to cache notifications
    2. ✅ Implemented `_on_cache_change()` callback
    3. ✅ Implemented `_push_session_event_to_peers()` to push events via Redis streams
    4. ✅ Implemented `_get_interested_computers()` to scan heartbeats for interested peers
    5. ✅ Events pushed to `session_events:{computer}` stream with maxlen=100

- [x] **Task 5.2:** Add INPUT_RECEIVED event
  - Status: Removed (redundant with session_updated events)
  - session_updated events already capture all input/output changes

### Verification:
- ✅ Remote session changes push to `session_events:{computer}` streams
- ✅ Only computers advertising interest in "sessions" receive events
- ✅ Event payload includes event type, data, timestamp, source_computer

---

## Phase 6: Event Receive (Local)

**Goal:** Local daemon receives events and updates cache.

**Status:** ✅ Complete

- [x] **Task 6.1:** Subscribe to session event stream
  - Files: `teleclaude/adapters/redis_adapter.py`
  - Changes:
    1. ✅ Added `_session_events_poll_task` background task
    2. ✅ Implemented `_poll_session_events()` to read from `session_events:{self.computer_name}` stream
    3. ✅ Only polls when cache has interest in "sessions"
    4. ✅ Parses incoming events and updates cache
    5. ✅ Handles both session_updated and session_removed events

- [x] **Task 6.2:** Trigger WebSocket push on event receive
  - Files: `teleclaude/adapters/redis_adapter.py`, `teleclaude/adapters/rest_adapter.py`
  - Changes:
    1. ✅ Cache update triggers `_notify()` to all subscribers
    2. ✅ REST adapter's WebSocket handler receives notification via cache subscription
    3. ✅ WebSocket pushes to connected TUI clients automatically

### Verification:
- ✅ Redis adapter subscribes to session events stream when cache has interest
- ✅ Incoming events update cache via `cache.update_session()` / `cache.remove_session()`
- ✅ Cache notifications trigger WebSocket push to TUI clients

---

## Phase 7: TUI Refactor

**Goal:** Complete TUI migration to WebSocket-based updates.

**Status:** ⏸️ Deferred (Server infrastructure complete, client pending)

### Implementation Status

**Server-Side (Complete):**
- ✅ WebSocket endpoint at `/ws` accepting connections
- ✅ Subscription handling (`{"subscribe": "sessions"}`)
- ✅ Cache change notifications pushed to WebSocket clients
- ✅ Event flow: Redis → Cache → REST adapter → WebSocket → TUI

**Client-Side (Deferred):**

- [ ] **Task 7.1:** Add WebSocket client to TUI
  - Files: `teleclaude/cli/api_client.py`, `teleclaude/cli/tui/app.py`
  - Blocker: Requires `websockets` library dependency (not currently in pyproject.toml)
  - Changes needed:
    1. Add websockets library to dependencies
    2. Create WebSocket client in TelecAPIClient
    3. Connect to `/ws` endpoint on Unix socket
    4. Send subscription message for "sessions"
    5. Receive pushed data in background task
    6. Update TUI state when data arrives

- [ ] **Task 7.2:** Remove REST polling
  - Files: `teleclaude/cli/tui/app.py`
  - Changes:
    1. Remove periodic refresh calls (keep only manual 'r' key refresh)
    2. Views render from WebSocket-pushed data instead of polling
    3. Initial data still fetched via REST on startup

### Deferral Rationale

1. **Dependency Addition:** Adding `websockets` library requires approval and testing
2. **TUI Architecture:** Requires integration of async WebSocket with synchronous curses event loop
3. **Testing Complexity:** WebSocket client needs comprehensive error handling and reconnection logic
4. **Current Functionality:** TUI currently works via REST; WebSocket is optimization for <1s updates

### Future Work

When implementing client-side WebSocket:
- Use `websockets` library for Unix socket connection
- Leverage existing `nest_asyncio` setup for async/sync integration
- Add reconnection logic with exponential backoff
- Handle graceful degradation to REST polling if WebSocket unavailable

### Verification:
- ✅ Server-side WebSocket infrastructure complete and tested
- ⏸️ TUI WebSocket client deferred pending dependency addition
- ⏸️ End-to-end <1s update latency pending client implementation

---

## Testing Strategy

### Unit Tests
- `tests/unit/test_cache.py` - TTL logic, data operations, interest management
- `tests/unit/test_rest_adapter.py` - Verify no MCP server dependency

### Integration Tests
- `tests/integration/test_cache_events.py` - Event flow from remote to cache to WebSocket
- `tests/integration/test_tui_websocket.py` - TUI connection and subscription

### Manual Testing
- Start TUI, verify instant load
- Create session on remote, verify appears in TUI within 1s
- Press 'r', verify refresh works
- Disconnect TUI, verify no traffic to remotes

---

## Rollback Plan

If issues arise:
1. REST endpoints can fall back to direct remote queries (slow but functional)
2. TUI can fall back to REST polling
3. Cache can be disabled without breaking functionality
