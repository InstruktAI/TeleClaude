# DOR Report: architecture-alignment-integration-pipeline

## Gate Verdict: pass

**Score: 9/10** — All eight DOR gates satisfied. Previous blocker resolved.
Ready for build.

---

## Gate Criteria Assessment

### 1. Intent & Success — Pass

Problem: `emit_deployment_started()` is defined but never called. The event-driven
integration trigger path is dead. Orchestrator bypasses it with direct `telec todo
integrate` calls.

Outcome: Wire the event-driven path end-to-end. After finalize, the state machine
emits `deployment.started`, the cartridge spawns the integrator. No direct CLI call.

Success criteria are concrete and testable (6 checkboxes in requirements).

### 2. Scope & Size — Pass

Five in-scope items across 3 code files + 1 doc + tests. Atomic, fits a single session.
Task 1.0 (PhaseName extension) adds ~5 lines as a prerequisite for everything else.

### 3. Verification — Pass

Clear verification path:
- Task 1.2: tests for `--phase finalize` acceptance and `--cwd` override.
- Task 2.3: tests for post-finalize emission (event emitted, worktree missing, correct args).
- Phase 4: `make test`, `make lint`, full suite.
- Demo script validates key behaviors end-to-end.

### 4. Approach Known — Pass

Previous blocker resolved. Plan-to-requirement traceability:

| Requirement | Plan Task |
|---|---|
| 1. PhaseName extension | Task 1.0 |
| 2. mark-phase --cwd | Task 1.1 |
| 3. Post-finalize event emission | Task 2.1 |
| 4. Guidance update | Task 2.2 |
| 5. VCS policy update | Task 3.1 |

No plan task contradicts a requirement. Task 1.0 is explicitly sequenced as
prerequisite to Tasks 2.1/2.2 (which depend on `finalize` being a valid phase).

Task 2.1 insertion point is correct: post-finalize detection goes BEFORE the
review-approved check at ~line 2850, short-circuiting before finalize re-dispatch.

### 5. Research Complete — Pass

No third-party dependencies. All components internal and verified:
- `integration_bridge.py:51` — `emit_deployment_started()` exists, async, clear signature.
- `cartridges/integration_trigger.py:31` — `IntegrationTriggerCartridge` watches `deployment.started`.
- `next_machine/core.py` — state machine flow well-understood, line references verified.

### 6. Dependencies & Preconditions — Pass

No blocking dependencies. Event platform delivered. `IntegrationTriggerCartridge` wired.
`next-machine-old-code-cleanup` depends on THIS todo (not reverse).

### 7. Integration Safety — Pass

New event emission path coexists with old manual path. Old path remains functional until
cleanup todo removes it. Incremental, reversible (revert guidance to restore old behavior).

### 8. Tooling Impact — N/A

No tooling/scaffolding changes.

---

## Corrections from Input

| Input Item # | Description | Correction |
|---|---|---|
| 5 | Auto-commits conversion (`_step_committed`, `_do_cleanup`) | Functions exist in `integration/state_machine.py`, not `next_machine/core.py`. Separate concern — recommend dedicated todo. |
| 6 | Session auth on integrate | Already resolved. `tool_client.py` sends `X-Caller-Session-ID` automatically on every API call. |
| 7 | queue.json vestigial | Incorrect. `IntegrationQueue` (430 lines) is the durable backing store. Events trigger; queue.json sequences. |

## Notes

- **Concurrent finalize detection**: If `next_work()` is called multiple times after
  finalize completes, `emit_deployment_started()` could fire multiple times. Downstream
  deduplication (IntegrationTriggerCartridge + IntegrationQueue) handles this. Builder
  should verify but this is not a blocker.

## Recommended Split

The auto-commits conversion (input item 5) should be a separate todo:
- **What:** Convert `_step_committed()` and `_do_cleanup()` auto-commits to AI-directed
  instructions. State machine returns "commit with message X" instead of executing git.
- **Why separate:** Independent concern (integrator internals vs. trigger wiring).

## Gate History

| Round | Score | Status | Finding |
|---|---|---|---|
| 1 | 7 | needs_work | `mark-phase --phase finalize` rejected by API validation (`todo_routes.py:133`). PhaseName enum lacks FINALIZE. |
| 2 | 9 | pass | Remediated in c874bde40. Task 1.0 added, insertion point corrected, stale risk removed. |
