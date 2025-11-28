# Unified Adapter Architecture: Remove AI Session Special Cases

> **Created**: 2025-11-28
> **Status**: 📝 Requirements
> **Goal**: Simplify adapter architecture by removing all AI session special cases and making Redis adapter work exactly like other adapters

## Problem Statement

The current architecture has **two separate code paths** for handling session output:

1. **Human sessions** (Telegram-originated): Use `send_output_update()` which edits a single message
2. **AI sessions** (Redis AI-to-AI): Use `_send_output_chunks_ai_mode()` which streams sequential chunks

This creates unnecessary complexity, duplication, and makes Redis adapter a special case instead of following the unified adapter pattern.

**Pain Points**:
- Polling coordinator has `if is_ai_session:` branching logic
- Redis adapter has custom streaming code that other adapters don't use
- AI sessions create dual database entries (local tracking session + remote execution session)
- Output streaming via Redis streams duplicates what Claude Code already stores in session files
- Observers (Telegram) can't properly track message IDs due to chunked output pattern
- Code is harder to maintain, test, and reason about

**Why Now**: We have an opportunity to massively simplify the architecture by leveraging what Claude Code already does (stores complete session to file) and making all adapters behave uniformly.

## Goals

**Primary Goals**:
1. **Remove all AI session special cases** - polling coordinator has ONE code path for all session types
2. **Unify adapter pattern** - Redis adapter implements same interface as Telegram adapter
3. **Eliminate output streaming** - use request/response pattern to read from Claude session files instead
4. **Single session architecture** - client mode creates NO local database session
5. **Shared session data access** - all adapters read from same `claude_session_file` using BaseAdapter method

**Secondary Goals**:
- Improve code maintainability by reducing branching logic
- Make observer pattern work correctly for all adapter types
- Reduce database complexity (fewer sessions to track)
- Leverage existing Claude Code session file storage

## Non-Goals

- Changing the observer pattern fundamentally (still uses `adapter_metadata` for tracking)
- Optimizing performance (unless it blocks the refactoring)
- Adding new features (pure refactoring/simplification effort)
- Changing MCP tool interfaces for users (maintain backward compatibility where possible)

## Architecture Changes

### 1. Polling Coordinator Simplification

**Before** (two code paths):
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

**After** (one unified path):
```python
# ALL sessions use send_output_update - broadcasts to all adapters
await adapter_client.send_output_update(
    event.session_id,
    clean_output,
    event.started_at,
    event.last_changed_at,
)
```

**Changes**:
- Remove `_is_ai_to_ai_session()` function
- Remove `_send_output_chunks_ai_mode()` function
- Remove `if is_ai_session:` branching in `poll_and_send_output()`
- All sessions treated identically by polling coordinator

### 2. Redis Adapter Refactoring

#### Client Mode (MozBook initiating to RasPi4)

**Before**:
- Creates local DB session on MozBook
- Stores local Claude session file
- Polls Redis output stream for chunks
- Streams chunks to MCP client

**After**:
- Does NOT create local DB session (no session in local database at all)
- Does NOT store local Claude session file (session only exists remotely)
- Uses request/response pattern: `send_request("/session_data")` + `read_response()`
- MCP tool `teleclaude__get_session_data()` pulls data on demand

**Key Change**: Client becomes a pure transport layer - no local session resources created.

#### Server Mode (RasPi4 receiving from MozBook)

**Before**:
- Implements custom output streaming to Redis streams
- Special chunking logic for AI consumption

**After**:
- Does NOT implement `send_output_update()` at all
- Polling coordinator calls `send_output_update()` which broadcasts to ALL adapters on that computer
- Telegram adapter (observer) edits single message using `adapter_metadata["telegram"]["output_message_id"]`
- Redis adapter handles `/session_data` command by reading `claude_session_file` (no streaming)

**Key Change**: No special output handling - relies on Claude Code's existing session file storage.

### 3. Session Data Access Pattern

**New BaseAdapter Method**:
```python
# teleclaude/adapters/base_adapter.py
async def get_session_data(
    self,
    session_id: str,
    since_timestamp: Optional[str] = None
) -> str:
    """Read session data from Claude Code session file.

    This is a shared capability for ALL adapters (Telegram, Redis, Slack, etc.)
    to serve session data from the standard claude_session_file location.

    Args:
        session_id: Session identifier
        since_timestamp: Optional UTC timestamp to filter messages since

    Returns:
        Formatted session data (messages, outputs, etc.)
    """
    # Implementation reads from storage/{session_id}/claude_session_file
    # Parses markdown format
    # Filters by timestamp if provided
    # Returns formatted content
```

**All adapters get this capability**:
- Telegram: Can serve session data for downloads or queries
- Redis: Responds to `/session_data` requests from remote clients
- Future adapters (Slack, WhatsApp): Automatically inherit this capability

**Command Pattern**:
- Standard command: `/session_data {timestamp_utc}`
- Handled by BaseAdapter (all adapters use same implementation)
- Returns content from `claude_session_file` filtered by timestamp

### 4. MCP Tool Changes

**Rename and refactor**:
- `teleclaude__get_session_status` → `teleclaude__get_session_data`

