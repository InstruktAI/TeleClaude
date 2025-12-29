# Mode Selector for Agent Model Variants - Implementation Plan

> **Requirements**: todos/mode-selector/requirements.md
> **Status**: 🚧 Ready to Implement
> **Created**: 2025-12-17

## Implementation Groups

**IMPORTANT**: Tasks within each group CAN be executed in parallel. Groups must be executed sequentially.

### Group 0: Research & Impact Analysis

_MUST complete before any code changes_

- [x] **SEQUENTIAL** Search for ALL usages of constants being removed:
  ```bash
  grep -r "DEFAULT_CLAUDE_COMMAND\|DEFAULT_GEMINI_COMMAND\|DEFAULT_CODEX_COMMAND\|AGENT_RESUME_TEMPLATES" --include="*.py"
  ```
  Document every file and line that imports or uses these constants.

- [x] **SEQUENTIAL** Search for ALL usages of `agent_config.command` and related patterns:
  ```bash
  grep -r "agent_config\.command\|config\.agents\[" --include="*.py"
  ```
  These are the places that may need updating for new AgentConfig fields.

- [x] **SEQUENTIAL** Search for ALL command assembly patterns:
  ```bash
  grep -r "cmd_parts\|base_cmd\|full_command.*agent\|\.command" --include="*.py"
  ```
  Every instance of manual command building must be replaced with `get_agent_command()`.

- [x] **SEQUENTIAL** Search for test fixtures using old constants:
  ```bash
  grep -r "DEFAULT_.*COMMAND\|AGENT_RESUME" tests/ --include="*.py"
  ```
  Update all test mocks and fixtures.

- [x] **SEQUENTIAL** Create `todos/mode-selector/impact-analysis.md` documenting:
  - Every file importing removed constants
  - Every location doing manual command assembly
  - Every test that needs updating
  - Checklist to verify nothing is missed

### Group 1: Config & Constants Foundation

_These tasks can run in parallel, DEPENDS on Group 0_

- [x] **PARALLEL** Update `teleclaude/config.py` - Extend `AgentConfig` dataclass with new fields:
  - `session_dir: str`
  - `log_pattern: str`
  - `model_flags: dict[str, str]`
  - `exec_subcommand: str`
  - `resume_template: str`

- [x] **PARALLEL** Update `teleclaude/config.py` - Update `DEFAULT_CONFIG["agents"]` with inline commands (see Implementation Notes for exact structure)

- [x] **PARALLEL** Update `teleclaude/config.py` - Update `_build_config()` to parse all AgentConfig fields from raw config dict

- [x] **PARALLEL** Update `teleclaude/constants.py` - Remove these exports:
  - `DEFAULT_CLAUDE_COMMAND`
  - `DEFAULT_GEMINI_COMMAND`
  - `DEFAULT_CODEX_COMMAND`
  - `AGENT_RESUME_TEMPLATES`
  - Also remove their imports from config.py

### Group 2: Core Helper Implementation

_Depends on Group 1_

- [x] **DEPENDS: Group 1** Create `get_agent_command()` helper in `teleclaude/core/agents.py` with full docstrings

Helper signature and docstring (MUST include):
```python
def get_agent_command(
    agent: str,
    mode: str = "slow",
    exec: bool = False,
    resume: bool = False,
    native_session_id: str | None = None
) -> str:
    """
    Build agent command string.

    Consolidates all agent command assembly into a single function.
    Handles both fresh starts and session resumption.

    Args:
        agent: Agent name ('claude', 'gemini', 'codex')
        mode: Model tier ('fast', 'med', 'slow'). Default 'slow' (most capable).
        exec: If True, include exec_subcommand after base command (e.g., 'exec' for Codex)
        resume: If True and no native_session_id, adds --resume flag (CLI finds last session)
        native_session_id: If provided, uses resume_template with this session ID (ignores resume flag)

    Returns:
        Assembled command string, ready for prompt to be appended.

    Command assembly order:
        - With native_session_id: resume_template.format(base_cmd=..., session_id=...)
        - Without: {base_command} {exec_subcommand?} {model_flags} {--resume?}

    Examples:
        >>> get_agent_command("claude", mode="fast")
        'claude --dangerously-skip-permissions --settings \'{"forceLoginMethod": "claudeai"}\' -m haiku'

        >>> get_agent_command("codex", mode="slow", exec=True)
        'codex --dangerously-bypass-approvals-and-sandbox --search exec -m gpt-5.2'

        >>> get_agent_command("claude", native_session_id="abc123")
        'claude --dangerously-skip-permissions --settings \'{"forceLoginMethod": "claudeai"}\' --resume abc123'
    """
```

### Group 3: Refactor Existing Command Assembly

_These tasks can run in parallel, depend on Group 2_

