# Implementation: Hook Notifications via MCP Socket

> **Context**: Claude Code hooks currently bootstrap entire TeleClaude daemon (causing hangs). Solution: Use existing MCP socket for lightweight IPC.

## Goal

Enable `.claude/hooks/notification.py` and `stop.py` to send notifications to TeleClaude daemon without blocking Claude Code.

**Current problem:**
- Hooks call `bootstrap_teleclaude()` → starts event loops → hangs forever
- Execution time: 5+ seconds (unacceptable)

**Target:**
- Hooks send JSON to MCP socket → get response → exit
- Execution time: <100ms

## Architecture

**No new infrastructure needed!** Reuse existing MCP server:
- MCP server already runs on `/tmp/teleclaude.sock` (socket transport)
- Add 2 new MCP tools for hook operations
- Hooks become thin MCP clients (stdlib only, no dependencies)

```
┌─────────────────┐
│ Claude Code     │
│ notification.py │
└────────┬────────┘
         │ JSON via socket
         ▼
┌─────────────────────────────────┐
│ TeleClaude Daemon (running)     │
│                                 │
│  MCP Server (/tmp/teleclaude.   │
│  sock)                          │
│   ├─ teleclaude__send_          │
│   │  notification (NEW)         │
│   └─ teleclaude__clear_         │
│      notification_flag (NEW)    │
│                                 │
│  AdapterClient → Telegram       │
└─────────────────────────────────┘
```

## Implementation Tasks

### Phase 1: Add MCP Tools (15 min)

**File:** `teleclaude/mcp_server.py`

Add two new tools after existing tools (around line 200):

```python
@self.server.call_tool()
async def teleclaude__send_notification(
    session_id: str,
    message: str,
    claude_session_file: str | None = None
) -> list[TextContent]:
    """Send notification to session (called by Claude Code hooks).

    Args:
        session_id: Session UUID
        message: Notification message to send
        claude_session_file: Optional path to Claude session file

    Returns:
        Success message with message_id
    """
    from teleclaude.core.db import db

    # Verify session exists
    session = await db.get_session(session_id)
    if not session:
        raise ValueError(f"Session {session_id} not found")

    # Send notification via AdapterClient
    message_id = await self.adapter_client.send_message(session_id, message)

    # Set notification_sent flag (prevents idle notifications)
    await db.set_notification_flag(session_id, True)

    # Store claude_session_file if provided
    if claude_session_file:
        await db.update_ux_state(session_id, claude_session_file=claude_session_file)

    return [TextContent(type="text", text=f"OK: {message_id}")]


@self.server.call_tool()
async def teleclaude__clear_notification_flag(
    session_id: str
) -> list[TextContent]:
    """Clear notification flag (called by stop hook).

    Args:
        session_id: Session UUID

    Returns:
        Success message
    """
    from teleclaude.core.db import db

    await db.clear_notification_flag(session_id)
    return [TextContent(type="text", text="OK")]
```

**Location:** Insert after existing tools (search for `@self.server.call_tool()` to find pattern)

### Phase 2: Rewrite Hooks (20 min)

**File:** `.claude/hooks/notification.py`

Replace entire `bootstrap_teleclaude()` section with simple socket client:

```python
#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.11"
# dependencies = []  # NO external dependencies - stdlib only
# ///

import json
import socket
import sys
from pathlib import Path

MCP_SOCKET = "/tmp/teleclaude.sock"


def send_notification(session_id: str, message: str, claude_session_file: str = None):
    """Send notification via MCP socket."""
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        sock.connect(MCP_SOCKET)

        # Build MCP tool call request
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

        if claude_session_file:
            request["params"]["arguments"]["claude_session_file"] = claude_session_file

        # Send request
        sock.sendall((json.dumps(request) + "\n").encode())

        # Read response
        response_data = sock.recv(4096).decode()
        response = json.loads(response_data)

        # Check for errors
        if "error" in response:
            print(f"Warning: {response['error']['message']}", file=sys.stderr)
            return False

        return True

    except FileNotFoundError:
        print(f"Warning: TeleClaude daemon not running (socket not found)", file=sys.stderr)
        return False
    except Exception as e:
        print(f"Warning: Failed to send notification: {e}", file=sys.stderr)
        return False
    finally:
        sock.close()


# Main hook logic (keep existing notification template selection, etc.)
if __name__ == "__main__":
    # ... existing argument parsing ...

    # Replace bootstrap_teleclaude() with:
    success = send_notification(
        session_id=session_id,
        message=notification_message,
        claude_session_file=claude_session_file
    )

    if not success:
        sys.exit(0)  # Don't block Claude Code even if notification fails
```

