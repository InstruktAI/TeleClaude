# Mode Selector Impact Analysis

Date: 2025-12-17  
Scope: Identify all usages of removed constants and manual agent command assembly points.

## Constants to remove

- `teleclaude/constants.py` defines `DEFAULT_CLAUDE_COMMAND`, `DEFAULT_GEMINI_COMMAND`, `DEFAULT_CODEX_COMMAND`, `AGENT_RESUME_TEMPLATES` (all slated for removal).
- `teleclaude/config.py` imports the three DEFAULT_* constants and uses them in `DEFAULT_CONFIG["agents"][*.command]`.
- `teleclaude/core/command_handlers.py` imports `AGENT_RESUME_TEMPLATES` and uses it when resuming agents.
- `teleclaude/restart_agent.py` imports `AGENT_RESUME_TEMPLATES` and uses it to build restart commands.

## Manual command assembly spots

- `teleclaude/core/command_handlers.py`
  - `handle_agent_start`: builds `cmd_parts` list from `agent_config.command` plus user args.
  - `handle_agent_resume`: builds command using `agent_config.command` and `AGENT_RESUME_TEMPLATES`.
- `teleclaude/restart_agent.py`
  - `restart_agent_in_session`: builds command from `agent_config.command` and `AGENT_RESUME_TEMPLATES`.

## Tests/fixtures referencing old constants or assembly

- `tests/unit/test_command_handlers.py`
  - `test_handle_agent_start_executes_command_with_args` asserts assembled command contains `claude` and user args.
  - `test_handle_agent_start_executes_command_without_extra_args_if_none_provided` asserts `codex` base command used.
  - `test_handle_agent_resume_executes_command_with_session_id_from_db` expects resume command containing `--resume` and session id.
- `tests/unit/test_mcp_server.py`
  - Start-session tests assume AGENT_START args structure; will need updates for new mode plumbing once added.

## Checklist

- [ ] Remove DEFAULT_*_COMMAND and AGENT_RESUME_TEMPLATES from codebase.
- [ ] Replace all manual command assembly with `get_agent_command()`.
- [ ] Update tests noted above to align with new helper and mode behavior.
