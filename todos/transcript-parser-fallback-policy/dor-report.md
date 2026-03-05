# DOR Report: transcript-parser-fallback-policy

## Gate Verdict: PASS (score: 9)

### Gate 1: Intent & Success
**Pass.** Problem statement is explicit: duplicated, silent fallback logic for unknown
transcript parser agents needs centralization and observability. Success criteria are
concrete and testable (centralized function, log-level split, seven specific test cases).
The "what" and "why" are captured in requirements.

### Gate 2: Scope & Size
**Pass.** Atomic: one new function in `agents.py`, two callsite code changes (streaming.py,
api_server.py), two verification-only callsites (transcript.py), one test file update.
Fits a single session without context exhaustion. No cross-cutting concerns.

### Gate 3: Verification
**Pass.** Seven test cases defined covering canonical values, `None`, empty string, unknown
values, case insensitivity, and log-level assertions. `make test` and `make lint` as
standard checks. Edge cases explicitly identified: `None` vs empty vs unknown have
different log levels per the constraints.

### Gate 4: Approach Known
**Pass.** The pattern is straightforward: extract inline try/except into a function that
wraps `AgentName.from_str()` with fallback and logging. Codebase already uses this exact
inline pattern at both callsites — the function extracts it.

### Gate 5: Research Complete
**Pass (auto-satisfied).** No third-party tools or libraries involved. Pure internal
refactoring.

### Gate 6: Dependencies & Preconditions
**Pass.** Depends on `default-agent-resolution` which is delivered (2026-03-05, commit
806fd11c). No external systems, configs, or environments needed. No new configuration keys.

### Gate 7: Integration Safety
**Pass.** Behavioral change is minimal: existing silent fallback becomes a logged fallback.
No API contract changes. No user-visible behavior changes. Rollback is trivial: revert the
commit.

### Gate 8: Tooling Impact
**Pass (auto-satisfied).** No tooling or scaffolding changes.

## Plan-to-Requirement Fidelity

Verified 1:1 mapping:
- Requirement: centralized `resolve_parser_agent()` → Plan Task 1.1
- Requirement: all callsites migrated → Plan Tasks 1.2-1.5 (two code changes, two verifications)
- Requirement: log-level split (`debug` for `None`/empty, `warning` for unknown) → Plan Task 1.1 + Test Tasks 2.1.6-2.1.7
- Requirement: seven test cases → Plan Task 2.1 enumerates all seven

Codebase verification:
- `streaming.py:119-125` (`_get_agent_name`) confirmed: inline try/except with `or "claude"` default
- `api_server.py:1097-1100` (`/messages` endpoint) confirmed: inline try/except with `or "claude"` default
- `transcript.py` functions confirmed: both take `AgentName` enum (not raw string) — verification-only is correct
- `resolve_parser_agent` does not yet exist — creation is required

## Actions Taken

- Tightened success criterion #3 in `requirements.md` to align with the constraints section:
  log-level split (`debug` for `None`/empty, `warning` for unknown) was already specified in
  constraints and the implementation plan, but the success criterion said "warning whenever
  fallback is triggered." Updated to match the more precise spec.

## Assumptions

- The `debug` vs `warning` log-level split is the right tradeoff. Fresh sessions may have
  `None` as `active_agent` before the agent starts — expected behavior, not a warning.

## Open Questions

None.

## Blockers

None.