**New signature**:
```python
async def teleclaude__get_session_data(
    computer: str,
    session_id: str,
    since_timestamp: Optional[str] = None,
) -> dict[str, object]:
    """Get session data from remote computer.

    Pulls accumulated session data from claude_session_file on remote computer.
    This replaces the streaming pattern with a simple request/response pattern.

    Args:
        computer: Target computer name
        session_id: Session ID on remote computer
        since_timestamp: Optional UTC timestamp to get messages since

    Returns:
        Dict with session data (messages, outputs, status)
    """
```

**Implementation**:
```python
# Send request to remote
await self.client.send_request(
    computer_name=computer,
    request_id=f"{session_id}-data-{timestamp()}",
    command=f"/session_data {since_timestamp or ''}",
)

# Read response (remote reads claude_session_file and returns content)
response = await self.client.read_response(request_id, timeout=5.0)
return json.loads(response)
```

### 5. Observer Pattern (Unchanged Conceptually)

**Telegram as Observer**:
- RasPi4 runs session, Telegram adapter is observer
- Polling coordinator calls `adapter_client.send_output_update()`
- Telegram adapter uses `adapter_metadata["telegram"]["output_message_id"]` to edit ONE message
- Works correctly because all output goes through `send_output_update()` (not chunks)

**Redis as Observer** (if needed):
- Could observe sessions on same computer
- Would use `adapter_metadata["redis"]` to track state
- Currently not a primary use case (Redis used for cross-computer communication)

## Technical Constraints

- Must maintain backward compatibility with existing MCP tools (users' workflows shouldn't break)
- Must work with existing `BaseAdapter` → `UiAdapter` → `TelegramAdapter` hierarchy
- Must preserve observer pattern using `adapter_metadata[adapter_type]`
- Must work with existing tmux/Claude Code session lifecycle
- All tests must pass (`make test && make lint`)
- No breaking changes to Telegram adapter (users' primary interface)

## Success Criteria

### Code Quality
- [ ] Remove `if is_ai_session:` check from polling_coordinator.py
- [ ] Remove `_send_output_chunks_ai_mode()` function
- [ ] Remove `_is_ai_to_ai_session()` function
- [ ] Remove Redis output streaming code
- [ ] Add `get_session_data()` method to BaseAdapter
- [ ] Update Redis adapter to NOT create local sessions in client mode
- [ ] All tests pass: `make test`
- [ ] All linting passes: `make lint`
- [ ] Test coverage maintained or improved

### Functional Verification
- [ ] **Local Telegram sessions** still work (edit single message, no regression)
- [ ] **AI-to-AI sessions** work with new request/response pattern
- [ ] **Observer pattern** works (Telegram on RasPi4 edits ONE message when MozBook runs AI session)
- [ ] **Session data retrieval** works via new `teleclaude__get_session_data` tool
- [ ] **No dual sessions** - verify only remote session exists in DB for AI-to-AI
- [ ] **All adapters** can serve session data via `/session_data` command

### Architecture Verification
- [ ] Polling coordinator has ONE code path (no branching by session type)
- [ ] Redis adapter follows same pattern as other adapters
- [ ] BaseAdapter provides shared session data access capability
- [ ] Session files are the single source of truth (no duplicate storage)

## Open Questions

- ❓ Should we keep `teleclaude__start_session` signature the same or simplify since no local session is created?
- ❓ Do we need to migrate existing AI-to-AI sessions in database, or just handle new sessions correctly?
- ❓ Should `get_session_data()` return raw markdown or parsed/formatted data?
- ❓ What timestamp format should we use? ISO 8601 UTC string?
- ❓ Should we version the session file format to make parsing more reliable?

## Migration Path

### Phase 1: Add Session Data Access (No Breaking Changes)
1. Add `get_session_data()` to BaseAdapter
2. Add `/session_data` command handler to BaseAdapter
3. Update MCP server with new `teleclaude__get_session_data` tool (keep old tool for now)
4. Test that session data can be retrieved correctly

### Phase 2: Refactor Redis Adapter
1. Update Redis adapter client mode to NOT create local sessions
2. Update Redis adapter server mode to use `get_session_data()` instead of streaming
3. Remove output stream polling code
4. Test AI-to-AI sessions work with new pattern

### Phase 3: Simplify Polling Coordinator
1. Remove `if is_ai_session:` branching
2. Remove `_send_output_chunks_ai_mode()` function
3. Remove `_is_ai_to_ai_session()` function
4. All sessions use unified `send_output_update()` path
5. Verify observer pattern works for all adapter types

### Phase 4: Cleanup
1. Remove deprecated `teleclaude__get_session_status` tool (after migration period)
2. Remove Redis output streaming configuration
3. Update documentation and architecture diagrams
4. Remove any AI session special case comments

## References

- **Architecture docs**: docs/architecture.md (needs update after this refactor)
- **Code locations**:
  - `teleclaude/core/polling_coordinator.py` - Remove AI session branching
  - `teleclaude/adapters/base_adapter.py` - Add get_session_data() method
  - `teleclaude/adapters/redis_adapter.py` - Remove streaming, use request/response
  - `teleclaude/adapters/ui_adapter.py` - Observer pattern via adapter_metadata
  - `teleclaude/mcp_server.py` - New teleclaude__get_session_data tool
- **Session file format**: storage/{session_id}/claude_session_file (markdown format)
- **Related work**: Observer message tracking (commit 7e9e2c7) enables this simplification
