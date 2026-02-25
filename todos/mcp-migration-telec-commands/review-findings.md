# Review Findings: mcp-migration-telec-commands

## Critical

1. **R2-F1 — `POST /sessions/run` no longer preserves worker-command invariants, so worker-role enforcement can be bypassed.**
   - Evidence:
     - The new route accepts all slash commands without worker-command slug validation and never extracts/propagates `working_slug`: `teleclaude/api_server.py:903`, `teleclaude/api_server.py:914`.
     - The daemon derives `system_role` from `session_metadata.system_role` or `working_slug`; otherwise it treats the caller as non-worker: `teleclaude/api/auth.py:33`.
     - Session creation only persists `working_slug` when it is provided via command/channel metadata: `teleclaude/core/command_handlers.py:272`, `teleclaude/core/command_handlers.py:381`.
     - The existing MCP baseline path (`teleclaude__run_agent_command`) explicitly enforces slug for worker commands and forwards `working_slug`: `teleclaude/mcp/handlers.py:591`.
   - Repro evidence:
     - Local probe returned `200` for `/sessions/run` with `{"command":"/next-build","args":"","project":"..."}` (worker command without slug).
   - Impact:
     - Role checks tied to worker identity can be skipped for sessions started through `telec sessions run`, and invalid worker-dispatch invocations are accepted instead of failing fast.

## Important

1. **R2-F2 — `POST /sessions/{session_id}/widget` silently reports success when delivery fails.**
   - Evidence:
     - Endpoint catches all send failures, logs a warning, and still returns `{"status":"success"}`: `teleclaude/api_server.py:1075`.
   - Repro evidence:
     - With `self.client.send_message` forced to raise, endpoint still returned `200` with success payload.
   - Impact:
     - Callers receive false-positive success, which hides delivery failures and breaks reliability of automation depending on this response.

2. **R2-F3 — New CLI help tests lock narrative wording instead of behavior.**
   - Evidence:
     - Exact prose assertions on help copy: `tests/integration/test_telec_cli_commands.py:186`, `tests/integration/test_telec_cli_commands.py:195`.
   - Impact:
     - Brittle tests fail on editorial wording changes without behavioral regression, violating the testing policy guardrail against prose-lock assertions.

## Suggestions

1. Convert invalid-agent errors in `/agents/{agent}/status` to `HTTP 400` instead of uncaught `ValueError` bubbling as server error:
   - `teleclaude/api_server.py:1324`
   - `teleclaude/core/agents.py:33`

2. `telec sessions list --closed` is exposed in CLI/help but not consumed by the API route; either implement endpoint support or remove the flag surface:
   - `teleclaude/cli/tool_commands.py:86`
   - `teleclaude/api_server.py:382`

## Paradigm-Fit Assessment

- Data flow: `sessions/run` diverges from the established `run_agent_command` path semantics (worker slug extraction/propagation), creating a parallel code path with weaker invariants.
- Component reuse: route correctly reuses command mapping/session creation plumbing, but omitted metadata propagation (`working_slug`) breaks the intended enforcement chain.
- Pattern consistency: error-path behavior is inconsistent (`send_result` fails loud/fallback; `render_widget` fails silent), which violates established fail-fast boundary behavior.

## Manual Verification Evidence

- Targeted test run:
  - `pytest -q tests/unit/test_api_auth.py tests/unit/test_api_route_auth.py tests/unit/test_api_server.py tests/unit/test_api_client.py tests/unit/test_telec_cli.py tests/integration/test_telec_cli_commands.py`
  - Result: `109 passed, 1 skipped`
- Targeted runtime probes:
  - Verified `/sessions/run` accepts `/next-build` without slug.
  - Verified `/sessions/run` generated command metadata lacks `working_slug`.
  - Verified `/sessions/{id}/widget` returns success despite forced adapter send failure.

## Fixes Applied

- **R2-F1**
  - Fix: Enforced worker lifecycle slug requirements in `POST /sessions/run` and propagated `working_slug` via channel metadata to preserve worker role derivation.
  - Commit: `543ed887`
- **R2-F2**
  - Fix: Converted widget delivery failures from silent success to explicit HTTP 500 failures with error diagnostics.
  - Commit: `f4145f99`
- **R2-F3**
  - Fix: Replaced prose-locked CLI help assertions with behavior-focused interface assertions (usage shape, flags, examples).
  - Commit: `b69ac067`

## Verdict

REQUEST CHANGES
