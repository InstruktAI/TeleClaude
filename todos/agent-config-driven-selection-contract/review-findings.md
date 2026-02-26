# Review Findings — agent-config-driven-selection-contract

## Manual Verification Evidence

- Targeted contract tests executed:
  `uv run pytest -q tests/unit/test_agent_config_loading.py tests/unit/test_agents.py tests/unit/test_command_mapper.py tests/unit/test_api_server.py tests/unit/test_command_handlers.py tests/unit/test_tui_modal.py tests/unit/test_next_machine_demo.py tests/unit/test_agent_guidance.py`
  Result: `212 passed, 1 skipped`.
- Lint/type checks executed:
  `make lint`
  Result: `ruff check` and `pyright` passed.
- Concrete value trace for fallback path:
  - `handle_sessions_run(['--command','/next-build','--project','/tmp/project'])` builds request body with `"agent": "claude"` ([teleclaude/cli/tool_commands.py:304](teleclaude/cli/tool_commands.py:304)).
  - `RunSessionRequest(..., agent='claude')` includes `"agent"` in `model_fields_set`, so API fallback logic is skipped ([teleclaude/api_server.py:1014](teleclaude/api_server.py:1014)).
  - If `claude` is disabled and `gemini` is enabled, the request is rejected at `assert_agent_enabled("claude")` instead of selecting enabled fallback ([teleclaude/api_server.py:1016](teleclaude/api_server.py:1016)).

## Critical

- None.

## Important

1. `telec sessions run` default request still hardcodes `claude`, defeating enabled-agent fallback policy.
   - Severity: Important
   - Confidence: 98
   - Files:
     - `teleclaude/cli/tool_commands.py:304`
     - `teleclaude/api_server.py:1014`
   - Why this matters:
     API-side fallback (`first enabled agent`) only activates when the `agent` field is omitted. The CLI currently always sends `agent=claude`, so with `claude` disabled and another agent enabled, dispatch is rejected instead of selecting an enabled default. This violates the requirement that fallback pickers be config-driven and consistent.
   - Requirement impact:
     - Violates R3 fallback-picker implication.
     - Undermines acceptance criterion 3 for default dispatch surfaces.
   - Fix direction:
     In `handle_sessions_run`, omit `"agent"` from the request body unless `--agent` was explicitly provided.

## Suggestions

1. Add a unit test for `handle_sessions_run` that asserts `agent` is absent from request JSON when `--agent` is not provided.
2. Add an API integration test proving `/sessions/run` picks first enabled agent when client omits `agent`.

## Paradigm-Fit Assessment

- Data flow: Mostly aligned, but CLI boundary still injects adapter-specific default (`claude`) instead of using centralized policy-driven fallback.
- Component reuse: Good reuse of `assert_agent_enabled` and `get_enabled_agents` in core/API.
- Pattern consistency: Fail-closed behavior is consistent in most paths; this CLI caller remains an outlier.

## Fixes Applied

- `Important-1`: Removed hardcoded `"agent": "claude"` default from `handle_sessions_run`, so CLI omits `agent` unless `--agent` is explicitly provided and API fallback can select the first enabled agent.
  Added `tests/unit/cli/test_tool_commands.py` coverage for both default-omission and explicit-agent pass-through behavior.
  Commit: `6772351f`.

## Verdict

REQUEST CHANGES
