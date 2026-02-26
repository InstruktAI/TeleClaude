# Review Findings: agent-availability-enforcement-migration

## Critical

- None.

## Important

- `agent` argument parsing now silently reclassifies unknown first tokens as "no explicit agent", which bypasses explicit unknown-agent rejection and routes to implicit default selection instead.
  - Evidence:
    - `teleclaude/core/command_mapper.py:44-50` and call sites at `:153-159`, `:223-229`, `:386-393`
    - `teleclaude/api_server.py:555-562` and `:591-597`
    - `teleclaude/daemon.py:1025-1031` and `:1053-1061`
  - Concrete behavior trace:
    - `CommandMapper.map_api_input("agent", {"args": ["claud"]}, ...)` produces `StartAgentCommand(agent_name=None, args=["claud"])`, so `"claud"` is no longer validated as an explicit agent target.
    - `TeleClaudeDaemon._execute_auto_command(..., "agent claud")` calls `resolve_routable_agent(None, ...)` and launches a default agent with `args=["claud"]` (observed), instead of rejecting `"claud"` as unknown.
  - Why this matters:
    - Violates FR1 explicit requested-agent validation and fail-closed intent for invalid explicit agent selections.
    - Can launch a different agent than requested, turning an invalid target into unintended execution.
  - Confidence: 97

## Suggestions

- Add regression tests for explicit-invalid first-token cases across surfaces:
  - mapper: `agent claud` should surface unknown-agent rejection path
  - daemon auto-command: `agent claud` should return error, not success
  - API `/sessions` auto-command validation: `agent claud` should be rejected
- Centralize "explicit agent token extraction" in one shared helper to avoid parsing drift between mapper/API/daemon.

## Paradigm-Fit Assessment

- Data flow: Mostly aligned. New routing policy is centralized in `core/agent_routing.py` and used by API/daemon/handlers.
- Component reuse: Partial violation. Agent-token parsing is duplicated in mapper, API server, and daemon, which caused semantic drift.
- Pattern consistency: Core policy enforcement is consistent, but explicit-vs-implicit selection semantics are inconsistent at parsing boundaries.

## Manual Verification Evidence

- Performed targeted behavioral validation with concrete values:
  - `uv run pytest -q tests/unit/test_agent_routing.py tests/unit/test_command_mapper.py tests/unit/test_daemon.py -k 'implicit_agent_selection or command_mapper or agent_routing'` -> passed (`20 passed`).
  - Direct runtime probe confirmed `agent claud` in daemon auto-command routes via implicit selection (`resolve_routable_agent(None, ...)`) and returns success.

## Fixes Applied

- Issue: Unknown first token in `agent` parsing was reclassified as implicit selection across mapper/API/daemon.
  - Fix: Added shared parsing helper (`split_leading_agent_token`) that preserves known thinking-mode implicit behavior while treating all other non-empty first tokens as explicit agent candidates for routing validation; wired it into mapper/API/daemon and added regression tests for `agent claud`.
  - Commit: `eb57bc77`

## Verdict

REQUEST CHANGES
