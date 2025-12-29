# Mode Selector for Agent Model Variants

> **Created**: 2025-12-17
> **Status**: 📝 Requirements

## Problem Statement

Currently, `teleclaude__start_session` and `teleclaude__run_agent_command` MCP tools accept an `agent` parameter (claude/gemini/codex) but always use the agent's default model. Users cannot select between fast, medium, and slow model variants without manually modifying agent commands. This limits flexibility in balancing speed vs. capability for different tasks.

## Goals

**Primary Goals**:

- Add `mode` parameter to MCP tools that accept `agent` parameter (`start_session`, `run_agent_command`)
- Support three modes: `fast`, `med`, `slow` mapping to agent-specific model flags
- Default mode is `slow` (most capable model) when not specified
- Model flag mapping defined in agent config (`config.agents[name].model_flags`)
- **Consolidate command assembly** into single helper: `get_agent_command(agent, mode="slow", exec=False)`

**Secondary Goals**:

- Validate mode against known values, reject invalid modes with clear error
- Remove duplicate command assembly logic from multiple files

## Non-Goals

- Adding mode selection to Telegram adapter commands (MCP-only scope)
- Custom model specification outside the three predefined modes
- Per-computer model configuration

## User Stories / Use Cases

### Story 1: Master AI Delegates Quick Task

As a master AI orchestrator, I want to start a session with `mode="fast"` so that simple, routine tasks complete quickly with lower cost.

**Acceptance Criteria**:

- [ ] `teleclaude__start_session(..., mode="fast")` starts session with fast model
- [ ] For Claude: adds `-m haiku` flag (from `config.agents.claude.model_flags.fast`)
- [ ] For Gemini: adds `-m gemini-2.5-flash-lite` flag
- [ ] For Codex: adds `-m gpt-5.1-codex-mini` flag

### Story 2: Complex Task Requires Powerful Model

As a developer, I want to start a session with `mode="slow"` so that complex architectural tasks use the most capable model.

**Acceptance Criteria**:

- [ ] `teleclaude__start_session(computer="macbook", ..., mode="slow")` starts session with slow/powerful model
- [ ] For Claude: adds `-m opus` flag
- [ ] For Gemini: adds `-m gemini-3-pro-preview` flag
- [ ] For Codex: adds `-m gpt-5.2` flag

### Story 3: Default Mode Uses Slow (Most Capable)

As a user, I want sessions without explicit `mode` to default to `slow` so I get the most capable model by default.

**Acceptance Criteria**:

- [ ] `teleclaude__start_session(...)` without `mode` defaults to `slow` mode
- [ ] Default adds appropriate model flag (e.g., `-m opus` for Claude)
- [ ] Existing tests updated to reflect new default behavior

### Story 4: Run Command with Mode

As an orchestrator, I want to use `teleclaude__run_agent_command` with a mode so that I can start slash command sessions with specific model tiers.

**Acceptance Criteria**:

- [ ] `teleclaude__run_agent_command(computer="local", command="next-work", agent="claude", mode="med")` starts new session with medium model
- [ ] Mode only applies when starting new session (no session_id provided)
- [ ] When session_id provided (existing session), mode parameter is ignored (agent already running)

### Story 5: Consolidated Command Assembly

As a maintainer, I want a single helper function for agent command assembly so that command logic is not scattered across multiple files.

**Acceptance Criteria**:

- [ ] New helper: `get_agent_command(agent: str, mode: str = "slow", exec: bool = False, resume: bool = False, native_session_id: str | None = None) -> str`
- [ ] With `native_session_id`: returns resume command using resume_template (ignores `resume` flag)
- [ ] Without `native_session_id` + `resume=True`: adds `--resume` flag (CLI finds last session)
- [ ] Without `native_session_id` + `resume=False`: fresh start command
- [ ] Base format: `{base_command} {exec_subcommand?} {model_flags} {resume_flag?}`
- [ ] exec_subcommand (e.g., "exec" for Codex) placed AFTER base command, BEFORE flags
- [ ] If agent has no exec_subcommand, it's omitted (empty string)
- [ ] Prompt can be appended to returned command
- [ ] Helper must have explicit docstrings documenting all params and return value
- [ ] Refactor `handle_agent_start()` and `handle_agent_resume()` to use helper
- [ ] AGENT_RESUME_TEMPLATES moved into config as `resume_template`

