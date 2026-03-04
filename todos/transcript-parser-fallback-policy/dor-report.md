# DOR Report: transcript-parser-fallback-policy

## Draft Assessment

### Gate 1: Intent & Success
**Status: Pass**
- Problem statement is explicit: duplicated, silent fallback logic for unknown transcript parser agents.
- Success criteria are concrete and testable (centralized function, logging levels, specific test cases).
- The "what" (centralize fallback) and "why" (eliminate duplication, add observability) are captured in requirements.

### Gate 2: Scope & Size
**Status: Pass**
- Atomic: one new function, four callsite verifications (two actual code changes), one test file update.
- Fits a single AI session without context exhaustion.
- No cross-cutting concerns — changes are localized to the transcript parsing pipeline.

### Gate 3: Verification
**Status: Pass**
- Seven specific test cases defined covering canonical values, `None`, empty string, unknown values, case insensitivity, and log levels.
- `make test` and `make lint` as standard verification.
- Edge cases identified: `None` vs empty string vs unknown string have different log levels.

### Gate 4: Approach Known
**Status: Pass**
- The pattern is straightforward: extract inline try/except into a function, replace callsites.
- Codebase already uses `AgentName.from_str()` everywhere — the new function wraps it with fallback and logging.
- No architectural decisions needed.

### Gate 5: Research Complete
**Status: Pass (auto-satisfied)**
- No third-party tools or libraries involved. Pure internal refactoring.

### Gate 6: Dependencies & Preconditions
**Status: Pass**
- Depends on `default-agent-resolution` which is already delivered (2026-03-05).
- No external systems, configs, or environments needed.
- No new configuration keys.

### Gate 7: Integration Safety
**Status: Pass**
- Behavioral change is minimal: existing silent fallback becomes a logged fallback.
- No API contract changes. No user-visible behavior changes.
- Rollback is trivial: revert the commit.

### Gate 8: Tooling Impact
**Status: Pass (auto-satisfied)**
- No tooling or scaffolding changes.

## Summary

All eight DOR gates pass. The todo is well-scoped, the approach is proven (wrapping
existing patterns), and the implementation plan maps 1:1 to requirements. Two callsites
need actual code changes; two need verification only. Seven tests cover the edge cases.

## Assumptions

- The `debug` vs `warning` log-level split (debug for `None`/empty, warning for unknown)
  is the right tradeoff. This is an inference based on the observation that fresh sessions
  may have `None` as `active_agent` before the agent starts, which is expected behavior
  and should not generate warnings.

## Open Questions

None.

## Blockers

None.
