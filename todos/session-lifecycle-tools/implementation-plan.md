# Session Lifecycle Tools - Implementation Plan

> **Requirements**: todos/session-lifecycle-tools/requirements.md
> **Status**: Ready to Implement
> **Created**: 2025-12-03

## Implementation Groups

**IMPORTANT**: Tasks within each group CAN be executed in parallel. Groups must be executed sequentially.

### Group 1: Session Listeners Module Extension

_These tasks can run in parallel_

- [ ] **PARALLEL** Add `unregister_listener(target_session_id, caller_session_id)` function to `teleclaude/core/session_listeners.py` - removes a specific listener for a caller-target pair

### Group 2: Command Handlers Extension

_These tasks can run in parallel_

- [ ] **PARALLEL** Add `handle_end_session(context)` to `teleclaude/core/command_handlers.py` - handles graceful session termination using existing cleanup utilities

### Group 3: MCP Server Tool Implementation

_These tasks depend on Group 1 and Group 2_

- [ ] **DEPENDS: Group 1, Group 2** Add `teleclaude__stop_notifications` and `teleclaude__end_session` Tool definitions to `list_tools()` in `teleclaude/mcp_server.py`
- [ ] **DEPENDS: Group 1, Group 2** Add `teleclaude__stop_notifications` method to `TeleClaudeMCPServer` class - calls unregister_listener for local, routes via Redis for remote
- [ ] **DEPENDS: Group 1, Group 2** Add `teleclaude__end_session` method to `TeleClaudeMCPServer` class - calls handle_end_session for local, routes via Redis for remote
- [ ] **DEPENDS: Group 1, Group 2** Add tool dispatch cases in `call_tool()` for both new tools

### Group 4: Testing

_These tasks can run in parallel_

- [ ] **PARALLEL** Write unit tests for `unregister_listener` in `tests/unit/test_session_listeners.py`
- [ ] **PARALLEL** Write unit tests for `teleclaude__stop_notifications` and `teleclaude__end_session` in `tests/unit/test_mcp_server.py`
- [ ] **DEPENDS: Group 3** Run `make format && make lint && make test` and fix any failures

### Group 5: Review & Finalize

_These tasks must run sequentially_

- [ ] Review created (automated via code-reviewer agent)
- [ ] Review feedback handled

### Group 6: Deployment

_These tasks must run sequentially_

- [ ] Test locally with `make restart && make status`
- [ ] Switch to main: `cd ../.. && git checkout main`
- [ ] Merge worktree branch: `git merge session-lifecycle-tools`
- [ ] Push and deploy: `/deploy`
- [ ] Verify deployment on all computers
- [ ] Cleanup worktree: `/remove-worktree session-lifecycle-tools`

## Task Markers

- `**PARALLEL**`: Can execute simultaneously with other PARALLEL tasks in same group
- `**DEPENDS: GroupName**`: Requires all tasks in GroupName to complete first
- `**SEQUENTIAL**`: Must run after previous task in group completes

## Implementation Notes

### Key Design Decisions

1. **stop_notifications**: Uses existing `unregister_listener` pattern but with new function that removes only the caller's listener for a specific target (not all listeners)
2. **end_session**: Reuses `cleanup_session_resources()` from session_cleanup.py plus tmux kill and DB update
3. **Remote routing**: For remote sessions, send command via Redis transport just like other remote operations

### Implementation Details

**`teleclaude__stop_notifications(computer, session_id)`**:
- Extract caller_session_id from context
- For local: call `unregister_listener(target_session_id, caller_session_id)` directly
- For remote: send `stop_notifications` command via Redis (remote daemon handles it)
- Return success/failure status

**`teleclaude__end_session(computer, session_id)`**:
- For local:
  1. Get session from DB
  2. Kill tmux session via terminal_bridge.kill_session()
  3. Mark session closed in DB
  4. Call cleanup_session_resources() for full cleanup
- For remote: send `end_session` command via Redis (remote daemon handles it)
- Return success/failure status

### Files to Create/Modify

**Modified Files**:

- `teleclaude/core/session_listeners.py` - Add `unregister_listener()` function
- `teleclaude/core/command_handlers.py` - Add `handle_end_session()` function
- `teleclaude/mcp_server.py` - Add both tools (Tool defs, methods, dispatch)
- `tests/unit/test_session_listeners.py` - Add tests for unregister_listener
- `tests/unit/test_mcp_server.py` - Add tests for both new tools

## Success Verification

Before marking complete, verify all requirements success criteria:

- [ ] Both tools are registered in MCP server's `list_tools()`
- [ ] Both tools have proper MCP schema with required arguments
- [ ] Unit tests verify local session behavior
- [ ] `make lint && make test` passes
- [ ] Tools work correctly on real multi-computer setup (rsync test)

## Completion

- [ ] All task groups completed
- [ ] Success criteria verified
- [ ] Mark roadmap item as complete (`[x]`) - N/A (not in roadmap)

---

**Usage with /next-work**: The next-work command will execute tasks group by group, running PARALLEL tasks simultaneously when possible.
