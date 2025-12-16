# Run Agent Command MCP Tool

> **Created**: 2025-12-16
> **Status**: Requirements

## Problem Statement

Currently, AI-to-AI orchestration requires multiple steps:
1. Call `start_session` to create a session with a free-form message
2. Or call `send_message` to send to an existing session

There's no direct way to:
- Start a session with a slash command as the initial task
- Support worktree subdirectories for feature branches
- Have a unified tool that handles both new and existing sessions

A dedicated `run_agent_command` tool provides:
- **Unified interface** - One tool for both starting new sessions and commanding existing ones
- **Command-first semantics** - Explicitly designed for slash commands, not free-form prompts
- **Worktree support** - Subfolder parameter for working in git worktrees
- **Agent flexibility** - Specify agent type (claude, gemini, codex) for new sessions

## Goals

**Primary Goals**:

- Provide unified MCP tool for running slash commands on AI sessions
- Support two modes: start new session OR send to existing session
- Accept command name and optional arguments as separate parameters
- Support worktree subdirectories via `subfolder` parameter
- Support multiple agent types (claude, gemini, codex)
- Follow existing patterns for session tracking and listener registration

## Non-Goals

- Command validation per agent type
- Command output parsing or structured responses
- Blocking wait for command completion
- Shell command execution (this is for AI slash commands only)

## User Stories / Use Cases

### Story 1: Start Session with Command

As a master AI, I want to start a worker session with a specific command so that I can delegate work without needing separate start_session + send_message calls.

**Acceptance Criteria**:

- [ ] Can start session: `run_agent_command(computer="raspi", project="/home/user/apps/MyProject", command="next-work", args="my-feature")`
- [ ] Session starts with `/{command} {args}` as initial message
- [ ] Returns session_id for tracking
- [ ] Registers listener for completion notifications

### Story 2: Start Session in Worktree

As a master AI, I want to start a session in a git worktree subdirectory so that I can work on feature branches in isolation.

**Acceptance Criteria**:

- [ ] Can specify `subfolder="worktrees/my-feature"`
- [ ] Session working directory becomes `{project}/{subfolder}`
- [ ] Works with any agent type

### Story 3: Send Command to Existing Session

As a master AI, I want to send a command to an existing session so that I can trigger actions like `/compact` or `/clear` on workers I'm managing.

**Acceptance Criteria**:

- [ ] Can send to existing: `run_agent_command(computer="raspi", session_id="abc-123", command="compact")`
- [ ] Command is delivered as `/{command}` or `/{command} {args}`
- [ ] project/agent/subfolder parameters ignored when session_id provided

### Story 4: Multi-Agent Support

As an orchestrator, I want to specify which AI agent to use so that I can leverage different agents for different tasks.

**Acceptance Criteria**:

- [ ] Can specify `agent="gemini"` or `agent="codex"` for new sessions
- [ ] Defaults to `agent="claude"` if not specified
- [ ] Agent parameter ignored when sending to existing session

## Technical Constraints

- Must integrate with existing MCP server infrastructure
- Must use existing session creation and message delivery mechanisms
- Must follow existing event subscription pattern (PUB-SUB listeners)
- Must work with `local` computer designation
- Must work across computers in the TeleClaude network
- Must store/track remote sessions like `start_session` does

## API Design

```python
teleclaude__run_agent_command(
    computer: str,              # Required: target computer name
    command: str,               # Required: command name (e.g., "next-work", "compact")
    args: str = "",             # Optional: arguments for the command
    session_id: str | None,     # Optional: if provided, send to existing session
    project: str | None,        # Optional: project dir (required if no session_id)
    agent: str = "claude",      # Optional: "claude" | "gemini" | "codex"
    subfolder: str = "",        # Optional: subfolder within project (e.g., "worktrees/feat-x")
)
```

**Behavior**:

1. **If `session_id` provided**:
   - Normalize command (strip leading `/` if present)
   - Construct `/{command}` or `/{command} {args}`
   - Send to existing session via `send_message` mechanics
   - Ignore project/agent/subfolder parameters

2. **If `session_id` NOT provided**:
   - Require `project` parameter (error if missing)
   - Compute working directory: `{project}/{subfolder}` or just `{project}`
   - Normalize command and construct command string
   - Start new session via `start_session` mechanics with command as initial message
   - Auto-generate title: `"Command: /{command} {args}"` or similar
   - Return session_id for tracking

**Input normalization**: If caller includes leading `/` in command, strip it automatically.

## Success Criteria

- [ ] Tool `teleclaude__run_agent_command` appears in MCP tool list
- [ ] Can start new session with command (no session_id)
- [ ] Can send command to existing session (with session_id)
- [ ] Subfolder parameter correctly sets working directory
- [ ] Agent parameter selects correct agent type for new sessions
- [ ] Returns session_id that can be used with `get_session_data` and `send_message`
- [ ] Listener registration works (completion notifications received)
- [ ] Unit tests cover both modes and input normalization
- [ ] Integration test confirms end-to-end functionality

## Open Questions

None - requirements are complete.

## References

- Existing tools: `teleclaude__start_session`, `teleclaude__send_message`
- MCP server: `teleclaude/mcp_server.py`
- Architecture: `docs/mcp-architecture.md`
