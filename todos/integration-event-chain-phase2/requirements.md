# Requirements: integration-event-chain-phase2

## Goal

Complete the remaining integration-pipeline work after regression recovery.

After this work, the pipeline has one coherent ownership model:
- finalizer/orchestrator hand off via events only
- the cartridge feeds `review.approved`, `branch.pushed`, and `deployment.started`
  into the readiness projection and only wakes the integrator when the candidate is READY
- only the integrator agent calls `telec todo integrate`
- delivery bookkeeping and cleanup are executed by the integrator agent from explicit
  state-machine instructions, not synchronous subprocess automation hidden in Python

## Scope

### In scope

1. **Register `branch.pushed` event schema** in `teleclaude_events/schemas/software_development.py`
2. **Create `emit_branch_pushed()` helper** in `teleclaude/core/integration_bridge.py`
3. **Wire `emit_branch_pushed()` into the canonical finalize handoff seam** so the readiness
   projection receives the `branch.pushed` signal after the candidate branch push is known
   to have succeeded. [inferred: in current code this is the recovered `POST_COMPLETION["next-finalize"]`
   handoff path, not a resurrected direct integration path]
4. **Modify `IntegrationTriggerCartridge`** to:
   - Accept an event ingestion callback (for feeding events to the IntegrationEventService)
   - Monitor `review.approved`, `branch.pushed`, and `deployment.started` events
   - Map platform event types to canonical integration event types
   - Only trigger spawn + enqueue when projection transitions a candidate to READY
5. **Wire the cartridge** in `teleclaude/daemon.py` with the integration event service and queue
6. **Convert integrator delivery bookkeeping to AI-directed steps**:
   - `_step_committed()` must stop running `telec roadmap deliver`, `telec todo demo create`,
     `git add`, and `git commit` directly
   - instead, it returns explicit instructions for the integrator agent to run those commands,
     then re-enter `telec todo integrate`
7. **Convert integrator cleanup to AI-directed steps**:
   - `_do_cleanup()` must stop directly removing worktrees, branches, todo folders,
     staging cleanup, committing cleanup, and restarting the daemon
   - instead, it returns explicit instructions for the integrator agent to perform cleanup
     and then re-enter `telec todo integrate`
8. **Remove stale direct-integrate assumptions from tests and user-facing text**:
   - no orchestrator/finalizer guidance should imply that anyone except the integrator
     calls `telec todo integrate`

### Out of scope

- Finalize lock removal and `caller_session_id` cleanup — already landed
- The recovered `deployment.started` handoff in `POST_COMPLETION["next-finalize"]` — restored
  on March 6, 2026
- `mark-phase --cwd` / synthetic `finalize` phase expansion — discarded planning detour
- Documentation-only cleanup in `next-machine-old-code-cleanup`
- System intelligence cartridges (trust, enrichment, correlation, classification)
- Event mesh distribution — separate roadmap item
- Broad redesign of `telec todo integrate` itself beyond the delivery/cleanup ownership boundary
- Documentation updates outside direct stale-text cleanup

## Success Criteria

- [ ] `domain.software-development.branch.pushed` event schema registered in catalog
- [ ] `emit_branch_pushed()` exists in `integration_bridge.py` and emits correct envelope
- [ ] Canonical finalize handoff emits `branch.pushed` event after successful candidate-branch push
- [ ] IntegrationTriggerCartridge feeds `review.approved`, `branch.pushed`, and
      `deployment.started` events to the readiness projection via ingestion callback
- [ ] Integrator spawn + enqueue ONLY happens when projection reports READY
      (all 3 preconditions met)
- [ ] Integration trigger does NOT fire on `deployment.started` alone
- [ ] `_step_committed()` no longer performs delivery bookkeeping via direct subprocess calls
- [ ] `_do_cleanup()` no longer performs cleanup/commit/restart via direct subprocess calls
- [ ] Integrator instruction blocks tell the integrator agent what to run, then re-enter
      `telec todo integrate`
- [ ] No orchestrator/finalizer guidance tells non-integrators to call `telec todo integrate`
- [ ] `make test` passes
- [ ] `make lint` passes

## Constraints

- `teleclaude_events/` must not import from `teleclaude.*` — use constructor-injected callbacks
  to maintain the one-way dependency boundary
- Existing integrator-wiring demo validation must still pass after changes
- Queue/lease serialization must remain intact while delivery bookkeeping becomes AI-directed
- Only the integrator may call `telec todo integrate`; no new backdoors for orchestrator use

## Risks

- **State-machine re-entry drift**: moving bookkeeping from synchronous Python into agent-executed
  steps requires checkpoint transitions to remain deterministic across retries.
- **Hidden direct callers**: stale tests/comments/wrappers may continue implying that the
  orchestrator calls `telec todo integrate`, which would reintroduce the wrong ownership model.
- **Scope overlap with superseded planning**: `architecture-alignment-integration-pipeline`
  is no longer canonical and must not be built separately.
