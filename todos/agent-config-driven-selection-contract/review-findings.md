# Review Findings — agent-config-driven-selection-contract

## Manual Verification Evidence

- Targeted unit tests run:
  `uv run pytest -q tests/unit/test_agent_config_loading.py tests/unit/test_agent_guidance.py tests/unit/test_agents.py tests/unit/test_api_server.py tests/unit/test_command_handlers.py tests/unit/test_config_experiments_overlay.py tests/unit/test_config_working_dir.py tests/unit/test_next_machine_demo.py tests/unit/test_tui_modal.py`
  Result: `199 passed, 1 skipped`.
- Demo contract validation run:
  `uv run python -m teleclaude.cli.telec todo demo validate agent-config-driven-selection-contract --project-root .`
  Result: `Validation passed: 5 executable block(s) found`.
- Concrete behavior trace for API enforcement gap:
  `POST /sessions` with `{"agent":"codex","auto_command":"agent codex slow"}` returns `200`, and `assert_agent_enabled()` is not called.

## Critical

- None.

## Important

1. Disabled-agent policy is bypassed in API session creation when `auto_command` is provided.
   - File: `teleclaude/api_server.py:559`
   - File: `teleclaude/api_server.py:594`
   - Why this matters: The new enforcement only runs inside `if not request.auto_command`. A caller can set a disabled agent in `auto_command` and still receive a successful session-creation response, which violates the fail-closed selection contract for API entry points.
   - Requirement impact: Violates `R3` (enforce before dispatch in API session creation path) and weakens `R1/R6` operator expectations for deterministic rejection.
   - Fix direction: Validate agent policy even when `auto_command` is present. At minimum, if `request.agent` is set, always call `assert_agent_enabled()`. Prefer parsing/guarding `agent*` auto-commands as well.

2. Command mapping still has a fail-open fallback to `"claude"` when no enabled agents are available.
   - File: `teleclaude/core/command_mapper.py:41`
   - Why this matters: `_default_agent_name()` returns `"claude"` when `get_enabled_agents()` is empty instead of raising a blocking configuration error. That reintroduces fallback behavior the contract is trying to remove.
   - Requirement impact: Conflicts with `R3` fallback policy and the non-functional “no silent fallback” rule.
   - Fix direction: Replace the fallback with an explicit error (`ValueError` with actionable `config.yml:agents` guidance) and handle it at boundary adapters.

## Suggestions

1. Add API regression coverage for `POST /sessions` with `auto_command` plus disabled agent to ensure 4xx rejection and no dispatch call.
2. Add command-mapper coverage for empty enabled-agent sets to assert fail-closed behavior (no implicit `"claude"` fallback).
3. TUI behavior was validated via unit tests, but interactive/manual TUI verification was not feasible in this review shell.

## Paradigm-Fit Assessment

- Data flow: Mostly aligned (policy helper usage expanded), but API `auto_command` path bypasses policy at the boundary.
- Component reuse: Good reuse of centralized helpers (`assert_agent_enabled`, `get_enabled_agents`, `get_known_agents`).
- Pattern consistency: Improved in most dispatch paths, but fail-open mapper default is inconsistent with the new fail-closed contract.

## Fixes Applied

1. Issue: Disabled-agent policy bypass in `POST /sessions` when `auto_command` is supplied.
   Fix: Enforced policy validation before dispatch for explicit `request.agent` and parsed `agent*`/direct-agent `auto_command` targets; added API regression tests for both bypass variants.
   Commit: `45c56309`

2. Issue: Command mapper fail-open fallback to `"claude"` when no enabled agents exist.
   Fix: Replaced fallback with explicit fail-closed `ValueError` carrying actionable `config.yml:agents` guidance; added regression coverage for API agent mapping with empty enabled-agent sets.
   Commit: `a9c17115`

## Verdict

REQUEST CHANGES
