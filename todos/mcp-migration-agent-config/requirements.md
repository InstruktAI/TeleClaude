# Requirements: mcp-migration-agent-config

## Goal

Remove MCP server configuration from all agent session types and validate that
agents can perform all existing operations using `telec` subcommands instead of MCP tools.

## Scope

### In scope

- Add MCP-disabling flags to AGENT*PROTOCOL profiles in `constants.py`
  (Claude: `--strict-mcp-config` + empty `enabledMcpjsonServers`;
  Gemini: `--allowed-mcp-server-names \_none*`; Codex: equivalent or config removal)
- Update `agent_cli.py` `_JOB_SPEC` to disable MCP for agent jobs
- Remove MCP server injection from `bin/init/setup_mcp_config.sh`
- Remove Codex MCP config injection from `install_hooks.py`
- Ensure `$TMPDIR/teleclaude_session_id` continues to be written
- End-to-end validation with Claude, Gemini, and Codex agents
- Validate orchestrator workflow: prepare → build → review → finalize
- Validate worker isolation (MCP role filtering is removed — verify telec
  equivalent or explicitly defer)

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
