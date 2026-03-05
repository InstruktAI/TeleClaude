# Input: integration-event-chain-phase2

## Context

Phase 1 wired the automated integration event chain: `telec todo finalize-ready`
emits `deployment.started`, enqueues the candidate, and the cartridge spawns the
integrator. But the cartridge still triggers on a single event (`deployment.started`)
rather than the full three-event predicate, and the manual finalize lock remains
as redundant ceremony.

## What this delivers

A mechanically verified integration gate: the readiness projection confirms all
three preconditions (review approved, branch pushed, deployment started) before
the cartridge triggers integration. The manual finalize lock is removed since the
queue + readiness projection provide stronger serialization guarantees.

## Scope

### 1. Wire readiness projection into the cartridge

The `IntegrationTriggerCartridge` currently fires on `deployment.started` alone.
Wire it to feed all three event types into the existing `ReadinessProjection` and
only trigger spawn + enqueue when the projection reports READY.

Events to feed:
- `review.approved` → `ReadinessProjection.record_review_approved()`
- `branch.pushed` → `ReadinessProjection.record_branch_pushed()`
- `deployment.started` → `ReadinessProjection.record_deployment_started()`

The readiness projection already exists at
`teleclaude/core/integration/readiness_projection.py` with these methods. The
cartridge just needs to call them and check `projection.status(key)` == READY
before triggering.

### 2. Remove finalize lock mechanism

The file-based `todos/.finalize-lock` and the multi-step lock verification in
`POST_COMPLETION["next-finalize"]` are redundant now that the queue serializes
candidates. Remove:
- Lock file creation/verification/cleanup from POST_COMPLETION instructions
- Any lock-related code in `next_machine/core.py`
- Lock checks from the finalize worker flow

### 3. Remove `caller_session_id` from `next_work()` signature

The `caller_session_id` parameter on `next_work()` was used for tracking but
creates coupling. Remove it and let the session resolve from environment where
needed.

### 4. Call `emit_branch_pushed()` from the finalize worker

The `emit_branch_pushed()` helper added in Phase 1 is unused. Wire it into the
finalize worker's git push step so the readiness projection receives the
`branch.pushed` signal.

## Out of scope

- Documentation updates (separate cleanup pass)
- Changing the `telec todo integrate` command itself (still used by the integrator)
- Event mesh distribution (separate roadmap item)
