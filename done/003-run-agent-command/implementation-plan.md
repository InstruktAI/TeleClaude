# Run Agent Command - Implementation Plan

> **Requirements**: todos/run-agent-command/requirements.md
> **Status**: Implementation Complete
> **Created**: 2025-12-16

## Implementation Groups

**IMPORTANT**: Tasks within each group CAN be executed in parallel. Groups must be executed sequentially.

### Group 1: Core Implementation

_Single file modification - mcp_server.py_

- [x] **SEQUENTIAL** Add `teleclaude__run_agent_command` Tool definition in `list_tools()`
- [x] **SEQUENTIAL** Add call_tool handler case for `teleclaude__run_agent_command`
- [x] **SEQUENTIAL** Implement `teleclaude__run_agent_command` method with dual-mode logic

### Group 2: Testing

_These tasks can run in parallel_

- [x] **PARALLEL** Write unit tests in `tests/unit/test_mcp_server.py` (added to existing file):
  - Command string construction (normalization, args handling)
  - Mode detection (session_id present vs absent)
  - Working directory computation (project + subfolder)
  - Validation (missing project when no session_id)
- [x] **DEPENDS: Group 1** Run targeted tests and fix failures

### Group 3: Verification & Polish

- [x] **SEQUENTIAL** Run `make format && make lint && make test`
- [x] **SEQUENTIAL** Manual verification: restart daemon, confirm tool in MCP list

### Group 4: Review & Finalize

- [x] **SEQUENTIAL** Code review produces `review-findings.md`
- [x] **SEQUENTIAL** Review feedback handled - fixes applied

### Group 5: Merge & Deploy

**Pre-merge:**

- [x] **SEQUENTIAL** Tests pass locally (`make test`)
- [x] **SEQUENTIAL** All Groups 1-4 complete

**Post-merge:**

- [x] **SEQUENTIAL** Merged to main and pushed
- [ ] **SEQUENTIAL** Deployment verified on all computers
- [ ] **SEQUENTIAL** Worktree cleaned up (if used)
- [ ] **SEQUENTIAL** Roadmap item marked complete (if applicable)

## Implementation Notes

### Key Design Decisions

1. **Dual-mode operation**: Single tool handles both "start new" and "send to existing" based on presence of `session_id` parameter.

2. **Delegation pattern**:
   - New session mode: Delegates to `teleclaude__start_session` internally
   - Existing session mode: Delegates to `teleclaude__send_message` internally
   - Avoids duplicating listener registration, transport handling, etc.

3. **Working directory**: `{project}/{subfolder}` computed before calling start_session.

4. **Auto-generated title**: `"/{command} {args}"` for new sessions.

### Files to Modify

**Modified Files**:

- `teleclaude/mcp_server.py`:
  - Tool definition (~30 lines)
  - call_tool handler (~15 lines)
  - Implementation method (~50 lines)

**New Files**:

- `tests/unit/test_run_agent_command.py` - Unit tests

### Implementation Details

**Tool Definition** (inputSchema):
```python
{
    "type": "object",
    "properties": {
        "computer": {
            "type": "string",
            "description": "Target computer name",
        },
        "command": {
            "type": "string",
            "description": "Command name without leading / (e.g., 'next-work', 'compact')",
        },
        "args": {
            "type": "string",
            "description": "Optional arguments for the command",
            "default": "",
        },
        "session_id": {
            "type": "string",
            "description": "Optional: send to existing session. If omitted, starts new session.",
        },
        "project": {
            "type": "string",
            "description": "Project directory. Required when starting new session (no session_id).",
        },
        "agent": {
            "type": "string",
            "enum": ["claude", "gemini", "codex"],
            "description": "Agent type for new sessions. Default: claude",
            "default": "claude",
        },
        "subfolder": {
            "type": "string",
            "description": "Optional subfolder within project (e.g., 'worktrees/my-feature')",
            "default": "",
        },
    },
    "required": ["computer", "command"],
}
```

**Method signature**:
```python
async def teleclaude__run_agent_command(
    self,
    computer: str,
    command: str,
    args: str = "",
    session_id: str | None = None,
    project: str | None = None,
    agent: str = "claude",
    subfolder: str = "",
    caller_session_id: str | None = None,
) -> dict[str, object]:
```

**Core logic**:
```python
# Normalize command
normalized_cmd = command.lstrip("/")

# Build full command string
full_command = f"/{normalized_cmd} {args}".strip() if args.strip() else f"/{normalized_cmd}"

if session_id:
    # Mode 1: Send to existing session
    chunks = []
    async for chunk in self.teleclaude__send_message(
        computer, session_id, full_command, caller_session_id
    ):
        chunks.append(chunk)
    return {"status": "sent", "session_id": session_id, "message": "".join(chunks)}
else:
    # Mode 2: Start new session with command
    if not project:
        return {"status": "error", "message": "project required when session_id not provided"}

    # Compute working directory
    working_dir = f"{project}/{subfolder}".rstrip("/") if subfolder else project

    # Generate title from command
    title = full_command

    # Delegate to start_session
    result = await self.teleclaude__start_session(
        computer=computer,
        project_dir=working_dir,
        title=title,
        message=full_command,
        caller_session_id=caller_session_id,
        agent=agent,
    )
    return result
```

## Success Verification

Before marking complete:

- [x] Tool `teleclaude__run_agent_command` appears in MCP tool list
- [ ] Can start new session with command (no session_id) - *needs real-world test*
- [ ] Can send command to existing session (with session_id) - *needs real-world test*
- [x] Subfolder parameter correctly sets working directory (unit tested)
- [x] Agent parameter selects correct agent type (unit tested)
- [ ] Returns session_id usable with `get_session_data` and `send_message` - *needs real-world test*
- [ ] Listener registration works - *needs real-world test*
- [x] Unit tests pass
- [x] All linters and tests pass

## Completion

When all Group 5 checkboxes are complete, this item is done.
