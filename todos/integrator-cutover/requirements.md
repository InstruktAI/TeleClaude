# Requirements: integrator-cutover

## Goal

Transition from shadow mode to enforced integrator ownership so no non-integrator
path can merge or push canonical `main`.

## Why

Without strict cutover controls, legacy finalize/worker paths can bypass the
serialized runtime and reintroduce race conditions on `main`.

## In Scope

1. Guardrails that block non-integrator canonical main merges/pushes.
2. Integrator-only execution path for canonical main integration.
3. Cutover go/no-go evidence checks and rollback trigger criteria.

## Out of Scope

1. Integration-blocked follow-up todo creation.
2. Reworking worker feature-branch push behavior.

## Functional Requirements

### FR1: Exclusive Main Authority

1. Only the integrator role MAY merge/push canonical `main`.
2. Non-integrator attempts MUST fail fast with actionable diagnostics.

### FR2: Controlled Enablement

1. Cutover MUST be enabled only after shadow parity evidence is accepted.
2. Rollback path MUST be explicit when parity evidence is incomplete.

### FR3: Compatibility Boundaries

1. Workers/finalizers MAY still push feature branches.
2. Existing branch-based workflows MUST remain intact.

## Verification Requirements

1. Acceptance test proving non-integrator canonical main push is rejected.
2. Acceptance test proving integrator path still succeeds.
3. Regression tests proving feature-branch pushes remain allowed.

## Risks

1. Missed legacy path can silently bypass new authority checks.
2. Overly broad guardrails can block valid non-main workflows.