- [x] **PARALLEL, DEPENDS: Group 2** Refactor `teleclaude/core/command_handlers.py` - `handle_agent_start()` to use `get_agent_command()`
- [x] **PARALLEL, DEPENDS: Group 2** Refactor `teleclaude/core/command_handlers.py` - `handle_agent_resume()` to use `get_agent_command()`
- [x] **PARALLEL, DEPENDS: Group 2** Refactor `teleclaude/restart_agent.py` to use `get_agent_command()`

### Group 4: MCP Tool Integration

_These tasks can run in parallel, depend on Group 3_

- [x] **PARALLEL, DEPENDS: Group 3** Update `teleclaude/mcp_server.py` - Add `mode` parameter to `teleclaude__start_session` tool definition:
  ```python
  "mode": {
      "type": "string",
      "description": "Model tier: 'fast' (cheapest), 'med' (balanced), 'slow' (most capable). Default: slow",
      "enum": ["fast", "med", "slow"],
      "default": "slow"
  }
  ```

- [x] **PARALLEL, DEPENDS: Group 3** Update `teleclaude/mcp_server.py` - Add `mode` parameter to `teleclaude__run_agent_command` tool definition (same schema as above, only applies when starting new session)

- [x] **PARALLEL, DEPENDS: Group 3** Update `teleclaude/mcp_server.py` - Pass `mode` through method chain:
  - `teleclaude__start_session(mode="slow")` → `_start_local_session(mode)` / `_start_remote_session(mode)`
  - Mode gets passed to `handle_agent_start()` via args or metadata

- [x] **PARALLEL, DEPENDS: Group 3** Update `teleclaude/mcp_server.py` - In `teleclaude__run_agent_command()`:
  - When no `session_id` (new session): pass `mode` to `teleclaude__start_session()`
  - When `session_id` provided (existing): ignore `mode` (agent already running)

- [x] **PARALLEL, DEPENDS: Group 3** Update `teleclaude/daemon.py` - Pass mode through AGENT_START event handling to `handle_agent_start()`

### Group 5: Testing

_These tasks can run in parallel, depend on Group 4_

- [x] **PARALLEL, DEPENDS: Group 4** Create `tests/unit/test_agents.py` - Unit tests for `get_agent_command()`:
  - Test all three agents (claude, gemini, codex)
  - Test all three modes (fast, med, slow)
  - Test exec=True for codex (adds "exec" subcommand)
  - Test resume=True without session_id (adds --resume)
  - Test native_session_id (uses resume_template)
  - Test default mode is "slow"

- [x] **PARALLEL, DEPENDS: Group 4** Update `tests/unit/test_mcp_server.py` - Add tests for mode parameter:
  - `teleclaude__start_session` with mode="fast", "med", "slow"
  - `teleclaude__run_agent_command` with mode (new session)
  - `teleclaude__run_agent_command` ignores mode when session_id provided

- [x] **PARALLEL, DEPENDS: Group 4** Update `tests/unit/test_command_handlers.py` - Update for new helper:
  - `handle_agent_start()` now uses `get_agent_command()`
  - `handle_agent_resume()` now uses `get_agent_command()`
  - Verify mode is passed correctly

### Group 6: Verification & Polish

_Depends on Group 5_

- [ ] **SEQUENTIAL, DEPENDS: Group 5** Verify NO unused imports or variables:
  ```bash
  # Check for any remaining references to removed constants
  grep -r "DEFAULT_CLAUDE_COMMAND\|DEFAULT_GEMINI_COMMAND\|DEFAULT_CODEX_COMMAND\|AGENT_RESUME_TEMPLATES" --include="*.py"
  # Should return NOTHING
  ```

- [ ] **SEQUENTIAL** Verify NO manual command assembly remains outside helper:
  ```bash
  grep -r "cmd_parts\|\.command" teleclaude/ --include="*.py" | grep -v "get_agent_command\|AgentConfig\|#"
  # Review any hits - should only be in get_agent_command() or AgentConfig definition
  ```

- [ ] **SEQUENTIAL** Run `make format && make lint` - Fix ALL warnings, especially:
  - Unused imports
  - Unused variables
  - Import errors

- [ ] **SEQUENTIAL** Run `make test` - ALL tests must pass

### Group 7: Review & Finalize

_These tasks must run sequentially. Each follows checkbox discipline: mark in-progress → do work → mark complete → commit._

- [ ] **SEQUENTIAL** Review created → produces `review-findings.md`
- [ ] **SEQUENTIAL** Review feedback handled → fixes applied from findings

### Group 8: Merge & Deploy

_These tasks must run sequentially. Each follows checkbox discipline: mark in-progress → do work → mark complete → commit._

**Pre-merge (in worktree, commit before merge):**

- [ ] **SEQUENTIAL** Tests pass locally (`make test`)
- [ ] **SEQUENTIAL** All Groups 1-7 complete (ready to merge)

**Post-merge (on main, commit after each):**

