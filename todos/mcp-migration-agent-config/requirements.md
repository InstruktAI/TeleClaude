# Requirements: mcp-migration-agent-config

## Goal

Remove MCP server configuration from all agent session types and validate that
agents can perform all existing operations using `telec` subcommands instead of MCP tools.

## Scope

### In scope

- Remove `enabledMcpjsonServers` MCP config from agent session bootstrap
- Remove MCP wrapper PATH setup from tmux session environment
- Ensure `telec` is on PATH in all agent sessions
- Ensure `$TMPDIR/teleclaude_session_id` continues to be written
- Update `agent_cli.py` to remove MCP-related flags
- End-to-end validation with Claude, Gemini, and Codex agents
- Validate orchestrator workflow: prepare → build → review → finalize
- Validate worker isolation

### Out of scope

- Deleting MCP server code (next phase — this phase just stops using it)
- Changes to non-agent consumers (Telegram, Discord, TUI, web)

## Success Criteria

- [ ] Claude Code sessions start without MCP server in config
- [ ] Gemini sessions start without MCP server in config
- [ ] Codex sessions start without MCP server in config
- [ ] Full orchestrator cycle works via telec tools
- [ ] Worker agents cannot discover orchestration tools
- [ ] Agent jobs (cron runner) still function
- [ ] `get_context` works via telec (not MCP) in new sessions
- [ ] No regression in multi-computer session management

## Constraints

- MCP server daemon process may still run (for any legacy connections) but
  no new sessions should use it
- This is the last validation gate before the deletion phase

## Risks

- Agent prompting differences: MCP tools appear as structured tool calls,
  telec appears as bash invocations. Agents may need prompt tuning.
- Gemini/Codex may handle bash-based tool invocation differently than Claude.
