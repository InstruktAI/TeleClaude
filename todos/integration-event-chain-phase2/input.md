# Input: integration-event-chain-phase2

## Context

The finalize handoff regression was recovered on March 6, 2026: `next-finalize`
again emits `deployment.started` instead of telling the orchestrator to call
`telec todo integrate` directly.

The finalize lock removal and `caller_session_id` cleanup are already landed.
This todo is now the single canonical place for the remaining integration-pipeline
work after that recovery.

## What remains

1. Finish the three-event readiness gate:
   - `review.approved`
   - `branch.pushed`
   - `deployment.started`

2. Align the integrator with worker role boundaries:
   - The integrator agent is the only actor that calls `telec todo integrate`
   - Delivery bookkeeping and cleanup are AI-directed integrator steps, not
     synchronous subprocess automation inside the state machine

3. Clean up stale overlap from earlier planning:
   - `architecture-alignment-integration-pipeline` becomes research history only
   - `next-machine-old-code-cleanup` stays documentation-only after this todo lands

## Explicitly not remaining

- Re-introducing finalize locks or `caller_session_id` coupling
- Adding a synthetic `finalize` phase to `state.yaml`
- Orchestrator-owned `telec todo integrate` calls
