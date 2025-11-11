# ~~REST API~~ Unix Socket: Notification Interface for Claude Code Hooks

## 🔄 ARCHITECTURE PIVOT (2025-01-11)

**Original approach: REST API with SSL + API keys**
**New approach: Unix domain socket**

### Why the Change?

After implementing Phases 1-5 (SSL, auth, endpoints), we realized:

1. **Wrong tool for the job** - HTTP/REST is for network communication, not local IPC
2. **Overcomplicated security** - API keys + SSL for localhost is architectural bloat
3. **Performance overhead** - HTTP parsing, uvicorn, SSL handshake for same-machine calls
4. **Multi-computer already solved** - Redis adapter handles cross-machine messaging
5. **Unix sockets are standard** - MCP server already uses `/tmp/teleclaude.sock` pattern

### Benefits of Unix Socket:

- **Security**: File system permissions (no API keys, no SSL)
- **Performance**: Direct IPC, zero HTTP overhead
- **Simplicity**: ~50 lines vs 200+ lines of FastAPI/auth/SSL
- **Appropriate**: Right tool for local process communication
- **Precedent**: MCP server already uses socket transport

## Overview (Revised)

Add Unix domain socket listener to TeleClaude daemon to enable lightweight IPC from Claude Code hooks. Currently, hooks bootstrap the entire TeleClaude stack (database, adapters, event loops) causing Claude Code to hang. This PRD establishes a thin client/server architecture where hooks write JSON to socket and close connection immediately.

## Problem Statement

The current `.claude/hooks/notification.py` implementation has critical issues:

1. **Hangs Claude Code**: The hook calls `bootstrap_teleclaude()` which starts the Telegram adapter event loop, blocking indefinitely and making Claude Code unresponsive
2. **Extremely Slow**: Bootstrapping the full daemon takes 5+ seconds per hook invocation
3. **Resource Wasteful**: Creates duplicate connections to Telegram, Redis, and database for each notification
4. **Poor Architecture**: Violates client/server separation - hooks should be thin clients, not daemon replicas

The TeleClaude daemon is already running 24/7 with all adapters connected. Hooks should simply make HTTP requests to leverage the existing infrastructure.

## Goals

- **Primary**: Enable Claude Code hooks to send notifications via Unix socket without hanging
- **Primary**: Reduce hook execution time from 5+ seconds to <100ms
- **Primary**: Maintain notification flag coordination (set/clear `notification_sent` in ux_state)
- **Secondary**: Establish pattern for future hook-to-daemon communication

## Non-Goals

- REST API endpoints (wrong tool for local IPC)
- SSL/TLS encryption (not needed for Unix sockets)
- API key authentication (file permissions handle security)
- Network accessibility (socket is local-only by design)

## Technical Approach

### High-Level Design (Revised)

```
┌─────────────────┐     JSON → Socket          ┌──────────────────────┐
│ Claude Code     │────────────────────────────>│ TeleClaude Daemon    │
│ notification.py │  /tmp/teleclaude-hooks.sock│ (always running)     │
└─────────────────┘                             │                      │
                                                 │ - Socket Listener    │
                                                 │ - AdapterClient      │
                   Immediate Close               │ - TelegramAdapter    │
┌─────────────────┐                             │ - RedisAdapter       │
│ Hook completes  │                             │ - Database           │
│ in <100ms       │                             └──────────────────────┘
└─────────────────┘                                       │ Broadcast
                                                          ▼
                                              ┌─────────────────────┐
                                              │ Telegram Topics     │
                                              │ (all UI adapters)   │
                                              └─────────────────────┘
```

### Key Components (Revised)

1. **Unix Socket Server** (`teleclaude/daemon.py`):
   - Async socket listener on `/tmp/teleclaude-hooks.sock`
   - Handles JSON protocol: `{"action": "notify"|"clear_flag", "session_id": "...", "message": "..."}`
   - Non-blocking: accept → parse → respond → close

