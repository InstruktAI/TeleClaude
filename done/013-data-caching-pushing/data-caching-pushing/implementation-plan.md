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

## Phase 3: WebSocket Server (DEFERRED)

**Goal:** Push updates from daemon to TUI via WebSocket.

**Status:** Deferred to future work - foundation complete in Phases 0-2

### Task 3.1: Add WebSocket endpoint to REST adapter

**Files:** `teleclaude/adapters/rest_adapter.py`

**Dependencies:** `websockets` or FastAPI's WebSocket support

**Changes:**
1. Add `/ws` endpoint accepting WebSocket connections
2. Track connected clients
3. Handle subscription messages: `{"subscribe": "sessions"}`, `{"subscribe": "preparation"}`
4. Handle refresh messages: `{"refresh": true}`

### Task 3.2: Push cache changes to WebSocket clients

**Files:** `teleclaude/adapters/rest_adapter.py`

**Changes:**
1. Subscribe to `cache.subscribe()` for change notifications
2. When cache changes, push to all connected WebSocket clients
3. Message format: `{"event": "session_updated", "data": {...}}`

### Task 3.3: Update TUI to use WebSocket

**Files:** `teleclaude/cli/tui/app.py`, `teleclaude/cli/api_client.py`

**Changes:**
1. Add WebSocket client to `TelecAPIClient`
2. Connect on startup, subscribe to relevant view
3. Render from pushed data instead of polling REST

### Verification:
- TUI connects via WebSocket
- Session changes appear in TUI without refresh
- Disconnection handled gracefully

---

## Phase 4: Interest Management

**Goal:** Advertise interest in heartbeat so remotes know who wants events.

### Task 4.1: Track TUI interest in cache

**Files:** `teleclaude/core/cache.py`

**Changes:**
1. When WebSocket client subscribes, call `cache.set_interest()`
2. When WebSocket client disconnects, remove interest

### Task 4.2: Include interest in heartbeat

**Files:** `teleclaude/adapters/redis_adapter.py`

**Changes:**
1. Heartbeat payload includes `interested_in: ["sessions"]` when cache has interest
2. Parse `interested_in` from received heartbeats

### Verification:
- Heartbeat includes interest flags when TUI connected
- Interest flags removed when TUI disconnects

---

## Phase 5: Event Push (Remote → Local)

**Goal:** Remote daemons push session events to interested peers.

### Task 5.1: Add event emitter to Redis adapter

**Files:** `teleclaude/adapters/redis_adapter.py`

**Changes:**
1. Hook into session event handlers (new_session, session_terminated, session_updated)
2. On event, check which peers are interested (from their heartbeats)
3. Push event to `session_events:{interested_computer}` stream

### Task 5.2: Add INPUT_RECEIVED event

**Files:** `teleclaude/core/events.py`

**Changes:**
1. Add `INPUT_RECEIVED = "input_received"` to `TeleClaudeEvents`
2. Emit this event when user sends input to session

### Verification:
- Remote session creation pushes event to interested local daemon
- Session updates (input, output) push events
- Only interested peers receive events

---

## Phase 6: Event Receive (Local)

**Goal:** Local daemon receives events and updates cache.

### Task 6.1: Subscribe to session event stream

**Files:** `teleclaude/adapters/redis_adapter.py`

**Changes:**
1. When cache has interest in sessions, subscribe to `session_events:{self.computer_name}`
2. Parse incoming events
3. Update cache with received data

### Task 6.2: Trigger WebSocket push on event receive

**Files:** `teleclaude/adapters/redis_adapter.py`, `teleclaude/adapters/rest_adapter.py`

**Changes:**
1. Cache update triggers `_notify()`
2. REST adapter's WebSocket handler receives notification
3. Push to connected TUI clients

### Verification:
- Remote session creation appears in TUI within 1s
- Remote session termination removes from TUI
- Session metadata updates (last_input, last_output) appear in TUI

---

## Phase 7: TUI Refactor

**Goal:** Complete TUI migration to WebSocket-based updates.

### Task 7.1: Remove REST polling from TUI

**Files:** `teleclaude/cli/tui/app.py`, `teleclaude/cli/tui/views/*.py`

**Changes:**
1. Remove any `stdscr.timeout()` polling
2. Views render from WebSocket-pushed data
3. Remove direct REST calls for session/project listing

### Task 7.2: Implement manual refresh

**Files:** `teleclaude/cli/tui/app.py`

**Changes:**
1. 'r' key sends `{"refresh": true}` to WebSocket
2. Daemon invalidates cache and re-fetches
3. Fresh data pushed to TUI

### Verification:
- TUI is fully reactive (no polling)
- Manual refresh works
- All success criteria from requirements.md met

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
