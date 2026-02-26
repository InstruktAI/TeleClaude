# Review Findings — agent-config-driven-selection-contract

## Manual Verification Evidence

- Targeted contract tests executed:
  `uv run pytest -q tests/unit/test_agent_config_loading.py tests/unit/test_agents.py tests/unit/test_command_mapper.py tests/unit/test_api_server.py tests/unit/test_command_handlers.py tests/unit/test_tui_modal.py tests/unit/test_next_machine_demo.py tests/unit/test_agent_guidance.py tests/unit/cli/test_tool_commands.py`
  Result: `214 passed, 1 skipped`.
- Lint/type checks executed:
  `make lint`
  Result: `ruff check` and `pyright` passed.
- Manual CLI verification executed:
  `TELECLAUDE_CONFIG_PATH=<invalid-config> uv run python -m teleclaude.cli.telec todo demo validate test-slug --project-root <tmp>`
  Result: exits 0 with `Validation passed`.
- Concrete disabled-agent bypass trace (API):
  With `TELECLAUDE_CONFIG_PATH=tests/integration/config.yml` (`codex.enabled=false`), a `POST /sessions` with `{"auto_command":"codex_resume abc123"}` returns `200` and calls `create_session` instead of returning `400`.

## Critical

- None.

## Important

1. API `create_session` auto-command validation misses `*_resume` aliases, allowing disabled-agent bypass of pre-dispatch rejection.
   - Severity: Important
   - Confidence: 98
   - Files:
     - `teleclaude/api_server.py:563`
     - `teleclaude/api_server.py:570`
     - `teleclaude/core/command_mapper.py:239`
     - `tests/unit/test_api_server.py:405`
   - Why this matters:
     The route validates `agent`, direct agent commands, and `agent*` forms, but not `claude_resume|gemini_resume|codex_resume`. Those aliases are accepted and mapped later, so a disabled agent can pass create-time checks and still produce a successful session creation response.
   - Requirement impact:
     - Violates R3 (reject disabled agent selection before dispatch in session-creation entrypoints).
     - Fails acceptance criterion 4 for deterministic disabled-agent rejection on API surface.
   - Fix direction:
     Extend `request.auto_command` validation in `create_session` to include `*_resume` aliases (or centralize command-to-agent extraction in one helper shared with `CommandMapper`), and add a regression test asserting `codex_resume` returns `400` when `codex` is disabled.

## Suggestions

1. Add explicit API tests for `auto_command` aliases: `claude_resume`, `gemini_resume`, `codex_resume`.
2. Replace ad-hoc command-name branching in `create_session` with a single parser/helper that extracts target agent for all command syntaxes.

## Paradigm-Fit Assessment

- Data flow: Mostly aligned with centralized helpers (`assert_agent_enabled`, `get_enabled_agents`), but auto-command alias parsing in API duplicates command-shape knowledge and diverges from mapper behavior.
- Component reuse: Good reuse across API/core/TUI paths; this alias branch is the remaining non-reused seam.
- Pattern consistency: Fail-closed behavior is consistent for direct `agent` paths; inconsistent for `*_resume` aliases.

## Verdict

REQUEST CHANGES