2. **Lightweight Hook Scripts** (`.claude/hooks/`):
   - `notification.py` - Simple socket write with Python's `socket` library (no dependencies)
   - `stop.py` - Socket write to clear flag

3. **Notification Flag Coordination**:
   - Socket handler sets `notification_sent=True` when hook notifies
   - Polling coordinator checks flag before sending idle notifications
   - stop.py sends `clear_flag` action to re-enable idle notifications

### Data Model Changes

No schema changes required. Uses existing `ux_state` JSON blob:

```python
# SessionUXState dataclass (already exists)
@dataclass
class SessionUXState:
    notification_sent: bool = False  # Set by notification endpoint
    claude_session_file: Optional[str] = None  # From hook metadata
    # ... other fields
```

### Socket Protocol (Revised)

#### Message Format

All messages are JSON-encoded strings followed by newline (`\n`):

**Notify Action:**
```json
{
  "action": "notify",
  "session_id": "abc123",
  "message": "Your agent needs your input",
  "claude_session_file": "/path/to/session.jsonl"
}
```

**Clear Flag Action:**
```json
{
  "action": "clear_flag",
  "session_id": "abc123"
}
```

#### Response Format

**Success:**
```json
{"status": "ok", "message_id": "msg-789"}
```

**Error:**
```json
{"status": "error", "error": "Session not found"}
```

#### Hook Implementation Example

```python
import socket
import json

def send_notification(session_id: str, message: str):
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        sock.connect("/tmp/teleclaude-hooks.sock")
        request = {"action": "notify", "session_id": session_id, "message": message}
        sock.sendall((json.dumps(request) + "\n").encode())
        response = sock.recv(1024).decode()
        return json.loads(response)
    finally:
        sock.close()
```

### Configuration Changes (Revised)

**No new environment variables required** (removed API_KEY)

**New configuration:**

```yaml
# config.yml
hooks:
  socket_path: /tmp/teleclaude-hooks.sock  # Unix domain socket for hook IPC
  socket_permissions: 0600  # Owner read/write only
```

**Removed configuration** (no longer needed):
- `API_KEY` environment variable
- `rest_api.ssl` section
- SSL certificate files

### Security (Revised)

**File system permissions handle authentication:**

1. Socket file owned by daemon user (typically current user)
2. Permissions set to `0600` (owner read/write only)
3. Only processes running as same user can connect
4. No network exposure (not even localhost)

**Example socket permissions:**
```bash
ls -l /tmp/teleclaude-hooks.sock
# Output: srw------- 1 user user 0 Jan 11 18:00 /tmp/teleclaude-hooks.sock
```

**Security advantages over REST API + SSL:**
- No certificate management
- No API key storage
- No network attack surface
- OS enforces access control
- Standard Unix IPC security model

## Implementation Details

### Files to Create (Revised)

- `prds/rest-api-notification-endpoint.md` - This PRD (updated with socket approach) ✅
- `teleclaude/lib/hook_socket.py` - Socket server handler (NEW)
- `tests/unit/test_hook_socket.py` - Unit tests for socket handler (NEW)

### Files to Delete (No Longer Needed)

- ~~`teleclaude/lib/auth.py`~~ - API key authentication (not needed for sockets) 🗑️
- ~~`tests/unit/test_auth.py`~~ - Auth tests (not needed) 🗑️
- ~~`scripts/generate-ssl-cert.sh`~~ - SSL certificate generation (not needed) 🗑️
- ~~`certs/server.crt`~~ - SSL certificate (not needed) 🗑️
- ~~`certs/server.key`~~ - SSL private key (not needed) 🗑️

### Files to Modify

1. **`teleclaude/rest_api.py`**: ✅
   - Import `verify_apikey` from `teleclaude.lib.auth` ✅
   - Add authentication dependency to new endpoints: `Depends(verify_apikey)` ✅
   - Add `POST /api/v1/notifications` endpoint handler ✅
   - Add `DELETE /api/v1/sessions/{session_id}/notification_flag` endpoint handler ✅
   - Import AdapterClient reference from daemon ✅
   - Handle session creation if session doesn't exist ✅
   - Set notification_sent flag via db.set_notification_flag() ✅

