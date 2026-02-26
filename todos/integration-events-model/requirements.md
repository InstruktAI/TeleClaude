# Requirements: integration-events-model

## Goal

Define and persist the canonical integration event model so readiness can be
computed from durable evidence instead of transient process state.

## Why

The integrator must decide readiness from auditable data. Without a canonical
event model, readiness checks drift and queue admission becomes unreliable.

## In Scope

1. Canonical schemas for `review_approved`, `finalize_ready`, and `branch_pushed`.
2. Durable event append and idempotent replay behavior.
3. Readiness projection for `(slug, branch, sha)` candidates.
4. Supersession logic for newer `finalize_ready` events on the same slug.

## Out of Scope

1. Lease acquisition/runtime loop (`integration/main`) implementation.
2. Mainline merge/push execution.
3. Blocked-flow follow-up todo creation.

## Functional Requirements

### FR1: Canonical Event Fidelity

1. Event payload fields MUST match `docs/project/spec/integration-orchestrator.md`.
2. Events missing required fields MUST be rejected with explicit diagnostics.

### FR2: Durable and Idempotent Ingestion

1. Accepted events MUST be persisted before projection update.
2. Duplicate event submissions MUST be idempotent.

### FR3: Readiness Projection

1. Projection MUST require all three canonical events and branch/sha alignment.
2. Projection MUST enforce remote reachability and not-already-integrated checks.
3. `worktree dirty -> clean` MUST NOT affect readiness.

### FR4: Supersession Semantics

1. Newer `finalize_ready` for the same slug MUST supersede older candidates.
2. Superseded candidates MUST remain auditable.

## Verification Requirements

1. Unit tests for event validation, idempotency, and supersession behavior.
2. Integration test covering readiness transitions from `NOT_READY` to `READY`.
3. Contract tests asserting payload fields match spec.

## Risks

1. Event duplication edge cases can corrupt readiness if idempotency is weak.
2. Reachability checks can report stale data if remote refs are not refreshed.
