# Requirements: integrator-shadow-mode

## Goal

Run the singleton lease+queue integrator in shadow mode so orchestration behavior
is validated without allowing canonical `main` merges.

## Why

Shadow mode proves queueing, lease handling, and readiness rechecks before cutover
removes fallback merge paths.

## In Scope

1. Lease acquisition/renew/release for key `integration/main`.
2. Durable FIFO queue processing by readiness timestamp.
3. Candidate revalidation before integration attempt.
4. Shadow outputs (`would_integrate`, `would_block`) without canonical main pushes.

## Out of Scope

1. Enforcing integrator-only main push policy (cutover responsibility).
2. Creating blocked follow-up todos.

## Functional Requirements

### FR1: Singleton Runtime

1. At most one active lease holder MAY process queue items.
2. Expired lease MAY be safely taken over by a new holder.

### FR2: Queue Discipline

1. Queue MUST be durable and FIFO by `ready_at`.
2. Candidate status transitions MUST be auditable.

### FR3: Shadow Execution

1. Runtime MUST re-check readiness immediately before apply simulation.
2. Runtime MUST emit shadow outcomes without pushing canonical `main`.

### FR4: Operational Safety

1. Shutdown MUST release lease and persist checkpoint state.
2. Crashes/restarts MUST resume from durable queue state.

## Verification Requirements

1. Concurrency tests proving single active lease holder.
2. Queue-order tests proving FIFO behavior.
3. Shadow-mode tests proving no canonical main push path is executed.

## Risks

1. Lease renewal timing bugs can cause dual processors.
2. Queue replay bugs can duplicate shadow outcomes.