2. **`teleclaude/daemon.py`**: ✅
   - Pass `adapter_client` reference to REST API initialization ✅
   - Ensure REST API has access to AdapterClient for message broadcasting ✅
   - Configure uvicorn with SSL: pass ssl_keyfile and ssl_certfile to uvicorn.Config ✅
   - Read SSL paths from config.yml ✅

3. **`config.yml.sample`**: ✅
   - Add ssl configuration section under rest_api ✅
   - Document cert_file and key_file paths ✅

4. **`Makefile`**: ✅
   - Add `make certs` command for certificate generation ✅
   - Document in help output ✅

5. **`README.md`**: ✅
   - Document SSL certificate setup process ✅
   - Add `make certs` usage example ✅

4. **`.claude/hooks/notification.py`**:
   - Remove `bootstrap_teleclaude()` function entirely
   - Remove all TeleClaude imports (config, db, adapter_client)
   - Add `requests` library to dependencies
   - Read API_KEY from environment variable
   - Implement HTTPS POST to https://localhost:6666 with X-API-KEY header
   - Set verify=False or verify='certs/server.crt' for self-signed cert
   - Add timeout (5 seconds) and error handling
   - Return immediately after HTTP response

5. **`.claude/hooks/stop.py`**:
   - Add HTTPS DELETE call to clear notification flag with X-API-KEY header
   - Add `requests` library to dependencies
   - Read API_KEY from environment variable
   - Set verify=False or verify='certs/server.crt' for self-signed cert
   - Keep existing TTS/summarization functionality

6. **`.env.sample`**:
   - Add API_KEY example with documentation

7. **`.gitignore`**:
   - Add `certs/*.key` to ignore private keys
   - Add `certs/*.crt` to ignore (regenerated per machine)

8. **`pyproject.toml`**:
   - Already fixed setuptools package discovery

### Dependencies

**New Hook Dependencies:**
```toml
# .claude/hooks/notification.py
# /// script
# dependencies = [
#     "requests",  # NEW: For HTTP calls
# ]
# ///
```

**Existing Dependencies** (no changes):
- FastAPI (already used for REST API)
- uvicorn (already used for REST API)
- aiosqlite (already used for database)

### Session Creation Logic

**Important**: If the hook provides a `claude_session_file` but no session exists yet:

1. Check if Claude Code session is active (session file exists and is being written to)
2. Create a new TeleClaude session:
   - Generate session_id (UUID)
   - Create tmux session with project directory
   - Store `claude_session_file` in ux_state
   - Create Telegram topic via AdapterClient
3. Send notification to newly created session

This enables "just-in-time" session creation when Claude Code first needs to notify.

## Testing Strategy

### Unit Tests

**`tests/unit/test_rest_api_notifications.py`:**

1. `test_post_notification_success` - Valid session, message sent
2. `test_post_notification_creates_session` - Session created if doesn't exist
3. `test_post_notification_session_not_found` - Returns 404 when session doesn't exist and can't create
4. `test_post_notification_sets_flag` - Verifies notification_sent=True in ux_state
5. `test_delete_notification_flag_success` - Flag cleared successfully
6. `test_delete_notification_flag_session_not_found` - Returns 404 for missing session
7. `test_notification_endpoint_broadcasts_to_adapters` - Message sent via AdapterClient
8. `test_notification_endpoint_error_handling` - Handles AdapterClient failures gracefully

### Integration Tests

**`tests/integration/test_notification_endpoint_integration.py`:**

1. Start daemon with REST API enabled
2. Make HTTP POST to /api/v1/notifications
3. Verify message appears in mock Telegram adapter
4. Verify notification_sent flag is set in database
5. Verify polling coordinator skips idle notification when flag is set
6. Make HTTP DELETE to clear flag
7. Verify flag is cleared and idle notifications resume

### Manual Testing

**Test Hook Without Claude Code:**

