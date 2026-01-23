# Role-Based Tool Filtering - Requirements

## Problem Statement

Worker agents spawned by `run_agent_command` (e.g., `next-build`, `next-review`) currently have access to all MCP tools, including orchestration tools they must not use. Previous mitigation via FORBIDDEN sections in command files is brittle and duplicates information across files.

## Requirements

### Functional

1. **Tool Visibility by Role**
   - Worker agents see only worker-allowed tools
   - Orchestrator agents see all tools
   - Tool filtering is transparent to client

2. **Role Injection**
   - Role is written to persistent marker file: `$TMPDIR/teleclaude_role`
   - Marker file created during session setup (same pattern as `teleclaude_session_id`)
   - File format: plain text, single role name (e.g., "worker", "orchestrator")

3. **MCP Wrapper Integration**
   - Wrapper reads role marker before returning tool list
   - Filters `initialize` response to remove disallowed tools
   - Handles missing role gracefully (defaults to orchestrator)

4. **Tool Access Policy**
   - Workers cannot access: `next_work`, `next_prepare`, `mark_phase`, `start_session`, `send_message`, `run_agent_command`
   - Workers can access: all other tools (file ops, bash, git, context, etc.)
   - Orchestrators can access: all tools

### Non-Functional

1. **Backwards Compatibility**
   - Existing orchestrator sessions continue to work
   - Existing tool contracts unchanged
   - No client-side changes needed

2. **Maintainability**
   - Policy defined in one place (`teleclaude/mcp/role_tools.py`)
   - Clear mapping of roles to allowed tools
   - Easy to audit and modify

3. **Testing**
   - Unit tests verify filtering logic
   - Integration test verifies filtered tool list in worker sessions
   - No tool inspection without proper role

## Success Criteria

1. Worker session cannot invoke `teleclaude__next_work` (receives method not found or similar)
2. Orchestrator session can invoke all tools
3. Tool list returned to worker excludes forbidden tools
4. Marker file mechanism works reliably across session types
5. Command files can be cleaned (FORBIDDEN sections removed)
