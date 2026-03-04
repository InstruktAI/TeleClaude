# Requirements: integrator-state-machine

## Goal

Replace the prose-based `/next-integrate` command with a deterministic Python state machine
that the integrator agent calls repeatedly via `telec todo integrate [<slug>]`. Each
invocation reads a durable checkpoint, executes the next deterministic block, and returns
structured instructions at decision points where agent intelligence is required.

The state machine is the authority on sequencing. The agent is the authority on intelligence.
Neither does the other's job.

## Scope

### In scope

- Idempotent state machine function `next_integrate()` following the `next_work()` pattern
  in `teleclaude/core/next_machine/core.py`
- Durable checkpoint schema for crash recovery and idempotent re-entry
- Five state phases per candidate: merge, agent-commit, delivery-bookkeeping, push, cleanup
- Three decision points: squash commit composition, conflict resolution, push rejection recovery
- CLI entry point `telec todo integrate [<slug>]` mirroring `telec todo work`
- API route `POST /todos/integrate` mirroring `POST /todos/work`
- Integration lifecycle event emission at each state transition
- Updated `/next-integrate` command spec to call the state machine in a loop
- Queue drain loop: process all READY candidates in FIFO order

### Out of scope

- Changes to existing integration primitives (queue, lease, readiness, clearance, follow-up)
- Dashboard or notification projector for integration events
- Changes to the trigger cartridge's `spawn_integrator_session`
- Shadow mode logic changes (cutover controls remain as-is)
- Changes to `IntegratorShadowRuntime` — the state machine replaces the runtime's
  role as the agent-facing entry point while reusing its primitives

## Success Criteria

- [ ] `telec todo integrate` returns a structured instruction block at each decision point
- [ ] Agent can call `telec todo integrate` repeatedly to advance through the full
      integration lifecycle for one candidate
- [ ] After processing one candidate, calling again pops the next READY candidate
- [ ] If the agent crashes mid-turn, the next `telec todo integrate` call resumes
      from the last checkpoint (idempotency)
- [ ] Lifecycle events emitted at each state transition (observable via event stream)
- [ ] Queue empty returns exit instruction for agent self-end
- [ ] Merge conflicts return conflicted file list and resolution instructions
- [ ] Push rejection returns diagnosis instructions
- [ ] Lease prevents concurrent integrators (existing primitive, wired through)
- [ ] Clearance probe gates merge attempts (existing primitive, wired through)
- [ ] Delivery bookkeeping (roadmap deliver, demo snapshot, cleanup) runs deterministically
- [ ] All existing integration tests continue to pass

## Constraints

- Reuse existing primitives: `IntegrationQueue`, `IntegrationLeaseStore`,
  `ReadinessProjection`, `MainBranchClearanceProbe`, `BlockedFollowUpStore`,
  `IntegratorCutoverControls`, `integration_bridge.py` event helpers
- Follow the `next_work()` pattern: async function returning plain text instruction
  blocks via `format_tool_call()` style formatting
- Checkpoint file must be atomic (temp file + os.replace) like queue persistence
- State machine must not perform git operations that require agent intelligence
  (commit message composition, conflict resolution) — these are decision points
- The `/next-integrate` command remains the agent-facing interface; the state machine
  is the implementation behind `telec todo integrate`

## Risks

- Checkpoint corruption during crash could leave integration in inconsistent state.
  Mitigation: atomic writes + recovery logic that re-queues interrupted candidates
  (existing pattern in `IntegrationQueue._recover_in_progress_items()`).
- Concurrent `telec todo integrate` calls from different sessions could race.
  Mitigation: lease-based mutual exclusion (existing `IntegrationLeaseStore`).
- Git operations (fetch, merge, push) are inherently side-effectful and not perfectly
  idempotent. Mitigation: checkpoint records exact git state (commit SHAs) so
  re-entry can detect already-completed operations.