```bash
# Terminal 1: Ensure daemon is running
make status

# Terminal 2: Test notification endpoint directly
curl -X POST http://localhost:6666/api/v1/notifications \
  -H "Content-Type: application/json" \
  -d '{"session_id": "test-123", "message": "Test notification"}'

# Expected: Notification appears in Telegram topic
# Expected: notification_sent flag set in database

# Terminal 2: Clear flag
curl -X DELETE http://localhost:6666/api/v1/sessions/test-123/notification_flag

# Expected: Flag cleared in database
```

**Test With Hook Script:**

```bash
# Simulate Claude Code calling the hook
echo '{"session_id": "abc123", "message": "Claude is ready"}' | \
  uv run .claude/hooks/notification.py --notify

# Expected: Hook completes in <100ms
# Expected: Notification appears in Telegram
# Expected: No hanging or blocking
```

## Rollout Plan

### Phase 1: Development (This PRD)

1. Implement REST API endpoints in `rest_api.py`
2. Wire AdapterClient into REST API initialization
3. Write and pass unit tests
4. Update hook scripts to use HTTP

### Phase 2: Testing

1. Manual testing with curl commands
2. Integration test with real daemon + hooks
3. Test session creation flow
4. Test notification flag coordination

### Phase 3: Deployment

1. Update pyproject.toml (already done)
2. Restart daemon to load new REST API endpoints
3. Test hooks in live Claude Code session
4. Monitor logs for any issues

### Rollback Strategy

If REST API approach fails:
1. Revert `.claude/hooks/*.py` to previous versions
2. Daemon continues running (no changes to core functionality)
3. Hooks fall back to global TTS-only hooks (always available as backup)

## Success Criteria

- [x] pyproject.toml fixed for setuptools discovery
- [ ] `POST /api/v1/notifications` endpoint implemented and tested
- [ ] `DELETE /api/v1/sessions/{session_id}/notification_flag` endpoint implemented
- [ ] Hook execution time reduced from 5+ seconds to <100ms
- [ ] Hooks complete without hanging Claude Code
- [ ] Notification flag coordination working (set on notify, cleared on activity)
- [ ] Messages appear in Telegram topics when hooks fire
- [ ] Unit tests pass for all new endpoints
- [ ] Integration test passes for full notification flow
- [ ] Manual testing confirms Claude Code remains responsive

## Open Questions

1. **Session auto-creation**: Should notification endpoint auto-create sessions if they don't exist, or require explicit session creation first?
   - **Decision**: Auto-create sessions when claude_session_file is provided (enables "just-in-time" workflow)

