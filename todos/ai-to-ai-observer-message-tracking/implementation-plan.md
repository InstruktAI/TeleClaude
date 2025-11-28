# Implementation Plan: Unified Adapter Architecture

> **Created**: 2025-11-28
> **Status**: 📋 Planning
> **Goal**: Step-by-step plan to remove AI session special cases and unify adapter pattern

## Overview

This plan implements the architecture changes defined in `requirements.md` through 4 phases:

1. **Phase 1**: Add session data access (non-breaking, additive only)
2. **Phase 2**: Refactor Redis adapter (remove streaming, use request/response)
3. **Phase 3**: Simplify polling coordinator (remove AI session branching)
4. **Phase 4**: Cleanup and documentation

Each phase is testable independently and can be deployed incrementally.

---

## Phase 1: Add Session Data Access

**Goal**: Add `get_session_data()` capability to BaseAdapter without breaking existing functionality.

**Status**: ⏳ Not started

### Task Group 1.1: Implement BaseAdapter.get_session_data()

**Files**:
- `teleclaude/adapters/base_adapter.py`

**Implementation**:

```python
# Add to BaseAdapter class
async def get_session_data(
    self,
    session_id: str,
    since_timestamp: Optional[str] = None,
) -> dict[str, object]:
    """Read session data from Claude Code session file.

    This is a shared capability for ALL adapters to serve session data
    from the standard claude_session_file location.

    Args:
        session_id: Session identifier
        since_timestamp: Optional ISO 8601 UTC timestamp to filter messages since

    Returns:
        Dict containing:
        - "status": "success" or "error"
        - "messages": List of messages/outputs since timestamp
        - "session_id": Session identifier
        - "error": Error message if status is "error"

    Raises:
        FileNotFoundError: If session file doesn't exist
    """
    from pathlib import Path
    from datetime import datetime

    # Get session file path
    session_file = Path("storage") / session_id / "claude_session_file"

    if not session_file.exists():
        return {
            "status": "error",
            "error": f"Session file not found for session {session_id[:8]}",
            "session_id": session_id,
        }

    # Read session file content
    try:
        content = session_file.read_text()
    except Exception as e:
        logger.error("Failed to read session file for %s: %s", session_id[:8], e)
        return {
            "status": "error",
            "error": f"Failed to read session file: {str(e)}",
            "session_id": session_id,
        }

    # If no timestamp filter, return all content
    if not since_timestamp:
        return {
            "status": "success",
            "messages": content,
            "session_id": session_id,
        }

    # Parse timestamp and filter content
    # Claude session file format: Markdown with timestamped entries
    # Format: "## [HH:MM:SS] User/Assistant\n content..."
    try:
        filter_time = datetime.fromisoformat(since_timestamp)
        # TODO: Implement timestamp filtering logic
        # For now, return all content (will implement proper parsing)
        return {
            "status": "success",
            "messages": content,
            "session_id": session_id,
            "note": "Timestamp filtering not yet implemented",
        }
    except ValueError:
        return {
            "status": "error",
            "error": f"Invalid timestamp format: {since_timestamp}",
            "session_id": session_id,
        }
```

**Testing**:
- Add unit test: `tests/unit/adapters/test_base_adapter.py::test_get_session_data`
- Test with existing session file
- Test with missing session file
- Test with invalid timestamp

**Acceptance Criteria**:
- [ ] Method implemented in BaseAdapter
- [ ] Returns session file content successfully
- [ ] Handles missing files gracefully
- [ ] Unit tests pass

---

### Task Group 1.2: Add /session_data Command Handler

**Files**:
- `teleclaude/adapters/base_adapter.py`

**Implementation**:

Add to `COMMANDS` list in BaseAdapter:
```python
COMMANDS = [
    "list_sessions",
    "session_data",  # New command - all adapters support this
]
```

