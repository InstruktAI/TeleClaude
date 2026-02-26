# Requirements: integration-safety-gates

## Goal

Introduce immediate safety gates in the existing finalize path so orchestrators
fail fast before unsafe canonical `main` apply attempts.

## Scope

### In scope

1. **Finalize dispatch safety gate** — before dispatching `/next-finalize`,
   require canonical `main` integration preconditions to pass.
2. **Finalize apply safety gate** — before running canonical apply steps,
   re-check preconditions and abort with explicit error if violated.
3. **Actionable failure messaging** — when blocked, return deterministic machine
   errors describing exactly which condition failed and what operator action is
   required.
4. **Regression-safe tests** — add/adjust unit tests to prove the new guardrails
   trigger correctly and preserve existing successful finalize flow.

### Out of scope

- Event persistence model (`review_approved`, `finalize_ready`, `branch_pushed`)
- Integrator lease/queue runtime
- Ownership cutover (integrator-only merge/push of canonical `main`)
- Integration blocked follow-up automation

## Success Criteria

- [ ] `telec todo work <slug>` refuses finalize dispatch when canonical `main`
      is unsafe (dirty or otherwise invalid for deterministic apply).
- [ ] Finalize apply path refuses execution when canonical preconditions fail,
      with explicit, stable error codes/messages.
- [ ] Existing happy-path finalize behavior remains intact when preconditions
      are satisfied.
- [ ] Unit tests cover both blocked and allowed branches of the new gates.

## Constraints

- Keep behavior changes minimal and localized to current finalize path.
- Do not introduce integrator queue/lease behavior in this step.
- Preserve existing command surfaces and orchestration patterns.
- Avoid destructive git behavior; guards should block with guidance.

## Risks

- **Over-blocking**: too strict gates could stall legitimate finalize runs.
  Mitigation: test both expected block and expected allow cases.
- **Under-blocking**: missing a dirty/divergence case can leave current failure
  mode intact. Mitigation: include targeted negative tests for known incidents.
