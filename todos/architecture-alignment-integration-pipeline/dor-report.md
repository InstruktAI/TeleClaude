# DOR Report: architecture-alignment-integration-pipeline

## Assessment Summary

**Verdict:** Draft complete. Ready for gate validation.

The original input contained 9 items. Codebase research revealed 3 are already
resolved or stale, 1 is a separate concern, and 5 form the core work — further
scoped to 4 after confirming session auth is resolved. The remaining scope is
atomic, grounded in codebase evidence, and fits a single build session.

## Gate Criteria Assessment

### 1. Intent & Success
**Status:** Satisfied.

Problem: `emit_deployment_started()` is defined but never called. The event-driven
integration trigger path is dead. Orchestrator bypasses it with direct `telec todo
integrate` calls.

Outcome: Wire the event-driven path end-to-end. After finalize, the state machine
emits `deployment.started`, the cartridge spawns the integrator. No direct CLI call.

### 2. Scope & Size
**Status:** Satisfied with one assumption.

Four concrete changes across 3 files + 1 doc:
- `tool_commands.py`: ~10 lines (--cwd flag)
- `next_machine/core.py`: ~30 lines (post-finalize branch) + ~10 lines (guidance)
- `version-control-safety.md`: ~15 lines (policy text)
- Tests: ~50 lines

**Assumption:** The `state.yaml` schema already supports a `finalize` phase field
via `mark-phase`, or can be trivially extended. If mark-phase stores phase status
differently than expected, the builder may need to investigate — but the delta
should be small.

### 3. Verification
**Status:** Satisfied.

Clear verification path:
- Unit tests for --cwd flag and post-finalize emission
- Demo script validates key behaviors
- Integration test: mock finalize-complete state → verify event emitted
- Full test suite must pass

### 4. Approach Known
**Status:** Satisfied.

- `emit_deployment_started()` exists, is async, has clear parameters
- `IntegrationTriggerCartridge` already watches `deployment.started`
- `next_work()` flow is well-understood; insertion point identified (after line 3022)
- Guidance text format is established (`POST_COMPLETION` dict)

### 5. Research Complete
**Status:** Satisfied.

No new third-party dependencies. All components are internal:
- `integration_bridge.py` (emit function)
- `cartridges/integration_trigger.py` (event watcher)
- `next_machine/core.py` (state machine)

### 6. Dependencies & Preconditions
**Status:** Satisfied.

- No blocking dependencies. Event platform is delivered.
- `IntegrationTriggerCartridge` is wired and deployed.
- `emit_deployment_started` is implemented and tested.
- `next-machine-old-code-cleanup` depends on THIS todo (not the reverse).

### 7. Integration Safety
**Status:** Satisfied.

- New event emission path coexists with old manual path
- Old path remains functional until cleanup todo removes it
- Incremental: each phase can be committed and verified independently
- Rollback: revert the guidance text to restore old behavior

### 8. Tooling Impact
**Status:** Not applicable (no tooling/scaffolding changes).

## Corrections from Input

| Input Item # | Description | Correction |
|---|---|---|
| 5 | Auto-commits conversion (`_step_committed`, `_do_cleanup`) | Functions exist in `integration/state_machine.py`, not `next_machine/core.py`. Separate concern — recommend dedicated todo. |
| 6 | Session auth on integrate | Already resolved. `tool_client.py` sends `X-Caller-Session-ID` automatically on every API call. |
| 7 | queue.json vestigial | Incorrect. `IntegrationQueue` (430 lines) is the durable backing store. Events trigger; queue.json sequences. |

## Recommended Split

The auto-commits conversion (input item 5) should be a separate todo:
- **What:** Convert `_step_committed()` and `_do_cleanup()` auto-commits to AI-directed
  instructions. State machine returns "commit with message X" instead of executing git.
- **Why separate:** Independent concern (integrator internals vs. trigger wiring).
  Does not block event-driven path. Significant redesign of integration state machine flow.
- **Depends on:** Nothing in this todo.

## Open Questions

1. **Finalize phase field in state.yaml:** Does `mark-phase --phase finalize` create
   a `finalize` key in state.yaml? The builder should verify the mark-phase API behavior
   and ensure `next_work()` can read the result. If the field doesn't exist yet, the
   schema extension is trivial.

2. **Concurrent finalize detection:** If `next_work()` is called multiple times after
   finalize completes (e.g., orchestrator retries), `emit_deployment_started()` would
   fire multiple times. The `IntegrationTriggerCartridge` and `IntegrationQueue`
   handle deduplication, but verify this explicitly.

## Blockers

None. Proceed to gate validation.