Add handler method:
```python
async def _handle_session_data(
    self,
    args: str,
    session_id: str,
    metadata: Optional[dict[str, object]] = None,
) -> Optional[str]:
    """Handle /session_data command.

    Reads claude_session_file and returns content, optionally filtered by timestamp.

    Args:
        args: Timestamp in ISO 8601 UTC format (optional)
        session_id: Session identifier (unused - reads from request)
        metadata: Command metadata with "session_id" to read

    Returns:
        JSON response with session data
    """
    import json

    # Extract target session_id from metadata (not the command's session_id)
    target_session_id = metadata.get("session_id") if metadata else None
    if not target_session_id:
        return json.dumps({
            "status": "error",
            "error": "session_id not provided in metadata",
        })

    # Parse timestamp from args
    since_timestamp = args.strip() if args else None

    # Get session data
    result = await self.get_session_data(target_session_id, since_timestamp)

    return json.dumps(result)
```

**Testing**:
- Add integration test: `tests/integration/test_session_data_command.py`
- Test command without timestamp
- Test command with valid timestamp
- Test command with invalid session_id

**Acceptance Criteria**:
- [ ] Command handler implemented
- [ ] Returns proper JSON response
- [ ] Handles missing session gracefully
- [ ] Integration tests pass

---

### Task Group 1.3: Add teleclaude__get_session_data MCP Tool

**Files**:
- `teleclaude/mcp_server.py`

**Implementation**:

Add new tool definition (keep old `teleclaude__get_session_status` for now):
```python
Tool(
    name="teleclaude__get_session_data",
    title="TeleClaude: Get Session Data",
    description=(
        "Retrieve session data from a remote computer's Claude Code session. "
        "Reads from the claude_session_file which contains complete session history. "
        "Optionally filter by timestamp to get only recent messages. "
        "**Use this to check on delegated work** after teleclaude__send_message. "
        "**Replaces**: teleclaude__get_session_status (deprecated)"
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "computer": {
                "type": "string",
                "description": "Target computer name where session is running",
            },
            "session_id": {
                "type": "string",
                "description": "Session ID to retrieve data for",
            },
            "since_timestamp": {
                "type": "string",
                "description": (
                    "Optional ISO 8601 UTC timestamp. "
                    "Returns only messages since this time. "
                    "Example: '2025-11-28T10:30:00Z'"
                ),
            },
        },
        "required": ["computer", "session_id"],
    },
),
```

Implement tool handler:
```python
async def teleclaude__get_session_data(
    self,
    computer: str,
    session_id: str,
    since_timestamp: Optional[str] = None,
) -> dict[str, object]:
    """Get session data from remote computer.

    Pulls accumulated session data from claude_session_file on remote computer.

    Args:
        computer: Target computer name
        session_id: Session ID on remote computer
        since_timestamp: Optional ISO 8601 UTC timestamp

    Returns:
        Dict with session data, status, and messages
    """
    import json

    # Generate unique request ID
    request_id = f"{session_id}-data-{int(time.time() * 1000)}"

    # Build command with optional timestamp
    command = f"/session_data {since_timestamp}" if since_timestamp else "/session_data"

    # Send request to remote computer
    await self.client.send_request(
        computer_name=computer,
        request_id=request_id,
        command=command,
        metadata={"session_id": session_id},
    )

    # Read response (remote reads claude_session_file)
    try:
        response = await self.client.read_response(request_id, timeout=5.0)
        return json.loads(response)
    except TimeoutError:
        return {
            "status": "error",
            "error": f"Timeout waiting for session data from {computer}",
        }
    except json.JSONDecodeError:
        return {
            "status": "error",
            "error": "Invalid JSON response from remote computer",
        }
```

**Testing**:
- Add e2e test: `tests/integration/test_mcp_get_session_data.py`
- Test retrieving session data from remote
- Test with timestamp filter
- Test timeout handling

**Acceptance Criteria**:
- [ ] MCP tool implemented
- [ ] Request/response pattern works
- [ ] Returns session data correctly
- [ ] E2E tests pass

---

## Phase 2: Refactor Redis Adapter

**Goal**: Remove Redis output streaming, use request/response pattern, eliminate local session creation in client mode.

**Status**: ⏳ Not started

### Task Group 2.1: Remove Local Session Creation in Client Mode

**Files**:
- `teleclaude/mcp_server.py` (teleclaude__start_session method)

**Current behavior**:
```python
# Creates session in local database
session = await db.create_session(
    computer_name=self.computer_name,
    tmux_session_name=f"{self.computer_name}-ai-{session_id[:8]}",
    origin_adapter="redis",
    title=title,
    adapter_metadata={...},
)
```

