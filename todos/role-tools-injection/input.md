# Role-Based Tool Filtering via MCP Wrapper

## Problem

Worker agents (running commands like `next-build`, `next-review`, etc.) currently have access to all MCP tools, including orchestration tools they should not use (`teleclaude__next_work`, `teleclaude__mark_phase`, `teleclaude__start_session`, etc.).

This was previously addressed with explicit FORBIDDEN sections in command files, but that's a brittle workaround. Instead, tools should be filtered at the MCP protocol level.

## Intended Outcome

Implement role-based tool filtering so:

1. Worker agents only see allowed tools (no orchestration tools)
2. Orchestrator agents see all tools
3. Role is injected via a persistent marker file (`teleclaude_role`) in the per-session TMPDIR (same pattern as `teleclaude_session_id`)
4. MCP wrapper reads the role and filters tools before returning to the client

## Technical Approach

- Create `teleclaude/mcp/role_tools.py` with tool access policy
- Update `tmux_bridge._prepare_session_tmp_dir()` to write `teleclaude_role` marker
- Update `mcp_wrapper.py` to read role marker and filter tools
- Update `run_agent_command()` to pass role when creating worker sessions
- Revert FORBIDDEN sections from command files (clean them up)

## Success Criteria

1. Worker agents cannot see orchestration tools
2. Orchestrator agents see all tools
3. Tool filtering happens transparently (client unaware)
4. Tests verify filtering works correctly