2. **Error handling for offline daemon**: What should hooks do if daemon is not running?
   - **Decision**: Hook should log error and exit gracefully (fail silently, don't block Claude Code)

3. **Rate limiting**: Should we add rate limiting to prevent hook spam?
   - **Decision**: Not needed for MVP (single-user, local-only, hook frequency is low)

4. **Message templates**: Should the endpoint support message templates or just pass through?
   - **Decision**: Pass through raw message (hook can do templating if needed)

## References

- Architecture docs: `docs/architecture.md`
- Project guidelines: `CLAUDE.md`
- REST API implementation: `teleclaude/rest_api.py`
- Polling coordinator: `teleclaude/core/polling_coordinator.py` (lines 209-216, notification flag check)
- Database helpers: `teleclaude/core/db.py` (set_notification_flag, clear_notification_flag)
- Related roadmap item: `todos/roadmap.md` #2

---

## 🔄 REVISED IMPLEMENTATION PLAN (Unix Socket Approach)

### Phase 1: Socket Server Implementation

**Create `teleclaude/lib/hook_socket.py`:**
```python
"""Unix domain socket server for Claude Code hook communication."""

import asyncio
import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

class HookSocketServer:
    """Async Unix socket server for hook IPC."""
    
    def __init__(self, socket_path: str, adapter_client, permissions: int = 0o600):
        self.socket_path = socket_path
        self.adapter_client = adapter_client
        self.permissions = permissions
        self.server = None
        
    async def start(self):
        """Start socket server."""
        # Remove old socket file if exists
        if os.path.exists(self.socket_path):
            os.unlink(self.socket_path)
            
        self.server = await asyncio.start_unix_server(
            self.handle_connection, 
            path=self.socket_path
        )
        
        # Set restrictive permissions
        os.chmod(self.socket_path, self.permissions)
        logger.info("Hook socket server listening on %s", self.socket_path)
        
    async def stop(self):
        """Stop socket server."""
        if self.server:
            self.server.close()
            await self.server.wait_closed()
            
        if os.path.exists(self.socket_path):
            os.unlink(self.socket_path)
            
    async def handle_connection(self, reader, writer):
        """Handle incoming socket connection."""
        try:
            # Read JSON request (newline-delimited)
            data = await reader.readline()
            request = json.loads(data.decode())
            
            # Route action
            if request["action"] == "notify":
                response = await self._handle_notify(request)
            elif request["action"] == "clear_flag":
                response = await self._handle_clear_flag(request)
            else:
                response = {"status": "error", "error": "Unknown action"}
                
            # Send response
            writer.write((json.dumps(response) + "\n").encode())
            await writer.drain()
            
        except Exception as e:
            logger.error("Socket handler error: %s", e)
            response = {"status": "error", "error": str(e)}
            writer.write((json.dumps(response) + "\n").encode())
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()
            
    async def _handle_notify(self, request):
        """Handle notify action."""
        from teleclaude.core.db import db  # Import here (module level)
        
        session_id = request["session_id"]
        message = request["message"]
        claude_session_file = request.get("claude_session_file")
        
        # Check session exists
        session = await db.get_session(session_id)
        if not session:
            return {"status": "error", "error": "Session not found"}
            
        # Send notification via AdapterClient
        message_id = await self.adapter_client.send_message(session_id, message)
        
        # Set notification flag
        await db.set_notification_flag(session_id, True)
        
        # Store claude_session_file if provided
        if claude_session_file:
            await db.update_ux_state(
                session_id,
                claude_session_file=claude_session_file
            )
            
        return {"status": "ok", "message_id": message_id}
        
    async def _handle_clear_flag(self, request):
        """Handle clear_flag action."""
        from teleclaude.core.db import db
        
        session_id = request["session_id"]
        await db.clear_notification_flag(session_id)
        return {"status": "ok"}
```

### Phase 2: Daemon Integration

**Modify `teleclaude/daemon.py`:**
```python
# In __init__:
from teleclaude.lib.hook_socket import HookSocketServer

self.hook_socket = HookSocketServer(
    socket_path="/tmp/teleclaude-hooks.sock",
    adapter_client=self.client,
    permissions=0o600
)

# In start():
# Start hook socket server
await self.hook_socket.start()
logger.info("Hook socket server started")

# In stop():
# Stop hook socket server
if hasattr(self, "hook_socket"):
    await self.hook_socket.stop()
    logger.info("Hook socket server stopped")
```

### Phase 3: Hook Rewrite

**`.claude/hooks/notification.py`:**
```python
#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.11"
# dependencies = []  # NO external dependencies - stdlib only
# ///

import json
import socket
import sys

SOCKET_PATH = "/tmp/teleclaude-hooks.sock"

def send_notification(session_id: str, message: str, claude_session_file: str = None):
    """Send notification via Unix socket."""
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        sock.connect(SOCKET_PATH)
        request = {
            "action": "notify",
            "session_id": session_id,
            "message": message
        }
        if claude_session_file:
            request["claude_session_file"] = claude_session_file
            
        sock.sendall((json.dumps(request) + "\n").encode())
        response = json.loads(sock.recv(1024).decode())
        
        if response["status"] != "ok":
            print(f"Warning: {response.get('error')}", file=sys.stderr)
            
    except FileNotFoundError:
        print("Warning: TeleClaude daemon not running", file=sys.stderr)
    except Exception as e:
        print(f"Warning: Failed to send notification: {e}", file=sys.stderr)
    finally:
        sock.close()

# Main hook logic here...
```

### Phase 4: Cleanup

**Delete obsolete files:**
- `teleclaude/lib/auth.py`
- `tests/unit/test_auth.py`
- `scripts/generate-ssl-cert.sh`
- `certs/` directory

**Revert changes in:**
- `teleclaude/rest_api.py` - Remove notification endpoints
- `teleclaude/daemon.py` - Remove SSL config, adapter_client wiring to rest_api
- `config.yml.sample` - Remove rest_api.ssl section
- `Makefile` - Remove make certs
- `README.md` - Remove SSL section
- `.env.sample` - Remove API_KEY
- `.gitignore` - Remove certs entries

### Benefits Summary

**Complexity reduction:**
- ~200 lines of REST/SSL/auth code → ~100 lines of socket server
- 3 files deleted (auth.py, test_auth.py, generate-ssl-cert.sh)
- No external dependencies in hooks (stdlib only)
- No certificate management
- No API key storage

**Performance:**
- REST API: ~50-100ms (HTTP parsing, SSL handshake)
- Unix socket: ~5-10ms (direct IPC)

**Security:**
- REST API: API keys + SSL certificates to manage
- Unix socket: OS file permissions (standard Unix security)

**Maintainability:**
- REST API: Keep uvicorn, FastAPI, SSL certs updated
- Unix socket: Standard Python asyncio (no extra dependencies)

---

## 🔄 EVEN SIMPLER: Use MCP Server for Hooks

**Realization:** We already have an MCP server running for Claude Code integration!

**Current architecture:**
- Claude Code → MCP stdio → TeleClaude daemon
- Hooks bootstrap entire daemon (wrong)

**Correct architecture:**
- Claude Code → MCP stdio → TeleClaude daemon
- Hooks → Call MCP client → TeleClaude daemon (via stdio or direct Python import)

**Options:**

### Option A: Hooks Call MCP Tools Directly (Simplest)
Since hooks run in same process as Claude Code, they can import and call MCP client methods directly:

```python
# .claude/hooks/notification.py
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

async def send_notification(session_id, message):
    server_params = StdioServerParameters(
        command="teleclaude-mcp",  # Points to daemon's MCP server
        args=[],
    )
    
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            
            # Call existing MCP tool
            result = await session.call_tool("send_notification", {
                "session_id": session_id,
                "message": message
            })
            return result
```

### Option B: Add Hook-Specific Utility (Even Simpler)
Since hooks run on same machine as daemon, just import the daemon directly:

```python
# .claude/hooks/notification.py - SIMPLEST
import asyncio
from teleclaude.core.db import db
from teleclaude.daemon import TeleClaudeDaemon

async def send_notification(session_id, message):
    # Get running daemon instance (via PID file or create temp instance)
    # Actually NO - this still bootstraps everything!
    pass
```

### Option C: Lightweight MCP Client in Hook
Hooks send request to MCP server's stdio transport:

```python
# .claude/hooks/notification.py
import subprocess
import json

def send_notification(session_id, message):
    # Call teleclaude-mcp command (which daemon exposes)
    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "send_notification",
            "arguments": {"session_id": session_id, "message": message}
        }
    }
    
    proc = subprocess.Popen(
        ["teleclaude-mcp"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
    )
    
    proc.stdin.write((json.dumps(request) + "\n").encode())
    proc.stdin.flush()
    response = proc.stdout.readline()
    proc.wait()
    
    return json.loads(response)
```

**WAIT - Problem:** MCP server uses stdio, but daemon is already running. Can't have two stdio connections to same process.

**CORRECT ANSWER: We DO need a separate socket for hooks!**

MCP server is for Claude Code (one stdio connection). Hooks need their own IPC channel (Unix socket). 

**Final decision: Separate Unix socket for hooks is correct.**
- MCP server: stdio transport for Claude Code
- Hook socket: Unix socket for notification hooks
- Both lightweight, both async, both running in daemon


---

## ✅ FINAL ANSWER: Reuse MCP Socket (No New Socket Needed!)

**Question:** Do we need another socket server for hooks?
**Answer:** NO! We already have `/tmp/teleclaude.sock` from MCP server.

**Current state:**
- MCP server supports BOTH stdio and socket transports
- Claude Code uses stdio (subprocess spawning)
- Socket transport exists but unused: `/tmp/teleclaude.sock`

**Solution: Hooks use existing MCP socket!**

1. **Add MCP tool:** `send_hook_notification` (simple wrapper around existing notify logic)
2. **Hooks connect to MCP socket** and call the tool
3. **No new server needed** - reuse existing MCP infrastructure

### Implementation (Simplified)

**Step 1: Add MCP tool in `teleclaude/mcp_server.py`:**

```python
@self.server.call_tool()
async def send_hook_notification(
    session_id: str,
    message: str,
    claude_session_file: str | None = None
) -> list[TextContent]:
    """Send notification from Claude Code hook (internal use)."""
    
    # Same logic as endpoints would have
    session = await db.get_session(session_id)
    if not session:
        raise ValueError(f"Session {session_id} not found")
        
    message_id = await self.adapter_client.send_message(session_id, message)
    await db.set_notification_flag(session_id, True)
    
    if claude_session_file:
        await db.update_ux_state(session_id, claude_session_file=claude_session_file)
        
    return [TextContent(type="text", text=f"Notification sent: {message_id}")]
```

**Step 2: Hook uses MCP client:**

```python
# .claude/hooks/notification.py
import asyncio
import json
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

async def send_notification(session_id, message):
    # Connect to MCP socket (not stdio - daemon already running)
    # Use simple socket connection
    import socket
    
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.connect("/tmp/teleclaude.sock")
    
    # Send MCP tool call request
    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "send_hook_notification",
            "arguments": {"session_id": session_id, "message": message}
        }
    }
    
    sock.sendall((json.dumps(request) + "\n").encode())
    response = json.loads(sock.recv(4096).decode())
    sock.close()
    
    return response
```

### Benefits:
- **Zero new infrastructure** - reuse MCP server
- **Consistent protocol** - everything uses MCP
- **No duplicate logic** - hook tools are just wrappers
- **Already secured** - socket permissions already set (0o666 in code above)

### Files to modify:
1. `teleclaude/mcp_server.py` - Add `send_hook_notification` and `clear_hook_notification_flag` tools
2. `.claude/hooks/notification.py` - Use MCP socket client
3. `.claude/hooks/stop.py` - Use MCP socket client

### Files to delete:
- Everything from REST API approach (auth, SSL, certs, etc.)


---

## 🎯 FINAL ARCHITECTURE DECISION

### User Feedback Applied:

1. **Tool naming:** `teleclaude__send_notification` (not `send_hook_notification` - hook context irrelevant)
2. **Kill HTTPS server entirely:** YES - no need for FastAPI/uvicorn at all

### What Dies:

**Delete entire REST API infrastructure:**
- ❌ `teleclaude/rest_api.py` - ENTIRE FILE
- ❌ FastAPI dependency
- ❌ uvicorn server initialization in daemon.py
- ❌ All REST API config in config.yml
- ❌ Pydantic models
- ❌ All `/health`, `/api/v1/*` endpoints

**Delete SSL/auth infrastructure:**
- ❌ `teleclaude/lib/auth.py`
- ❌ `tests/unit/test_auth.py`
- ❌ `scripts/generate-ssl-cert.sh`
- ❌ `certs/` directory
- ❌ `make certs` command
- ❌ SSL documentation in README

### What Lives:

**MCP tools for everything:**
```python
# teleclaude/mcp_server.py

@self.server.call_tool()
async def teleclaude__send_notification(
    session_id: str,
    message: str,
    claude_session_file: str | None = None
) -> list[TextContent]:
    """Send notification to session (used by Claude Code hooks)."""
    session = await db.get_session(session_id)
    if not session:
        raise ValueError(f"Session {session_id} not found")
        
    message_id = await self.adapter_client.send_message(session_id, message)
    await db.set_notification_flag(session_id, True)
    
    if claude_session_file:
        await db.update_ux_state(session_id, claude_session_file=claude_session_file)
        
    return [TextContent(type="text", text=f"OK: {message_id}")]

@self.server.call_tool()
async def teleclaude__clear_notification_flag(
    session_id: str
) -> list[TextContent]:
    """Clear notification flag (used by stop hook)."""
    await db.clear_notification_flag(session_id)
    return [TextContent(type="text", text="OK")]

@self.server.call_tool()
async def teleclaude__get_session_output(
    session_id: str,
    lines: int | None = None,
    from_line: int = 0
) -> list[TextContent]:
    """Get terminal output for session (replaces REST API endpoint)."""
    # Move logic from rest_api.py here
    pass
```

### Hook Implementation (Final):

```python
# .claude/hooks/notification.py
import socket
import json

MCP_SOCKET = "/tmp/teleclaude.sock"

def send_notification(session_id: str, message: str):
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        sock.connect(MCP_SOCKET)
        
        request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "teleclaude__send_notification",
                "arguments": {
                    "session_id": session_id,
                    "message": message
                }
            }
        }
        
        sock.sendall((json.dumps(request) + "\n").encode())
        response = json.loads(sock.recv(4096).decode())
        
        if "error" in response:
            print(f"Warning: {response['error']}", file=sys.stderr)
            
    except Exception as e:
        print(f"Warning: {e}", file=sys.stderr)
    finally:
        sock.close()
```

### Simplification Metrics:

**Before (REST API approach):**
- 3 new files (auth.py, generate-ssl-cert.sh, test_auth.py)
- 200+ lines of endpoint code
- 100+ lines of SSL configuration
- 50+ lines of authentication middleware
- External dependencies: none (FastAPI/uvicorn already present)
- Configuration: API_KEY, SSL certs, rest_api.ssl section

**After (MCP socket approach):**
- 0 new files (use existing mcp_server.py)
- ~40 lines added (2 MCP tools)
- 0 configuration changes (socket already exists)
- 0 external dependencies
- 0 security infrastructure (Unix permissions)

**Net change: -350 lines, -3 files, simpler architecture**


---

## ✅ `/health` Endpoint Also Not Needed

**Current use:** `bin/daemon-control.sh` checks `http://localhost:6666/health` for `make status`

**Better approach:** Process check (already done) is sufficient!

```bash
# Current daemon-control.sh already does this:
if kill -0 $PID 2>/dev/null; then
    log_info "Daemon process: RUNNING (PID: $PID)"
fi
```

**Process check = health check:**
- If PID exists and responds → daemon is alive
- If daemon crashes → PID is stale, `kill -0` fails
- No HTTP endpoint needed for this

**Optional enhancement (if paranoid):**
```bash
# Check MCP socket exists and is accepting connections
if [ -S /tmp/teleclaude.sock ]; then
    log_info "Daemon health: HEALTHY (MCP socket active)"
else
    log_warn "Daemon health: MCP socket missing"
fi
```

**Decision:** Remove `/health` endpoint, simplify daemon-control.sh to rely on PID check only.

### Updated Deletion List:

**Delete ENTIRE FastAPI/uvicorn infrastructure:**
- ❌ `teleclaude/rest_api.py` - ENTIRE FILE (not just endpoints, WHOLE FILE)
- ❌ Remove FastAPI from dependencies (check if used elsewhere first)
- ❌ Remove uvicorn from dependencies
- ❌ Remove Pydantic BaseModel imports
- ❌ Remove uvicorn initialization from daemon.py (~30 lines)
- ❌ Remove `rest_api` config section from config.yml.sample
- ❌ Simplify daemon-control.sh (remove HTTP health check)

**Result:** Daemon becomes pure Python asyncio server (no web framework).