**New behavior**:
```python
# Generate session UUID (for remote session tracking only)
session_id = str(uuid.uuid4())

# Do NOT create local database session
# Do NOT create local channels
# Do NOT store local metadata

# Send create_session command to remote
await self.client.send_request(
    computer_name=computer,
    request_id=session_id,
    command="/create_session",
    metadata={
        "title": title,
        "project_dir": project_dir,
    },
)

# Wait for response with remote session_id
response = await self.client.read_response(session_id, timeout=5.0)
remote_session_id = json.loads(response).get("session_id")

# Return remote session_id (this is what user uses for subsequent calls)
return {
    "session_id": remote_session_id,
    "status": "success",
    "computer": computer,
}
```

**Testing**:
- Update test: `tests/integration/test_ai_to_ai_session_init_e2e.py`
- Verify NO local session created
- Verify remote session created
- Verify session_id returned is remote session_id

**Acceptance Criteria**:
- [ ] No local DB session created on client
- [ ] No local session file created
- [ ] Returns remote session_id
- [ ] Tests updated and passing

---

### Task Group 2.2: Remove Redis Output Streaming Code

**Files**:
- `teleclaude/adapters/redis_adapter.py`

**Code to remove**:

1. Remove `_output_stream_listeners` tracking:
```python
# DELETE this from __init__
self._output_stream_listeners: dict[str, asyncio.Task[None]] = {}
```

2. Remove output stream listener methods:
```python
# DELETE these methods entirely
async def _listen_to_output_stream(self, session_id: str, output_stream: str) -> None:
    ...

async def _start_output_listener(self, session_id: str, output_stream: str) -> None:
    ...
```

3. Remove output stream cleanup in stop():
```python
# DELETE this section from stop()
for session_id, task in list(self._output_stream_listeners.items()):
    task.cancel()
    ...
self._output_stream_listeners.clear()
```

4. Remove XADD to output stream:
```python
# Search for: await self.redis.xadd(output_stream, ...)
# DELETE all output stream writing code
```

**Testing**:
- Run full test suite: `make test`
- Verify no references to output streaming remain
- Check that Redis adapter still handles requests/responses

**Acceptance Criteria**:
- [ ] Output streaming code removed
- [ ] No listener tasks created
- [ ] All tests pass after removal

---

### Task Group 2.3: Update Redis Adapter Server Mode

**Files**:
- `teleclaude/adapters/redis_adapter.py`

**Changes**:

1. Ensure Redis adapter does NOT implement `send_output_update()`:
```python
# Verify this method does NOT exist in RedisAdapter
# If it exists, DELETE it
# Redis adapter inherits from BaseAdapter which has no send_output_update()
# Only UiAdapter subclasses implement send_output_update()
```

2. Update message handlers to support `/session_data`:
```python
# In _handle_redis_message method, add case for /session_data
async def _handle_redis_message(self, message_data: dict) -> None:
    command = message_data.get("command", "")

    if command == "/session_data":
        # This is already handled by BaseAdapter._handle_session_data
        # via command routing in handle_command()
        # Just ensure it flows through correctly
        pass
```

**Testing**:
- Test `/session_data` command via Redis
- Verify response contains session file data
- Test with remote request

**Acceptance Criteria**:
- [ ] Redis adapter does not implement send_output_update()
- [ ] /session_data command works via Redis
- [ ] Integration tests pass

---

## Phase 3: Simplify Polling Coordinator

**Goal**: Remove all AI session special cases from polling coordinator.

**Status**: ⏳ Not started

### Task Group 3.1: Remove AI Session Detection

**Files**:
- `teleclaude/core/polling_coordinator.py`

**Code to remove**:

```python
# DELETE this function entirely
def _is_ai_to_ai_session(session: Session) -> bool:
    """Check if session is AI-to-AI by presence of target_computer."""
    if not session or not session.adapter_metadata:
        return False
    return bool(session.adapter_metadata.get("target_computer"))
```

**Code to update**:

Remove usage of `_is_ai_to_ai_session()`:
```python
# In poll_and_send_output function, DELETE:
session = await db.get_session(session_id)
is_ai_session = _is_ai_to_ai_session(session)
```

