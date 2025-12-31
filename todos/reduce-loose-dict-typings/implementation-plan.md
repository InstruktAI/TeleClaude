# Implementation Plan: Reduce Loose Dict Typings

## Overview

Add TypedDicts for known data structures while keeping `dict[str, object]` for truly dynamic JSON.

**Target:** Reduce ~130 occurrences to ~65 (50% reduction)

---

## Group 1: Core TypedDict Definitions

Create the shared TypedDict definitions that will be reused across the codebase.

### Task 1.1: Add TypedDicts to `teleclaude/core/types.py` (new file)

Create new `types.py` module with TypedDicts:

```python
from typing import TypedDict, NotRequired

class SystemStatsDict(TypedDict):
    """System statistics for a computer."""
    memory_percent: float
    disk_percent: float
    cpu_percent: float

class ComputerInfoDict(TypedDict):
    """Computer information returned by list_computers."""
    name: str
    status: str  # "local" | "online" | "offline"
    last_seen: str  # ISO 8601
    adapter_type: str
    user: NotRequired[str]
    host: NotRequired[str]
    ip: NotRequired[str]
    role: NotRequired[str]
    system_stats: NotRequired[SystemStatsDict]

class SessionInfoDict(TypedDict):
    """Session information returned by list_sessions."""
    session_id: str
    computer_name: str
    title: str
    status: str
    closed: bool
    created_at: NotRequired[str]
    last_activity: NotRequired[str]
    agent: NotRequired[str]

class ToolSuccessResponse(TypedDict):
    """Standard MCP tool success response."""
    status: str  # "success"
    session_id: NotRequired[str]
    message: NotRequired[str]
    data: NotRequired[object]

class ToolErrorResponse(TypedDict):
    """Standard MCP tool error response."""
    status: str  # "error"
    message: str
    error: NotRequired[str]

# Union for tool responses
ToolResponse = ToolSuccessResponse | ToolErrorResponse
```

- [ ] Create `teleclaude/core/types.py`

### Task 1.2: Update `teleclaude/core/models.py`

Replace `dict[str, object]` in dataclass fields:

- [ ] `PeerInfo.system_stats: Optional[SystemStatsDict]`
- [ ] `MessageMetadata.channel_metadata: Optional[dict[str, str]]` (values are strings)
- [ ] Keep `to_dict()` returns as `dict[str, object]` (serialization output)
- [ ] Keep `from_dict()` params as `dict[str, object]` (deserialization input)

---

## Group 2: MCP Server Tool Returns

Update `teleclaude/mcp_server.py` to use TypedDicts for return types.

### Task 2.1: list_computers and related

- [ ] `teleclaude__list_computers() -> list[ComputerInfoDict]`
- [ ] Update `local_computer` variable annotation
- [ ] Update `remote_peers` variable annotation

### Task 2.2: Session tools

- [ ] `teleclaude__start_session() -> ToolResponse`
- [ ] `teleclaude__run_agent_command() -> ToolResponse`
- [ ] `teleclaude__send_message() -> ToolResponse`
- [ ] `teleclaude__get_session_data() -> ToolResponse`
- [ ] `teleclaude__list_sessions() -> list[SessionInfoDict]`
- [ ] `teleclaude__end_session() -> ToolResponse`
- [ ] `teleclaude__stop_notifications() -> ToolResponse`

### Task 2.3: Other tools

- [ ] `teleclaude__deploy() -> dict[str, ToolResponse]`
- [ ] `teleclaude__handle_agent_event() -> str` (already specific)
- [ ] `teleclaude__next_prepare() -> ToolResponse`
- [ ] `teleclaude__next_work() -> ToolResponse`

---

## Group 3: Core Module Updates

### Task 3.1: `teleclaude/core/events.py`

Keep `raw: dict[str, object]` - these hold agent-specific hook payloads that vary by agent. Document why they stay loose.

- [ ] `UpdateSessionEvent.updated_fields` → `dict[str, str | bool | None]` (limited value types)
- [ ] `ErrorEvent.details` → keep loose or create `ErrorDetailsDict`
- [ ] `CreateSessionEvent.channel_metadata` → `dict[str, str]`

### Task 3.2: `teleclaude/core/adapter_client.py`

- [ ] Review 14 occurrences - most are JSON parsing (keep loose)
- [ ] `discover_peers() -> list[ComputerInfoDict]`

### Task 3.3: `teleclaude/core/ux_state.py`

- [ ] Review 6 occurrences - UX state is stored as JSON blob
- [ ] Create `UxStateDict` if structure is stable

### Task 3.4: `teleclaude/core/command_handlers.py`

- [ ] `handle_get_computer_info() -> ComputerInfoDict`
- [ ] `handle_list_projects() -> list[ProjectInfoDict]`

### Task 3.5: `teleclaude/core/computer_registry.py`

- [ ] 4 occurrences - computer discovery/status
- [ ] Use `ComputerInfoDict` where applicable

---

## Group 4: Keep Loose (Document Why)

These files intentionally use `dict[str, object]` for external/dynamic data:

### Task 4.1: Document in `teleclaude/utils/transcript.py` (23 occurrences)

- All transcript parsing is external JSON from Claude/Gemini/Codex
- Format varies by agent version - cannot be typed statically
- Add module docstring explaining this

### Task 4.2: Document in agent parser files

- `teleclaude/core/agent_parsers.py` (7) - agent-specific JSON
- `teleclaude/hooks/adapters/claude.py` (1) - Claude hook payloads
- `teleclaude/hooks/adapters/gemini.py` (2) - Gemini hook payloads
- `teleclaude/hooks/receiver.py` (4) - agent hook routing

---

## Testing Strategy

1. Run `make lint` after each group - mypy will catch type errors
2. Run `make test` after completing all groups
3. No new tests needed - existing tests cover functionality

---

## Estimated Changes

| Group | Files | Dict Replacements | New TypedDicts |
|-------|-------|-------------------|----------------|
| 1     | 2     | 3                 | 6              |
| 2     | 1     | 26                | 0 (uses G1)    |
| 3     | 5     | 20                | 1-2            |
| 4     | 5     | 0 (documented)    | 0              |

**Total reduction:** ~50 dict[str, object] → TypedDict = ~60 remaining (within target)
