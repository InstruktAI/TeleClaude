# Requirements: integration-blocked-flow

## Goal

When integration cannot proceed (for example merge conflicts), emit a durable
`integration_blocked` outcome with evidence and resumable follow-up workflow.

## Why

Blocked integrations must be actionable and recoverable; silent failures or
non-resumable dead ends stall delivery.

## In Scope

1. `integration_blocked` event payload contract with evidence fields.
2. Follow-up todo creation contract for blocked candidates.
3. Resume UX contract that links follow-up resolution back to queue processing.

## Out of Scope

1. Cutover authority controls.
2. Core lease/queue implementation.

## Functional Requirements

### FR1: Evidence-Rich Blocked Outcome

1. Blocked outcomes MUST include `slug`, `branch`, `sha`, and conflict evidence.
2. Diagnostics MUST include next action guidance.

### FR2: Resumable Follow-Up Workflow

1. Each blocked candidate MUST create/associate a follow-up todo.
2. Follow-up todo MUST preserve linkage to original candidate.

### FR3: Safe Resume

1. Resume flow MUST re-check readiness before re-queueing.
2. Resume MUST not bypass integrator serialization.

## Verification Requirements

1. Conflict simulation test proving blocked event fields are complete.
2. Follow-up todo creation test proving linkage and idempotency.
3. Resume-path test proving candidate can continue after remediation.

## Risks

1. Poor evidence quality can force manual triage loops.
2. Duplicate follow-up creation can fragment ownership.