**File:** `.claude/hooks/stop.py`

Add similar socket client for clearing flag:

```python
def clear_notification_flag(session_id: str):
    """Clear notification flag via MCP socket."""
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        sock.connect(MCP_SOCKET)

        request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "teleclaude__clear_notification_flag",
                "arguments": {"session_id": session_id}
            }
        }

        sock.sendall((json.dumps(request) + "\n").encode())
        response = json.loads(sock.recv(4096).decode())

        if "error" in response:
            print(f"Warning: {response['error']['message']}", file=sys.stderr)

    except Exception as e:
        print(f"Warning: Failed to clear flag: {e}", file=sys.stderr)
    finally:
        sock.close()


# In main hook logic (after TTS/summarization):
clear_notification_flag(session_id)
```

### Phase 3: Delete Obsolete Code (10 min)

**Remove these files entirely:**
```bash
rm teleclaude/lib/auth.py
rm tests/unit/test_auth.py
rm scripts/generate-ssl-cert.sh
rm -rf certs/
```

**Remove from `teleclaude/rest_api.py`:**
- Delete entire notification endpoints section (lines 147-253)
- Remove auth import: `from teleclaude.lib.auth import verify_apikey`
- Remove Annotated, Depends imports if unused elsewhere
- Remove NotificationRequest model

**Remove from `teleclaude/daemon.py`:**
- Delete SSL configuration code (lines 688-718, the uvicorn SSL setup)
- Revert adapter_client wiring to rest_api (move rest_api init before client init)

**Remove from `config.yml.sample`:**
```yaml
# Delete this entire section:
rest_api:
  ssl:
    enabled: true
    cert_file: ${WORKING_DIR}/certs/server.crt
    key_file: ${WORKING_DIR}/certs/server.key
```

**Remove from `Makefile`:**
```makefile
# Delete these lines:
certs:
	@echo "Generating SSL certificates for REST API..."
	...
```

**Remove from `README.md`:**
- Delete "SSL Certificates (Optional)" section

**Remove from `.env.sample`:**
```bash
# Delete this line:
API_KEY=your-secret-key-here
```

**Remove from `.gitignore`:**
```
# Delete these lines:
# SSL Certificates (per-machine generation)
certs/*.key
certs/*.crt
```

### Phase 4: Test (15 min)

**Manual test:**

```bash
# 1. Ensure daemon is running
make status

# 2. Check MCP socket exists
ls -l /tmp/teleclaude.sock
# Should show: srwxrwxrwx ... /tmp/teleclaude.sock

# 3. Create a test session in Telegram
/new_session

# 4. Test notification hook manually
echo '{"session_id": "YOUR_SESSION_ID", "message": "Test notification"}' | \
  python3 -c "
import json, socket, sys
data = json.load(sys.stdin)
sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
sock.connect('/tmp/teleclaude.sock')
req = {
    'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
    'params': {
        'name': 'teleclaude__send_notification',
        'arguments': data
    }
}
sock.sendall((json.dumps(req) + '\n').encode())
print(sock.recv(4096).decode())
sock.close()
"

# 5. Check notification appears in Telegram topic

# 6. Test with actual Claude Code hook
# Trigger notification event in Claude Code → verify completes in <100ms
```

**Expected results:**
- ✅ Hook completes in <100ms (not 5+ seconds)
- ✅ Notification appears in Telegram topic
- ✅ Claude Code remains responsive (no hanging)
- ✅ notification_sent flag is set in database
- ✅ Stop hook clears flag successfully

## Success Criteria

- [ ] MCP tools added to mcp_server.py
- [ ] Hooks rewritten to use socket client
- [ ] Obsolete SSL/auth code deleted
- [ ] Manual test passes
- [ ] Hook execution time <100ms
- [ ] Claude Code doesn't hang

## Questions/Issues?

- **Socket permissions:** MCP socket has 0o666 permissions (world-writable). This is intentional for multi-user scenarios. If stricter permissions needed, modify in `mcp_server.py` line ~325.

- **Error handling:** Hooks fail gracefully if daemon offline (don't block Claude Code). This is by design.

- **MCP protocol:** If unfamiliar with MCP JSON-RPC, see: https://modelcontextprotocol.io/docs/concepts/architecture

## Estimated Time

- **Total:** 1 hour
- **Phase 1:** 15 min (add MCP tools)
- **Phase 2:** 20 min (rewrite hooks)
- **Phase 3:** 10 min (delete obsolete code)
- **Phase 4:** 15 min (test)