- [ ] **SEQUENTIAL** Merged to main and pushed
- [ ] **SEQUENTIAL** Deployment verified on all computers
- [ ] **SEQUENTIAL** Worktree cleaned up
- [ ] **SEQUENTIAL** Roadmap item marked complete (`[x]` in `todos/roadmap.md`)

## Task Markers

- `**PARALLEL**`: Can execute simultaneously with other PARALLEL tasks in same group
- `**DEPENDS: GroupName**`: Requires all tasks in GroupName to complete first
- `**SEQUENTIAL**`: Must run after previous task in group completes

## Implementation Notes

### Key Design Decisions

1. **Default mode is "slow"** - Most capable model by default, users opt-in to faster/cheaper
2. **exec_subcommand placement** - After base command, before model flags (Codex requires this)
3. **Helper handles both start and resume** - `native_session_id` presence determines which path
4. **Config-driven** - All agent settings in DEFAULT_CONFIG, no separate constants
5. **Mode only applies to new sessions** - When `session_id` provided to `run_agent_command`, mode is ignored

### Exact Config Structure (DEFAULT_CONFIG["agents"])

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
        "command": "gemini  -i",
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

### AgentConfig Dataclass Update

```python
@dataclass
class AgentConfig:
    """Configuration for a specific AI agent."""
    command: str
    session_dir: str
    log_pattern: str
    model_flags: dict[str, str]      # {"fast": "-m haiku", "med": "-m sonnet", "slow": "-m opus"}
    exec_subcommand: str             # "" for claude/gemini, "exec" for codex
    resume_template: str             # "{base_cmd} --resume {session_id}" or "{base_cmd} resume {session_id}"
```

### Command Assembly Order

**Fresh start (no native_session_id)**:
```
{base_command} {exec_subcommand?} {model_flags} {--resume?} {prompt}
```

**Resume with explicit session (native_session_id provided)**:
```
resume_template.format(base_cmd=base_command, session_id=native_session_id)
```

### Helper Logic

```python
def get_agent_command(agent, mode="slow", exec=False, resume=False, native_session_id=None):
    agent_config = config.agents[agent]
    base_cmd = agent_config.command

    if native_session_id:
        # Explicit resume - use template, ignore other flags
        return agent_config.resume_template.format(
            base_cmd=base_cmd,
            session_id=native_session_id
        )

    # Build command parts
    parts = [base_cmd]

    if exec and agent_config.exec_subcommand:
        parts.append(agent_config.exec_subcommand)

    # Add model flag for selected mode
    model_flag = agent_config.model_flags.get(mode)
    if model_flag:
        parts.append(model_flag)

    if resume:
        parts.append("--resume")

    return " ".join(parts)
```

### Potential Blockers

- Breaking changes to constants.py imports (search for all usages)
- Test fixtures may depend on old constant names

### Files to Create/Modify

**New Files**:
- `tests/unit/test_agents.py` - Tests for `get_agent_command()` helper

**Modified Files**:
- `teleclaude/config.py` - AgentConfig expansion, DEFAULT_CONFIG update, _build_config update
- `teleclaude/constants.py` - Remove DEFAULT_*_COMMAND and AGENT_RESUME_TEMPLATES
- `teleclaude/core/agents.py` - Add `get_agent_command()` helper
- `teleclaude/core/command_handlers.py` - Refactor handle_agent_start(), handle_agent_resume()
- `teleclaude/restart_agent.py` - Refactor to use helper
- `teleclaude/mcp_server.py` - Add mode parameter to tools and methods
- `teleclaude/daemon.py` - Pass mode through event handling
- `tests/unit/test_mcp_server.py` - Add mode tests
- `tests/unit/test_command_handlers.py` - Update for new helper

## Success Verification

Before marking complete, verify all requirements success criteria:

- [ ] `mode` parameter available on `teleclaude__start_session` and `teleclaude__run_agent_command` tools
- [ ] Model flags correctly applied for all three agents (claude, gemini, codex) and all three modes (fast, med, slow)
- [ ] Omitting mode defaults to `slow` (most capable model)
- [ ] Invalid mode values return clear error message
- [ ] `get_agent_command()` helper used by `handle_agent_start()`, `handle_agent_resume()`, `restart_agent.py`
- [ ] Codex commands include "exec" subcommand in correct position
- [ ] DEFAULT_*_COMMAND and AGENT_RESUME_TEMPLATES removed from constants.py
- [ ] Unit tests cover mode parameter, exec_subcommand, resume, and helper function
- [ ] Zero regressions in existing functionality
- [ ] All linters and tests pass
- [ ] Code formatted and linted

## Completion

When all Group 8 checkboxes are complete, this item is done. The roadmap update is the final checkbox in Group 8.

---

**Usage with /next-work**: The next-work command will execute tasks group by group, running PARALLEL tasks simultaneously when possible.
