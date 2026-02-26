# Review Findings: agent-availability-enforcement-migration

## Critical

- Fail-open availability lookup in canonical resolver allows unavailable/degraded agents to route as available when DB lookup errors.
  - Evidence:
    - `teleclaude/core/agent_routing.py:67-77` catches all exceptions from `db.get_agent_availability(...)` and returns `"available"`.
    - That status is consumed by both explicit and implicit routing (`teleclaude/core/agent_routing.py:113-131`, `teleclaude/core/agent_routing.py:146-150`).
  - Concrete behavior trace:
    - Probe run:
      - Set config with enabled `claude`
      - Stub `db.get_agent_availability` to raise `RuntimeError("db down")`
      - Call `resolve_routable_agent("claude", source="probe")`
    - Observed output:
      - `agent routing availability lookup failed; assuming available`
      - returned agent: `claude`
  - Why this matters:
    - Violates the migration goal and FR1/FR3/FR4 fail-closed enforcement for unavailable/degraded agents.
    - Reintroduces bypass behavior during transient DB failures (exactly where deterministic policy enforcement is needed most).
  - Confidence: 99

## Important

- None.

## Suggestions

- Add a targeted unit test asserting fail-closed behavior when availability lookup raises in `resolve_routable_agent(...)` for both explicit and implicit selection.
- If a temporary fail-open policy is intentionally required, gate it explicitly behind a named config flag and emit high-signal error telemetry; do not make fail-open the unconditional default.

## Paradigm-Fit Assessment

- Data flow: Aligned. Routing policy is centralized in `teleclaude/core/agent_routing.py` and reused by API, daemon, and command handlers.
- Component reuse: Aligned. Shared parser (`split_leading_agent_token`) removes prior parsing drift across mapper/API/daemon.
- Pattern consistency: Mostly aligned, but the resolver currently violates fail-fast policy by silently converting DB failures into availability success.

## Manual Verification Evidence

- Targeted tests run:
  - `uv run pytest -q tests/unit/test_agent_routing.py tests/unit/test_api_server.py tests/unit/test_command_handlers.py tests/unit/test_command_mapper.py tests/unit/test_cron_runner_job_contract.py tests/unit/test_daemon.py tests/unit/test_daemon_independent_jobs.py tests/unit/test_discord_adapter.py`
  - Result: `278 passed, 1 skipped`.
- Behavioral probe run:
  - `resolve_routable_agent("claude", source="probe")` with `db.get_agent_availability` forced to raise `RuntimeError("db down")`
  - Result: resolver logged fallback and returned `claude` (fail-open confirmed).

## Verdict

REQUEST CHANGES

## Fixes Applied

- Issue: Critical - fail-open availability lookup in canonical resolver returned `available` on DB errors.
- Fix: Updated `teleclaude/core/agent_routing.py` to fail closed by treating availability lookup exceptions as `unavailable`, and added targeted explicit/implicit regression tests in `tests/unit/test_agent_routing.py`.
- Commit: `f4819444509bd3db4d46d5d60f81a2abfe378eae`