**Testing**:
- Run test suite: `make test`
- Verify no references to `_is_ai_to_ai_session` remain

**Acceptance Criteria**:
- [ ] Function removed
- [ ] No references remain
- [ ] Tests pass

---

### Task Group 3.2: Remove AI Mode Output Chunking

**Files**:
- `teleclaude/core/polling_coordinator.py`

**Code to remove**:

```python
# DELETE this function entirely (lines 131-158)
async def _send_output_chunks_ai_mode(
    session_id: str,
    adapter_client: "AdapterClient",
    full_output: str,
) -> None:
    """Send output as sequential chunks for AI consumption."""
    # ... DELETE ALL OF THIS
```

**Testing**:
- Grep for references: `grep -r "_send_output_chunks_ai_mode" .`
- Ensure no calls remain
- Run test suite

**Acceptance Criteria**:
- [ ] Function removed
- [ ] No references remain
- [ ] Tests pass

---

### Task Group 3.3: Implement Command-Type Detection

**Files**:
- `teleclaude/core/polling_coordinator.py`

**Add new function**:
```python
def _is_claude_command(session: Session) -> bool:
    """Check if session is running Claude Code.

    Detects if /claude command was executed in this session.
    Claude writes output to claude_session_file, not tmux stdout.

    Returns:
        True if Claude is running, False for bash/vim/other commands
    """
    if not session or not session.adapter_metadata:
        return False

    # Check if /claude command was executed
    # Can be set when /claude is sent, or detected from tmux pane content
    return bool(session.adapter_metadata.get("is_claude_session"))
```

**Testing**:
- Unit test for `_is_claude_command()`
- Test with Claude session metadata
- Test with non-Claude session

**Acceptance Criteria**:
- [ ] Function implemented
- [ ] Returns True for Claude sessions
- [ ] Returns False for bash sessions
- [ ] Unit tests pass

---

### Task Group 3.4: Unify Output Handling (Command-Based)

**Files**:
- `teleclaude/core/polling_coordinator.py`
- `teleclaude/adapters/base_adapter.py` (use existing `get_session_data()`)

**Current code** (lines ~214-243):
```python
if is_ai_session:
    # AI mode: Send sequential chunks (no editing, no loss)
    await _send_output_chunks_ai_mode(
        event.session_id,
        adapter_client,
        clean_output,
    )
else:
    # Human mode: Edit same message via AdapterClient
    await adapter_client.send_output_update(
        event.session_id,
        clean_output,
        event.started_at,
        event.last_changed_at,
    )
```

**Replace with** (command-type based branching):
```python
# Determine output source based on COMMAND TYPE, not session type
session = await db.get_session(event.session_id)
is_claude = _is_claude_command(session)

if is_claude:
    # Claude mode: Read from claude_session_file (Claude writes to file, not stdout)
    # Use BaseAdapter.get_session_data() with timestamp filtering
    session_data = await adapter_client.get_session_data(
        event.session_id,
        since_timestamp=event.last_poll_timestamp  # Track between polls
    )
    output = session_data.get("messages", "")

    # Update timestamp for next poll
    event.last_poll_timestamp = datetime.now(UTC).isoformat()
else:
    # Bash mode: Read from tmux output (bash/vim write to stdout)
    output = clean_output  # From tmux capture

# Unified broadcast to ALL adapters (Telegram edits message, Redis does nothing)
await adapter_client.send_output_update(
    event.session_id,
    output,
    event.started_at,
    event.last_changed_at,
)
```

**Key Changes**:
1. Branch on **what command is running** (claude vs bash), NOT session type (AI vs human)
2. Claude sessions: Poll `claude_session_file` with timestamp
3. Bash sessions: Poll tmux stdout
4. Both: Unified `send_output_update()` broadcast

**UX Improvement**: Claude sessions now show real-time output in UI! 🎉

**Also update in DirectoryChanged and ProcessExited handlers** (lines ~280-320):
- Same pattern: check `is_claude_command()` to determine output source
- Use unified `send_output_update()` for all events

**Testing**:
- Run full test suite: `make test`
- Test Telegram bash session (should still work)
- Test Telegram /claude session (now shows live output!)
- Test AI-to-AI session (same unified pattern)
- Test observer pattern (Telegram editing single message)

