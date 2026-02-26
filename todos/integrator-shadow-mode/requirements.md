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
5. Main branch clearance: detect active standalone sessions on main, commit dirty files when safe.

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

### FR4: Main Branch Clearance

1. Before processing any queue candidate, the integrator MUST verify that `main` is
   uncontested and clean. This check is a blocking prerequisite — the integrator
   MUST NOT proceed until clearance succeeds.
2. Session classification heuristic:
   - Sessions with `initiator_session_id` set are **workers** (operate in worktrees). Skip.
   - Sessions referenced as `initiator_session_id` by other sessions are **orchestrators**
     (dispatch into worktrees). Skip.
   - Remaining sessions are **standalone candidates** that may be working on `main`.
3. For each standalone candidate, the integrator MUST inspect recent session output
   (via `telec sessions tail`) to determine whether the session is actively modifying
   `main`. Stale or idle sessions are not blockers.
4. If clearance fails (active standalone session on `main`, or dirty files detected):
   - The integrator MUST wait a configurable interval (default: 60 seconds).
   - Then re-run the full clearance check from step 1.
   - This cycle repeats indefinitely — the integrator never gives up or times out.
5. If clearance succeeds (no active standalone sessions on `main`), the integrator
   MAY commit any dirty tracked files as a housekeeping commit.
6. After the housekeeping commit, the integrator MUST re-verify the working tree is
   clean before proceeding. If new dirty files appeared, return to step 4.

### FR5: Operational Safety

1. Shutdown MUST release lease and persist checkpoint state.
2. Crashes/restarts MUST resume from durable queue state.

## Architecture Impact

The existing `project/spec/integration-orchestrator` MUST be updated to include
main branch clearance as a prerequisite step in the integrator lifecycle (between
lease acquisition and queue processing).

## Verification Requirements

1. Concurrency tests proving single active lease holder.
2. Queue-order tests proving FIFO behavior.
3. Shadow-mode tests proving no canonical main push path is executed.
4. Clearance tests proving orchestrator-worker pairs are correctly excluded
   from standalone candidate inspection.
5. Clearance tests proving idle/stale standalone sessions do not block integration.

## Risks

1. Lease renewal timing bugs can cause dual processors.
2. Queue replay bugs can duplicate shadow outcomes.
3. A standalone session could start modifying `main` between clearance check and
   housekeeping commit (narrow race window; acceptable in shadow mode).
