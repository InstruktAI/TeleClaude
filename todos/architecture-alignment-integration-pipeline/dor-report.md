# DOR Report: architecture-alignment-integration-pipeline

## Gate Verdict: needs_work

**Score: 7/10** — Approach is sound and well-researched, but a concrete plan-to-codebase
contradiction blocks the builder. Remediation is small and well-defined.

---

## Gate Criteria Assessment

### 1. Intent & Success — Pass

Problem: `emit_deployment_started()` is defined but never called. The event-driven
integration trigger path is dead. Orchestrator bypasses it with direct `telec todo
integrate` calls.

Outcome: Wire the event-driven path end-to-end. After finalize, the state machine
emits `deployment.started`, the cartridge spawns the integrator. No direct CLI call.

Success criteria are concrete and testable.

### 2. Scope & Size — Pass

Four concrete changes across 3 files + 1 doc + tests. Atomic, fits a single session.

### 3. Verification — Pass

Clear verification path: unit tests for --cwd and post-finalize emission, demo script,
full test suite. Edge cases identified (worktree missing, concurrent calls).

### 4. Approach Known — Needs Work (Blocker)

**Plan-to-codebase contradiction: `mark-phase --phase finalize` is rejected by the API.**

The requirements (Success Criteria #1) and implementation plan (Task 2.2) both prescribe:
```
telec todo mark-phase {slug} --phase finalize --status complete --cwd /path
```

But the API route at `todo_routes.py:133-134` explicitly validates:
```python
if phase not in ("build", "review"):
    raise HTTPException(status_code=400, detail=f"invalid phase '{phase}': must be 'build' or 'review'")
```

And `PhaseName` enum (`core.py:42-44`) only has `BUILD` and `REVIEW`. There is no `FINALIZE`.

The builder would hit an HTTP 400 error on the first attempt to mark finalize complete.
The plan assumes this call works — it does not.

**Remediation required:**
1. Add `FINALIZE = "finalize"` to `PhaseName` enum (`core.py:44`).
2. Add `"finalize"` to the API validation whitelist (`todo_routes.py:133`).
3. Update CLI handler docstring (`tool_commands.py:960`) to list finalize as a valid phase.
4. Add these as explicit tasks in the implementation plan (Phase 1, before --cwd work).
5. Add to requirements scope: "Extend phase schema to include finalize."

This is a ~5-line fix but must be explicitly planned — the builder should not discover it
at runtime.

### 5. Research Complete — Pass

No third-party dependencies. All components are internal and verified:
- `integration_bridge.py:51` — `emit_deployment_started()` exists, async, clear signature.
- `cartridges/integration_trigger.py:31` — `IntegrationTriggerCartridge` watches `deployment.started`.
- `next_machine/core.py` — state machine flow well-understood.

### 6. Dependencies & Preconditions — Pass

No blocking dependencies. Event platform delivered. `IntegrationTriggerCartridge` wired.
`next-machine-old-code-cleanup` depends on THIS todo (not reverse).

### 7. Integration Safety — Pass

New event emission path coexists with old manual path. Old path remains functional until
cleanup todo removes it. Incremental and reversible.

### 8. Tooling Impact — N/A

No tooling/scaffolding changes.

---

## Corrections from Input

| Input Item # | Description | Correction |
|---|---|---|
| 5 | Auto-commits conversion (`_step_committed`, `_do_cleanup`) | Functions exist in `integration/state_machine.py`, not `next_machine/core.py`. Separate concern — recommend dedicated todo. |
| 6 | Session auth on integrate | Already resolved. `tool_client.py` sends `X-Caller-Session-ID` automatically on every API call. |
| 7 | queue.json vestigial | Incorrect. `IntegrationQueue` (430 lines) is the durable backing store. Events trigger; queue.json sequences. |

## Resolved Open Questions

1. **Finalize phase field in state.yaml:** `mark-phase --phase finalize` currently **fails**
   with HTTP 400. The API validation at `todo_routes.py:133` only accepts `build` and `review`.
   The `PhaseName` enum has no `FINALIZE` member. Remediation: extend both (see Gate 4 above).

2. **Concurrent finalize detection:** `emit_deployment_started()` could fire multiple times
   if `next_work()` is retried. The `IntegrationTriggerCartridge` and `IntegrationQueue`
   handle deduplication. Builder should verify with a test but this is not a blocker.

## Recommended Split

The auto-commits conversion (input item 5) should be a separate todo:
- **What:** Convert `_step_committed()` and `_do_cleanup()` auto-commits to AI-directed
  instructions. State machine returns "commit with message X" instead of executing git.
- **Why separate:** Independent concern (integrator internals vs. trigger wiring).
  Does not block event-driven path. Significant redesign of integration state machine flow.
- **Depends on:** Nothing in this todo.

## Actions Required

1. **Requirements**: Add scope item for extending `PhaseName` and API validation to include finalize.
2. **Implementation Plan**: Add Phase 1 task for `PhaseName`/API/CLI extension before --cwd work.
3. **Implementation Plan**: Ensure Task 2.1 insertion point is clear — the post-finalize branch
   goes before the review-approved check at line 2850, not after line 3022 (which is the
   finalize dispatch for review-approved state). The builder needs to detect `state.get("finalize") == "complete"` early in the routing logic.

## Blockers

None that require human decision. All findings are `needs_work` — the draft author
can remediate with targeted edits to requirements and plan.