**Acceptance Criteria**:
- [ ] All `if is_ai_session:` checks removed from coordinator
- [ ] Replaced with `if is_claude_command:` checks (command type, not session type)
- [ ] Claude sessions poll `claude_session_file` with timestamp
- [ ] Bash sessions poll tmux output
- [ ] Only `send_output_update()` used for output events
- [ ] All tests pass
- [ ] Manual verification: Telegram /claude shows live output
- [ ] Manual verification: Observer edits single message

---

## Phase 4: Cleanup and Documentation

**Goal**: Remove deprecated code, update docs, verify everything works.

**Status**: ⏳ Not started

### Task Group 4.1: Remove Deprecated MCP Tool

**Files**:
- `teleclaude/mcp_server.py`

**After migration period** (give users time to update):

```python
# DELETE teleclaude__get_session_status tool definition
# DELETE teleclaude__get_session_status implementation method
```

**Timeline**: Wait at least 1-2 weeks after deploying Phase 1-3 before removing.

**Communication**: Add deprecation notice in tool description first:
```python
# Add to teleclaude__get_session_status description
"**DEPRECATED**: Use teleclaude__get_session_data instead. "
"This tool will be removed in a future version."
```

**Acceptance Criteria**:
- [ ] Deprecation notice added
- [ ] Wait period completed
- [ ] Tool removed
- [ ] No users affected

---

### Task Group 4.2: Update Architecture Documentation

**Files**:
- `docs/architecture.md`

**Updates needed**:

1. Remove AI session streaming section
2. Update adapter pattern section to show unified approach
3. Document BaseAdapter session data access capability
4. Update sequence diagrams to show request/response pattern
5. Remove references to output stream polling

**New sections to add**:

```markdown
### Session Data Access Pattern

All adapters inherit `get_session_data()` from BaseAdapter, enabling them to serve
session data from Claude Code's session file storage:

- **Telegram**: Can export session data for user downloads
- **Redis**: Responds to remote `/session_data` requests
- **Future adapters**: Automatically get this capability

This creates a consistent pattern for accessing session history across all transport layers.

### Unified Output Distribution

The polling coordinator has ONE code path for all session types:

```python
await adapter_client.send_output_update(session_id, output, ...)
```

This broadcasts output to ALL adapters registered for the session:
- Telegram adapter: Edits single message using adapter_metadata
- Redis adapter: (Does nothing - no send_output_update implementation)
- Observer adapters: Edit their own messages using adapter_metadata

No special cases for AI sessions vs human sessions.
```

**Acceptance Criteria**:
- [ ] Architecture doc updated
- [ ] Sequence diagrams updated
- [ ] No references to streaming remain
- [ ] New patterns documented

---

### Task Group 4.3: Remove Redis Streaming Configuration

**Files**:
- `teleclaude/config.py`
- `config.yml`

**Configuration to remove**:

```yaml
# DELETE these from config.yml
redis:
  output_stream_maxlen: 100
  output_stream_ttl: 3600
```

```python
# DELETE these from config.py RedisConfig
output_stream_maxlen: int = 100
output_stream_ttl: int = 3600
```

**Keep**:
```yaml
redis:
  url: ...
  password: ...
  max_connections: 10
  socket_timeout: 5
  message_stream_maxlen: 1000  # Still needed for command messages
```

**Acceptance Criteria**:
- [ ] Unused config removed
- [ ] Essential config preserved
- [ ] Config validation passes

---

### Task Group 4.4: Final Verification

**End-to-end testing**:

1. **Local Telegram Session**:
   - [ ] User sends `/new_session` on Telegram
   - [ ] Session starts, output updates in single edited message
   - [ ] No regressions from refactoring

2. **AI-to-AI Session**:
   - [ ] MozBook calls `teleclaude__start_session(computer="RasPi4", ...)`
   - [ ] NO local session created on MozBook
   - [ ] Remote session created on RasPi4
   - [ ] MozBook calls `teleclaude__send_message(session_id, "run tests")`
   - [ ] MozBook calls `teleclaude__get_session_data(computer="RasPi4", session_id)`
   - [ ] Returns session output from RasPi4
   - [ ] Works correctly without streaming

