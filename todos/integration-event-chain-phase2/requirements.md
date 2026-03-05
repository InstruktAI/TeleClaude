# Requirements: integration-event-chain-phase2

## Goal

Complete the automated integration event chain by wiring the ReadinessProjection into the
IntegrationTriggerCartridge, creating the branch.pushed event emission, and removing the
now-redundant finalize lock mechanism.

After this work, the integration gate is fully mechanized: the cartridge feeds all three
precondition events (review approved, branch pushed, finalize ready) into the readiness
projection, and only spawns the integrator + enqueues the candidate when the projection
reports READY. The file-based finalize lock and `caller_session_id` coupling are removed.

## Scope

### In scope

1. **Register `branch.pushed` event schema** in `teleclaude_events/schemas/software_development.py`
2. **Create `emit_branch_pushed()` helper** in `teleclaude/core/integration_bridge.py`
3. **Wire `emit_branch_pushed()` into the finalize worker's git push step** so the projection
   receives the `branch.pushed` signal
4. **Modify `IntegrationTriggerCartridge`** to:
   - Accept an event ingestion callback (for feeding events to the IntegrationEventService)
   - Monitor `review.approved`, `branch.pushed`, and `deployment.started` events
   - Map platform event types to canonical integration event types
   - Only trigger spawn + enqueue when projection transitions a candidate to READY
5. **Wire the cartridge** in `teleclaude/daemon.py` with the integration event service and queue
6. **Remove finalize lock mechanism**: `acquire_finalize_lock`, `release_finalize_lock`,
   `get_finalize_lock_holder`, constants, `_finalize_lock_path`, session cleanup hook
7. **Remove `caller_session_id`** from `next_work()` signature and `/todos/work` API route
8. **Rewrite `POST_COMPLETION["next-finalize"]`** to emit-and-move-on pattern (no inline
   `telec todo integrate`, no lock file cleanup)

### Out of scope

- System intelligence cartridges (trust, enrichment, correlation, classification) — separate
  todo `event-system-cartridges`
- Event mesh distribution — separate roadmap item
- Changes to `telec todo integrate` command itself (used by the integrator)
- Documentation updates (separate cleanup pass)

## Success Criteria

- [ ] `domain.software-development.branch.pushed` event schema registered in catalog
- [ ] `emit_branch_pushed()` exists in `integration_bridge.py` and emits correct envelope
- [ ] Finalize worker emits `branch.pushed` event after successful git push
- [ ] IntegrationTriggerCartridge feeds `review.approved`, `branch.pushed`, and
      `deployment.started` events to the readiness projection via ingestion callback
- [ ] Integrator spawn + enqueue ONLY happens when projection reports READY
      (all 3 preconditions met)
- [ ] Integration trigger does NOT fire on `deployment.started` alone
- [ ] `acquire_finalize_lock`, `release_finalize_lock`, `get_finalize_lock_holder` removed
- [ ] `caller_session_id` removed from `next_work()` signature and `/todos/work` API route
- [ ] `POST_COMPLETION["next-finalize"]` no longer contains `telec todo integrate` or lock cleanup
- [ ] No references to `todos/.finalize-lock` in production code
- [ ] Session cleanup no longer calls `release_finalize_lock`
- [ ] `make test` passes
- [ ] `make lint` passes

## Constraints

- `teleclaude_events/` must not import from `teleclaude.*` — use constructor-injected callbacks
  to maintain the one-way dependency boundary
- Existing integrator-wiring demo validation must still pass after changes
- Queue serialization replaces lock serialization — no concurrent integration regressions
- Land as atomic commit to prevent mid-transition breakage for in-flight orchestrators

## Risks

- **False dependency on `event-system-cartridges`**: roadmap declares this dependency but the
  actual work is independent — phase 2 modifies the existing IntegrationTriggerCartridge and
  doesn't require system intelligence cartridges. Needs decision.
- **In-flight orchestrator builds**: if an orchestrator is mid-finalize using the old lock path
  while the lock mechanism is removed, it could error. Mitigated by atomic commit.
- **Scope overlap with `next-machine-old-code-cleanup`**: that scaffolded todo (not on roadmap)
  covers lock/caller_session_id removal. If phase 2 delivers these items, the cleanup todo
  should be closed/absorbed.