## Technical Constraints

- Command assembly order: `{base_command} {exec_subcommand?} {model_flags} {resume_flag?} {prompt}`
- With `native_session_id`: uses `resume_template` format instead (e.g., `{base_cmd} --resume {session_id}`)
- exec_subcommand is optional per agent (e.g., Codex has "exec", others have "")
- Model flags stored in `config.agents[name].model_flags` dict
- `AgentConfig` dataclass needs: `model_flags: dict[str, str]`, `exec_subcommand: str`
- `_build_config()` needs to parse new AgentConfig fields
- Helper function `get_agent_command()` placed in `teleclaude/core/agents.py`
- Implementation must flow through: MCP tool → method → local/remote handler → `handle_agent_start`
- Remote session flow uses Redis transport - mode must be passed through command string

## Success Criteria

How will we know this is successful?

- [ ] `mode` parameter available on `teleclaude__start_session` and `teleclaude__run_agent_command` tools
- [ ] Model flags correctly applied for all three agents (claude, gemini, codex) and all three modes (fast, med, slow)
- [ ] Omitting mode defaults to `slow` (most capable model)
- [ ] Invalid mode values return clear error message
- [ ] `get_agent_command()` helper used by `handle_agent_start()`, `handle_agent_resume()`, `restart_agent.py`
- [ ] Codex commands include "exec" subcommand in correct position
- [ ] DEFAULT\_\*\_COMMAND and AGENT_RESUME_TEMPLATES removed from constants.py
- [ ] Unit tests cover mode parameter, exec_subcommand, resume, and helper function
- [ ] Zero regressions in existing functionality

## Open Questions

None - config structure defined (commands inlined, no separate constants):

```python
"agents": {
    "claude": {
        "command": 'claude --dangerously-skip-permissions --settings \'{"forceLoginMethod": "claudeai"}\'',
        "session_dir": "~/.claude/sessions",
        "log_pattern": "*.jsonl",
        "model_flags": {"fast": "-m haiku", "med": "-m sonnet", "slow": "-m opus"},
        "exec_subcommand": "",
        "resume_template": "{base_cmd} --resume {session_id}",
    },
    "gemini": {
        "command": "gemini --yolo -i",
        "session_dir": "~/.gemini/sessions",
        "log_pattern": "*.jsonl",
        "model_flags": {"fast": "-m gemini-2.5-flash-lite", "med": "-m gemini-2.5-flash", "slow": "-m gemini-3-pro-preview"},
        "exec_subcommand": "",
        "resume_template": "{base_cmd} --resume {session_id}",
    },
    "codex": {
        "command": "codex --dangerously-bypass-approvals-and-sandbox --search",
        "session_dir": "~/.codex/sessions",
        "log_pattern": "*.jsonl",
        "model_flags": {"fast": "-m gpt-5.1-codex-mini", "med": "-m gpt-5.1-codex", "slow": "-m gpt-5.2"},
        "exec_subcommand": "exec",  # placed after command, before flags
        "resume_template": "{base_cmd} resume {session_id}",  # codex uses subcommand, not flag
    },
}
```

## References

- Affected files:
  - `teleclaude/config.py` - inline commands + add `model_flags`, `exec_subcommand`, `resume_template` to AgentConfig
  - `teleclaude/constants.py` - remove DEFAULT\_\*\_COMMAND and AGENT_RESUME_TEMPLATES
  - `teleclaude/core/agents.py` - add `get_agent_command()` helper (handles start + resume)
  - `teleclaude/mcp_server.py` - add mode parameter to tools and method implementations
  - `teleclaude/core/command_handlers.py` - refactor `handle_agent_start()` + `handle_agent_resume()` to use helper
  - `teleclaude/restart_agent.py` - refactor to use `get_agent_command()` helper
  - `teleclaude/daemon.py` - pass mode through AGENT_START event handling
  - `tests/unit/test_mcp_server.py` - add mode parameter tests
  - `tests/unit/test_command_handlers.py` - add mode handling tests
  - `tests/unit/test_agents.py` - new tests for `get_agent_command()` helper
- Architecture doc: [docs/architecture.md](../../docs/architecture.md)
