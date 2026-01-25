# Role-Based Tool Filtering - Implementation Plan

## Architecture Overview

```
run_agent_command(command="next-build")
  ↓ (derives role from command)
  ↓ role="worker"
tmux_bridge._prepare_session_tmp_dir()
  ↓ (writes marker file)
  ↓ $TMPDIR/teleclaude_role = "worker"
agent session starts
  ↓ (connects to MCP wrapper)
mcp_wrapper._read_role_marker()
  ↓ (reads role)
  ↓ role="worker"
mcp_wrapper._handle_initialize()
  ↓ (filters tools)
  ↓ removes forbidden tools
client receives filtered tool list
```

## Implementation Sequence

### Phase 1: Policy Definition

**1.1 Create `teleclaude/mcp/role_tools.py`**

```python
ROLE_TOOLS = {
    "worker": [
        # All tools except orchestration
        # Exclude: next_work, next_prepare, mark_phase, start_session, send_message, run_agent_command
    ],
    "orchestrator": [
        # All tools available
    ]
}

def get_excluded_tools(role: str) -> set[str]:
    """Return set of tool names excluded for this role."""
```

- Define `WORKER_EXCLUDED_TOOLS` constant (list of forbidden tool names)
- Implement `get_excluded_tools(role)` to return excluded names for a role
- Add function to list allowed tools for a role

### Phase 2: Session Setup

**2.1 Update `teleclaude/core/tmux_bridge.py:_prepare_session_tmp_dir()`**

- Add optional `role: str = "orchestrator"` parameter
- Write role marker file: `(session_tmp / "teleclaude_role").write_text(role, encoding="utf-8")`
- Ensure marker file has same permissions/format as `teleclaude_session_id`

**2.2 Update `teleclaude/core/tmux_bridge.py:_create_tmux_session()`**

- Add optional `role` parameter
- Pass role to `_prepare_session_tmp_dir(role)`

**2.3 Update `teleclaude/mcp/handlers.py:run_agent_command()`**

- Derive role from command name:
  - Commands starting with "next-": role="worker"
  - All other commands: role="orchestrator"
- Pass `role=role` when calling session creation

### Phase 3: Wrapper Filtering

**3.1 Update `teleclaude/entrypoints/mcp_wrapper.py`**

Add `_read_role_marker()` function:

```python
def _read_role_marker() -> str | None:
    """Read TeleClaude role from per-session TMPDIR marker file."""
    # Mirror _read_session_id_marker() pattern
    # Read from $TMPDIR/teleclaude_role
    # Return role name or None
```

Update `_handle_initialize()`:

```python
def _handle_initialize(msg):
    # ... existing code ...
    role = _read_role_marker() or "orchestrator"

    # Filter tools before returning
    if role == "worker":
        tools = [t for t in tools if t["name"] not in get_excluded_tools("worker")]

    # Return modified response with filtered tools
```

Import `get_excluded_tools` from `mcp.role_tools`

### Phase 4: Cleanup

**4.1 Revert Command Files**

- Remove FORBIDDEN sections from:
  - `agents/commands/next-build.md`
  - `agents/commands/next-review.md`
  - `agents/commands/next-fix-review.md`
  - `agents/commands/next-finalize.md`
  - `agents/commands/next-prepare.md`
  - `agents/commands/next-bugs.md`
  - `agents/commands/next-defer.md`
- Restore files to minimal state (just references to snippets)

### Phase 5: Testing

**5.1 Unit Tests** (`tests/unit/test_role_tools.py`)

- Test `get_excluded_tools("worker")` returns correct set
- Test `get_excluded_tools("orchestrator")` returns empty set
- Test role marker reading

**5.2 Integration Tests** (`tests/integration/test_mcp_role_filtering.py`)

- Create worker session, verify forbidden tools absent
- Create orchestrator session, verify all tools present
- Test marker file creation and reading
- Test filtering in wrapper

## Files to Create

- [x] `teleclaude/mcp/role_tools.py`

## Files to Modify

- [ ] `teleclaude/core/tmux_bridge.py` - Add role parameter to session creation
- [ ] `teleclaude/mcp/handlers.py:run_agent_command()` - Derive and pass role
- [ ] `teleclaude/entrypoints/mcp_wrapper.py` - Read role, filter tools
- [ ] `agents/commands/next-*.md` - Revert FORBIDDEN sections

## Files to Create (Tests)

- [ ] `tests/unit/test_role_tools.py`
- [ ] `tests/integration/test_mcp_role_filtering.py`

## Risk Assessment

### Unknowns

- Whether MCP client will properly handle filtered tool list (should be transparent)
- Whether existing sessions break if role marker absent (mitigated by defaulting to orchestrator)

### Mitigation

- Default to orchestrator role if marker missing (backwards compatible)
- Add comprehensive tests before deployment
- Verify on staging before rolling out

## Success Verification

1. Run `make test` - all tests pass
2. Run `make lint` - no issues
3. Verify worker agent cannot call `teleclaude__next_work` in manual test
4. Verify orchestrator agent can call all tools
5. Verify tool list is filtered transparently (client doesn't error)
