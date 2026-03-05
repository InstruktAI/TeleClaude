# Requirements: next-machine-old-code-cleanup

## Goal

Strip the old manual integration trigger path from the next-machine now that event-driven
integration automation is in place. The orchestrator should emit an event and move on —
no more finalize locks, no more `caller_session_id`, no more inline `telec todo integrate`.

## Scope

### In scope

- Remove finalize lock mechanism (functions, lock file, all call sites, session cleanup)
- Remove `caller_session_id` from `next_work()` and the API route
- Rewrite `POST_COMPLETION["next-finalize"]` to emit-and-move-on pattern
- Update three stale documentation files (finalize lifecycle, next-machine design, finalizer concept)
- Update or remove tests that exercise removed code paths

### Out of scope

- Event chain wiring (Phase 1 — separate work)
- Integration state machine changes (already delivered)
- Readiness projection changes (already delivered)

## Success Criteria

- [ ] `acquire_finalize_lock`, `release_finalize_lock`, `get_finalize_lock_holder` removed from codebase
- [ ] `caller_session_id` parameter removed from `next_work()` signature and API route
- [ ] `POST_COMPLETION["next-finalize"]` no longer contains `telec todo integrate`
- [ ] No references to `todos/.finalize-lock` remain in production code
- [ ] Documentation reflects integrator-owned merge-to-main (not orchestrator-owned)
- [ ] All tests pass
- [ ] Demo validation scripts from `demos/integrator-wiring/demo.md` pass

## Constraints

- Must land AFTER event chain wiring (Phase 1) is verified working
- Must not break in-flight orchestrator builds during transition

## Risks

- In-flight builds using the manual path could break if landed prematurely — mitigated by dependency gate
- Test coverage for the old path may be sparse, making removal seem safe when it isn't — mitigated by running full test suite
