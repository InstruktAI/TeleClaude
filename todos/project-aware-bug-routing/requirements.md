# Requirements: project-aware-bug-routing

## Goal

Define one bug-handling route that is lightweight, deterministic, and safe:

1. `bug-*` items follow a dedicated bug route.
2. Non-`bug-*` items continue existing normal route unchanged.
3. Each bug is handled atomically with independent review before landing.

## In Scope

1. Routing
   - Prefix-based route selection (`bug-*` => bug route).
   - Default bug intake from current context without mandatory project-name input.
   - Explicit TeleClaude override flag for intentional TeleClaude bug targeting.
2. Atomic execution loop (per bug)
   - Fix phase runs in one agent/session.
   - Review phase runs immediately in a different agent/session.
   - If review fails, dispatch another fixer agent/session.
   - Retry until pass or retry limit.
3. Safety gates
   - No self-review.
   - No landing without review pass.
   - No unsafe direct bypass of merge/landing safeguards.
4. State and reporting
   - Persist minimal bug-run state (status, attempt, commit, fixer/reviewer identity, verdict, reason).
   - Produce a simple blocked-items report for `needs_human` outcomes.
5. Validation/docs
   - Targeted tests for routing, reviewer separation, retry behavior, and landing gate.
   - Concise docs for the route and operator expectations.

## Out of Scope

1. Converting each bug into a full todo artifact set.
2. Broad redesign of non-bug maintenance flows.
3. Large-scale migration of historical data unless strictly needed for compatibility.

## Success Criteria

- [ ] `bug-*` always enters bug route; non-`bug-*` never does.
- [ ] Bug intake works without mandatory project argument.
- [ ] TeleClaude override flag routes as intended.
- [ ] Reviewer is always different from current fixer.
- [ ] No bug is marked landed/done without explicit review pass.
- [ ] Failed review triggers another fixer attempt, not same-session self-approval.
- [ ] Retry limit produces deterministic `needs_human` state and appears in blocked report.
- [ ] Tests cover the contract above with behavior-focused assertions.

## Constraints

1. Keep implementation pragmatic and minimal; avoid introducing artifact-heavy process.
2. Keep existing non-bug workflows stable.
3. Prefer explicit, machine-checkable gates over informal policy text.

## Risks

1. Route ambiguity if slug normalization is inconsistent.
2. Hidden bypass paths that could mark completion without independent review.
3. State drift if retry/landing decisions are not written atomically.