3. **Observer Pattern**:
   - [ ] MozBook starts AI session on RasPi4
   - [ ] RasPi4 Telegram adapter observes session
   - [ ] Telegram edits ONE message (not multiple)
   - [ ] Message ID tracked in `adapter_metadata["telegram"]["output_message_id"]`
   - [ ] No message spam

4. **Session Data Command**:
   - [ ] Send `/session_data` command via any adapter
   - [ ] Returns session file content
   - [ ] Timestamp filtering works (if implemented)

**Acceptance Criteria**:
- [ ] All verification scenarios pass
- [ ] No regressions detected
- [ ] Architecture simplified as designed
- [ ] Code quality improved

---

## Deployment Strategy

### Incremental Rollout

1. **Phase 1 Deployment** (Non-breaking):
   - Deploy to development environment first
   - Test session data access works
   - Deploy to production (safe, additive only)

2. **Phase 2 Deployment** (Breaking for AI sessions):
   - Deploy to development environment
   - Test AI-to-AI sessions extensively
   - Coordinate deployment to both MozBook and RasPi4 simultaneously
   - **CRITICAL**: Both machines must be updated together

3. **Phase 3 Deployment** (Coordinator changes):
   - Deploy to development environment
   - Test all session types
   - Verify observer pattern works
   - Deploy to production during low-usage window

4. **Phase 4 Deployment** (Cleanup):
   - Wait for migration period
   - Deploy final cleanup
   - Update documentation

### Rollback Plan

If issues detected:

1. **Phase 1**: Safe to rollback, additive only
2. **Phase 2**: Rollback requires reverting both machines simultaneously
3. **Phase 3**: Rollback requires git revert + restart daemons
4. **Phase 4**: Rollback by re-adding deprecated code

### Testing Checklist Before Each Phase

- [ ] All unit tests pass (`make test-unit`)
- [ ] All integration tests pass (`make test-e2e`)
- [ ] Linting passes (`make lint`)
- [ ] Manual smoke tests completed
- [ ] Architecture changes documented

---

## Success Metrics

### Code Metrics

**Before**:
- polling_coordinator.py: ~350 lines with branching logic
- Redis adapter: ~500 lines with streaming code
- Number of code paths: 2 (human vs AI sessions)

**After**:
- polling_coordinator.py: ~250 lines (30% reduction)
- Redis adapter: ~400 lines (20% reduction)
- Number of code paths: 1 (unified)

### Architecture Metrics

- **Special cases removed**: 100% (no AI session branching)
- **Code duplication**: Reduced (shared session data access)
- **Adapter pattern compliance**: 100% (Redis works like others)

### Quality Metrics

- **Test coverage**: Maintained or improved
- **Lint score**: 10/10 maintained
- **Bugs introduced**: 0 (verified through testing)

---

## Risk Assessment

### High Risk Areas

1. **AI-to-AI session breakage**: Phase 2 changes fundamental session creation
   - **Mitigation**: Extensive testing, coordinated deployment

2. **Observer pattern regression**: Phase 3 changes output distribution
   - **Mitigation**: Test observer scenarios thoroughly before deployment

3. **Data loss**: Removing streaming could lose in-flight messages
   - **Mitigation**: Session files are source of truth, no data loss

### Medium Risk Areas

1. **Backward compatibility**: Old MCP tools might break
   - **Mitigation**: Keep deprecated tools during migration period

2. **Performance**: Request/response might be slower than streaming
   - **Mitigation**: Session file reads are fast, acceptable trade-off

### Low Risk Areas

1. **Local Telegram sessions**: Should be unaffected by changes
2. **Database**: No schema changes required
3. **Configuration**: Minimal config changes needed

---

## Timeline Estimate

- **Phase 1**: 2-3 days (implementation + testing)
- **Phase 2**: 3-4 days (careful refactoring + extensive testing)
- **Phase 3**: 2-3 days (coordinator simplification + verification)
- **Phase 4**: 1-2 days (cleanup + documentation)

**Total**: 8-12 days for complete implementation and testing.

**Deployment**: Can deploy phases incrementally over 2-3 weeks to ensure stability.
