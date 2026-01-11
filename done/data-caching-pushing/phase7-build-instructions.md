# Build Instructions: Review Fixes + Phase 7

## PRIORITY 1: Fix Critical Review Issues

**These must be fixed FIRST before Phase 7 implementation.**

### Critical Issue 1: Fire-and-forget asyncio task in redis_adapter.py

**File:** `teleclaude/adapters/redis_adapter.py:1086`

Current code:
```python
asyncio.create_task(self._push_session_event_to_peers(event, data))
```

Fix by adding exception callback:
```python
task = asyncio.create_task(self._push_session_event_to_peers(event, data))
task.add_done_callback(
    lambda t: logger.error("Event push task failed: %s", t.exception())
    if t.done() and not t.cancelled() and t.exception() else None
)
```

### Critical Issue 2: Fire-and-forget WebSocket send in rest_adapter.py

**File:** `teleclaude/adapters/rest_adapter.py:476`

Current code:
```python
asyncio.create_task(ws.send_json({"event": event, "data": data}))
```

Fix by adding done callback that removes dead clients:
```python
task = asyncio.create_task(ws.send_json({"event": event, "data": data}))

def on_send_done(t: asyncio.Task[None], client: WebSocket = ws) -> None:
    if t.done() and t.exception():
        logger.warning("WebSocket send failed, removing client: %s", t.exception())
        self._ws_clients.discard(client)
        self._client_subscriptions.pop(client, None)

task.add_done_callback(on_send_done)
```

### Important Issue: Cache subscription cleanup

**File:** `teleclaude/adapters/redis_adapter.py:122-128`

Update the cache property setter to unsubscribe from old cache:
```python
@cache.setter
def cache(self, value: "DaemonCache | None") -> None:
    if self._cache:
        self._cache.unsubscribe(self._on_cache_change)
    self._cache = value
    if value:
        value.subscribe(self._on_cache_change)
        logger.info("Redis adapter subscribed to cache notifications")
```

### After fixing review issues

Run tests: `make test-unit`
Run lint: `make lint`
Commit with message: `fix(async): add exception handling to fire-and-forget tasks`

---

## PRIORITY 2: Phase 7 - TUI WebSocket Client

## Context

Phases 0-6 are complete. The server-side WebSocket infrastructure is working:
- `/ws` endpoint in REST adapter accepts connections
- Cache changes push to WebSocket clients
- Redis adapter pushes/receives events between computers

**Your task:** Implement the TUI client-side WebSocket integration.

## Task 7.1: Add WebSocket Dependency and Client

### Step 1: Add websockets library

**File:** `pyproject.toml`

Add to dependencies:
```toml
"websockets>=12.0",
```

Then run: `uv sync`

### Step 2: Create WebSocket client in TelecAPIClient

**File:** `teleclaude/cli/api_client.py`

The TUI uses `TelecAPIClient` to communicate with the daemon via Unix socket REST API. Add WebSocket support:

1. Add import at top:
```python
import websockets
from websockets.sync.client import connect as ws_connect
```

2. Add WebSocket connection method that connects to the daemon's Unix socket:
```python
def connect_websocket(self, on_message: Callable[[dict], None]) -> None:
    """Connect to daemon WebSocket for push updates.

    Args:
        on_message: Callback for received messages
    """
    # Unix socket WebSocket URL format
    ws_url = f"ws+unix://{self.socket_path}:/ws"
    # ... implement connection and message loop
```

3. Add subscription method:
```python
def subscribe(self, interests: list[str]) -> None:
    """Subscribe to event types (e.g., ["sessions", "preparation"])."""
    # Send {"subscribe": "sessions"} for each interest
```

### Step 3: Integrate with TUI app

**File:** `teleclaude/cli/tui/app.py`

The TUI uses `nest_asyncio` to run async code in the synchronous curses loop. Look at existing patterns.

1. Start WebSocket connection on TUI startup
2. Handle incoming messages to update state
3. On `session_updated` event, refresh the sessions view
4. On disconnect, attempt reconnection with backoff

## Task 7.2: Replace Polling with Push Updates

### Current behavior (to change)

The TUI currently polls REST endpoints periodically for updates. Find and remove these polling mechanisms.

### Target behavior

1. Initial data fetched via REST on startup (keep this)
2. Updates received via WebSocket push (new)
3. Manual refresh with 'r' key still triggers REST fetch (keep this)
4. No automatic polling - only push-driven updates

**Files to check:**
- `teleclaude/cli/tui/app.py` - Main app loop
- `teleclaude/cli/tui/views/sessions.py` - Sessions view
- `teleclaude/cli/tui/views/preparation.py` - Preparation view

## Testing Requirements

1. Run `make test-unit` - all tests must pass
2. Run `make lint` - must pass
3. Manual test: Start TUI, create session on remote, verify it appears within 1 second

## Architecture Notes

### Unix Socket WebSocket Connection

The websockets library supports Unix sockets. The daemon's REST adapter runs on a Unix socket at `self.socket_path`. The WebSocket endpoint is at `/ws` on that socket.

Example connection pattern:
```python
# Using websockets library with Unix socket
import socket
from websockets.sync.client import ClientConnection

# Create Unix socket connection
sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
sock.connect(socket_path)
# Then upgrade to WebSocket...
```

Or use the URI format: `ws+unix:///path/to/socket:/ws`

### Message Format

**Subscription request:**
```json
{"subscribe": "sessions"}
```

**Incoming events:**
```json
{"event": "session_updated", "data": {...session info...}}
{"event": "session_removed", "data": {"session_id": "..."}}
```

### Error Handling

- Handle connection failures gracefully
- Implement reconnection with exponential backoff
- Fall back to REST if WebSocket unavailable
- Log connection state changes

## Success Criteria

From requirements.md:
- [ ] Session updates appear in TUI within 1 second of change
- [ ] No polling traffic when TUI is connected via WebSocket
- [ ] Manual refresh ('r' key) still works
- [ ] TUI starts instantly (local data shown immediately)

## Commit Format

When complete, commit with:
```
feat(tui): implement WebSocket client for real-time updates (Phase 7)

- Add websockets dependency
- Create WebSocket client in TelecAPIClient
- Connect TUI to /ws endpoint on startup
- Replace polling with push-driven updates
- Handle reconnection with exponential backoff

🤖 Generated with [TeleClaude](https://github.com/InstruktAI/TeleClaude)

Co-Authored-By: TeleClaude <noreply@instrukt.ai>
```
