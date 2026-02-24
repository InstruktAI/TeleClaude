# Requirements — agent-config-driven-selection-contract

## Problem

Agent availability and selection are currently inconsistent across the system:

- `config.yml` missing `agents:` still allows agent usage via implicit defaults.
- Guidance output can show empty per-agent lines with no actionable signal.
- Multiple code paths hardcode `"claude" | "gemini" | "codex"` lists.
- Enable/disable checks are not consistently enforced in dispatch/start paths.

This creates a contract mismatch between configuration, orchestrator guidance, and runtime behavior.

## Goal

Make agent selection fully configuration-driven and fail-closed:

1. `config.yml` must be the leading source of which agents are selectable.
2. Missing/invalid agent configuration must fail early with clear feedback.
3. All selection/dispatch surfaces must enforce enabled-agent policy consistently.
4. Agent identifiers must be centralized via constants/helpers, not string sprawl.

## In Scope

- Configuration contract and validation for `agents`.
- Runtime helper APIs for known agents vs enabled agents.
- Enforcement in orchestrator/dispatch/session start paths.
- TUI/API behavior for zero-enabled and disabled agents.
- Guidance output quality for agent selection.
- Tests covering fail-closed behavior and surface consistency.

## Out of Scope

- Adding new agent providers.
- Reworking model-tier semantics (`fast|med|slow`) beyond policy checks.
- Refactoring unrelated adapter routing logic.

## Functional Requirements

### R1. Config is authoritative

- `config.yml` must include an explicit `agents` section.
- `agents` must include at least one enabled agent.
- Startup/load must fail with a clear error if:
  - `agents` section is missing.
  - all agents are disabled.
  - unknown agent keys are present.

### R2. Centralized agent identifiers and policy

- Introduce one canonical source for known agent IDs and policy helpers.
- Eliminate ad-hoc hardcoded lists of agent names in runtime selection/dispatch code.
- Provide centralized helpers for:
  - known agents
  - enabled agents
  - `is_agent_enabled(agent)`
  - assertion/error helpers with user-facing messages

### R3. Enforced selection contract

All user- and worker-facing entry points must reject disabled agents with explicit errors before dispatch:

- API session creation
- MCP `start_session` / `run_agent_command`
- command handlers (`start_agent`, `resume_agent`, `restart_agent` as applicable)
- fallback pickers (CLI/tooling) must consider config-enabled status

### R4. Next-machine guidance quality

- Guidance must only list enabled and runtime-available agents.
- If no selectable agent exists, return explicit blocking error.
- Per-agent guidance lines must be meaningful:
  - if strengths/avoid are empty, render explicit placeholders (not blank lines).

### R5. TUI and availability surfaces

- TUI selectable agent set must come from enabled-agent policy, not hardcoded arrays.
- If zero enabled agents, TUI must show a blocking configuration error and prevent agent launch actions.
- `/agents/availability` must reflect config-disabled status deterministically.

### R6. Backward compatibility and migration clarity

- Error messages must point to exact `config.yml` keys to fix.
- Existing deployments with explicit `agents` should continue working.

## Non-Functional Requirements

- Deterministic behavior across daemon restart.
- No silent fallback to disabled/missing agent config.
- Clear observability via logs for policy rejections.

## Acceptance Criteria

1. With no `agents:` section in `config.yml`, startup/config load fails with actionable error.
2. With `agents` present but all `enabled: false`, startup/config load fails with actionable error.
3. With one enabled agent, only that agent is selectable in TUI and accepted by dispatch paths.
4. Attempting to start/dispatch a disabled agent returns a deterministic error (API + MCP + command handler paths).
5. `compose_agent_guidance()` output contains no blank per-agent lines.
6. Hardcoded `['claude', 'gemini', 'codex']` selection loops are replaced by centralized policy helpers in selection/dispatch paths.

## Risks

- Partial migration can leave mixed behavior across older code paths.
- UI assumptions about fixed agent count may need controlled adaptation.

## Dependencies

- Logical dependency `adapter-output-delivery` is already delivered (`2026-02-24`, commit `21544a6d`), so this todo can proceed without an active roadmap block.

## Preconditions

- `config.yml` is available in the runtime environment where config validation runs.
- Build/test environment can execute targeted unit/integration tests under `tests/unit` and `tests/integration`.
- Any machine used for demonstration has a writable temp directory for test config fixtures.

## Edge Cases and Deferreds

- `run_agent_command` command-format validation (leading `/`) remains owned by existing MCP command contract tests; this todo should not weaken that guard.
- Visual theming constants that intentionally define color palettes per agent are out of scope unless they affect selection/availability behavior.
- New provider onboarding remains out of scope; only existing known agents are covered.

## Integration Safety and Rollback

- Integration is incremental: first centralize helper APIs, then migrate selection/dispatch call sites.
- Rollback path is containment by module: if a specific surface regresses, that surface can temporarily fall back to previous selection behavior while keeping strict config validation intact.
- No data migrations are required; behavior changes are runtime-policy only.
