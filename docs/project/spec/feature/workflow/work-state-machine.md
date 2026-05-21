---
id: 'project/spec/feature/workflow/work-state-machine'
type: 'spec'
domain: 'software-development'
scope: 'project'
visibility: 'public'
applies_to: 'v1'
status: 'target'
delivered_by:
  - drift-detection-consolidation
description: 'Phase B state machine driving a prepared Todo through build → review → fix → terminal finalize_ready inside a per-slug worktree, with a single-flight lock per (project_root, slug) and caller-session ownership for finalize.'
---

# Work State Machine — Spec

## Required reads

- @~/.teleclaude/docs/software-development/principle/domain-driven-design.md
- @~/.teleclaude/docs/software-development/spec/domain-spec.md
- @docs/project/spec/domain/workflow.md

## What it is

The work state machine is the workflow capability that drives a prepared Todo through Phase B — `prepared` → `build_started` → `build_complete` → `review_changes_requested` (zero-or-more loops) → `review_approved` → terminal `finalize_ready`. Each call by the orchestrator reads the authoritative `lifecycle_phase`, dispatches the matching Phase handler, and returns a verbatim instruction telling the orchestrator what to do next — dispatch a builder, dispatch a reviewer, relay findings to an already-live builder, dispatch a finalizer, or perform terminal worker-session cleanup. Integration emission is owned by the `TodosDb` phase-transition chokepoint when an owned-session write lands `lifecycle_phase=finalize_ready`. Review verdicts (`approve` | `needs_work` | `needs_decision`) drive transitions between build, fix, and finalize.

Work is the first stage that materializes a per-slug worktree under `trees/<slug>`, branched from `origin/main` so the worktree baseline is a single source of truth shared by every concurrent worker. A single-flight asyncio lock keyed per `(canonical_project_root, slug)` makes same-slug calls in the same repo wait and reuse the prepared worktree, while same-slug calls in different repos remain fully independent. The caller's session ID is preserved across the async boundary so the finalize Phase records who owns the handoff — the peer-conversation contract that lets builders and reviewers iterate directly without context-destroying churn. A loop guard bounds in-call internal transitions, every Phase emits a grep-friendly `NEXT_WORK_PHASE` log line with decision and duration, and worktree prep failures surface as `unexpected_<ExceptionType>` reasons so the orchestrator can diagnose without inspecting daemon logs.

Before the `prepared → build_started` handoff and BEFORE `_ensure_worktree_ready`, work calls the shared `derive_lifecycle_drift` (the same function the prepare state machine uses; see `@spec/feature/workflow/drift-detection`). The state read that drives the derivation moves ahead of worktree creation in `next_work`: slug resolution and non-worktree preconditions happen first, then the state is read from `todos_db`, then `derive_lifecycle_drift` is called against repo-root state. When any tracked artifact's collapsed drift status is `pending` or `substantive`, work does NOT mutate work-state, does NOT create or touch a worktree on this call, and does NOT dispatch any worker; it returns an orchestrator script telling the caller to run `telec todo prepare {slug}` to resolve drift. The prepare flow's existing BLOCKED branch routes the drift analyzer; when prepare reaches `prepared` again, its terminal script line tells the orchestrator to call `telec todo work {slug}` next. The continuation across the bounce is the existing script-driven contract — no new mechanism, no human gate on cosmetic verdicts, and substantive verdicts cascade through the existing re-derivation chain back into a prepared Todo.

## Canonical fields

### Use cases

```
Given a Todo at lifecycle_phase=prepared with no worktree
When the orchestrator calls `telec todo work my-feature`
Then the machine acquires the (project_root, my-feature) single-flight lock
And calls derive_lifecycle_drift against current evidence
And every tracked artifact's collapsed drift status is fresh or cosmetic with a valid anchor
And creates a worktree at trees/my-feature branched from origin/main
And merges origin/main into the worktree once before dispatch
And advances lifecycle_phase from prepared to build_started in a machine-owned transition
And on the same call dispatches the next-build worker session
```

```
Given a Todo at lifecycle_phase=prepared whose plan artifact's owned-snippet digests no longer match current truth
When the orchestrator calls `telec todo work my-feature`
Then derive_lifecycle_drift reports drift.implementation-plan = pending
And the machine does NOT advance lifecycle_phase
And the machine does NOT create or touch the worktree
And the machine returns an orchestrator script saying "Drift detected on implementation-plan. Call `telec todo prepare my-feature` to resolve."
And the orchestrator follows the script verbatim
And the prepare BLOCKED branch dispatches the next-drift-analyze worker
And on cosmetic verdict the prepare machine reaches PREPARED again and its terminal script tells the orchestrator to call `telec todo work my-feature`
And on substantive verdict the prepare machine clears the affected review verdicts and re-derives through draft → review → PREPARED, then the same terminal script bounces work
And work re-runs derive_lifecycle_drift, observes fresh / valid-anchor status, and proceeds with worktree creation and dispatch
```

```
Given a Todo at lifecycle_phase=build_started with a live builder session
When the orchestrator calls `telec todo work my-feature` while the builder is still active
Then the machine refuses to dispatch a second builder
And returns an instruction to wait for the builder to run `telec todo stamp my-feature --build-complete`
```

```
Given a Todo whose builder has Stamped build-complete and committed its work
When the orchestrator calls `telec todo work my-feature`
Then the machine runs the build gates against the worktree
And on pass advances lifecycle_phase to build_complete and dispatches the next-review-build worker
And on fail relays the gate output back to the live builder session via `telec sessions send`
And does NOT advance the lifecycle_phase until the builder restamps build-complete with a passing gate
```

```
Given a Todo at lifecycle_phase=build_complete whose reviewer Stamped verdict=changes_requested
When the orchestrator calls `telec todo work my-feature`
Then the machine advances lifecycle_phase to review_changes_requested
And relays the review-findings to the live builder session via the reviewer's direct-fix message
And refuses to dispatch a fresh reviewer until the builder restamps build-complete from the new HEAD
And on every re-review round the reviewer is re-dispatched against the merge-base diff, not the full diff
```

```
Given a Todo at lifecycle_phase=review_approved with no pending deferrals
When the orchestrator calls `telec todo work my-feature`
Then the machine dispatches the next-finalize worker
And when the finalizer Stamps finalize_ready with a sha matching worktree HEAD, branch ref, and remote ref
Then the machine advances to lifecycle_phase=finalize_ready through the TodosDb write boundary
And the phase-transition chokepoint emits the todo_finalize_ready integration event
And worker-session cleanup happens inside the finalize_ready step
And on any triple-ref mismatch (uncommitted, branch≠HEAD, remote≠local, stamped sha≠HEAD) refuses to advance and instructs the operator to re-stamp
```

```
Given an operator uses reconcile or mark-phase to land lifecycle_phase=finalize_ready through an owned TodosDb write
When the state write commits
Then the same TodosDb phase-transition chokepoint emits todo_finalize_ready
And the IntegrationTriggerCartridge treats it the same as the normal work-machine path
```

```
Given a Todo is already at lifecycle_phase=finalize_ready
When the same phase value is written again
Then the TodosDb phase-transition chokepoint suppresses emission
And no duplicate integrator spawn is requested for that rewrite
```

```
Given two orchestrator sessions in the same project call `telec todo work my-feature` concurrently
When both calls reach the worktree-ensure boundary
Then the (project_root, my-feature) asyncio lock serializes them
And the second call observes the prepared worktree and reuses it
And the same slug called concurrently from a different project root acquires a separate lock and runs in parallel
```

```
Given a bug-kind Todo at lifecycle_phase=build_started
When the orchestrator calls `telec todo work my-bug`
Then the machine dispatches the next-bugs-fix worker instead of next-build
And the BUG-FIX artifact contract is included in the worker note
And the lifecycle still requires an explicit `telec todo stamp my-bug --build-complete` before review can dispatch
```

### Implementation pointers (v1)

- `teleclaude/core/next_machine/work.py:102` — `next_work()` orchestration entry. The implementation plan must reorder this function so the state read and `derive_lifecycle_drift` call happen AFTER slug resolution and non-worktree preconditions but BEFORE `_ensure_worktree_ready` (currently at work.py:130). On `pending` or `substantive` collapsed status for any tracked artifact, return the bounce-to-prepare script via existing output-formatting helpers without calling `_ensure_worktree_ready`, without merging origin/main, without entering the dispatch loop, and without mutating work state. The `derive_lifecycle_drift` function is renamed from `derive_prepare_drift` in `lifecycle.py`.
- `teleclaude/core/next_machine/work.py:55` — `_SINGLE_FLIGHT_LOCKS` registry keyed per `(canonical_cwd, slug)`.
- `teleclaude/core/next_machine/work.py:60` — `_get_slug_single_flight_lock()` canonicalizes cwd then takes the per-pair lock.
- `teleclaude/core/next_machine/work.py:218` — `_advance_prepared_to_build_started()` machine-owned handoff applied on first work entry.
- `teleclaude/core/next_machine/work.py:151` — dispatch loop bounded by `_WORK_LOOP_LIMIT`.
- `teleclaude/core/next_machine/work.py:72` — `_log_next_work_phase()` emits the `NEXT_WORK_PHASE` markers with decision / reason / duration_ms.
- `teleclaude/core/next_machine/work.py:390` — `_ensure_worktree_ready()` ensure-prepare boundary invoked under the single-flight lock; surfaces `unexpected_<ExceptionType>` on failures.
- `teleclaude/core/next_machine/work_steps.py:702` — `_work_dispatch()` table dispatching to per-Phase handlers.
- `teleclaude/core/next_machine/work_steps.py:194` — `_work_step_build_started` builder dispatch + build-gate-claim consumption.
- `teleclaude/core/next_machine/work_steps.py:260` — `_work_step_build_complete` reviewer dispatch, re-review baseline scoping, round limit.
- `teleclaude/core/next_machine/work_steps.py:484` — `_handle_finalize_ready_claim()` triple-ref consistency check; manual event emission is not performed here.
- `teleclaude/core/todos_db/_base.py:323` — `notify_phase_transition()` callback surface for committed lifecycle phase writes.
- `teleclaude/core/todos_db/_state.py:150` — `write_state()` / `write_state_sync()` post-commit phase-transition chokepoint.
- `teleclaude/daemon.py:499` — daemon translator from `* → finalize_ready` phase transition to `domain.software-development.planning.todo_finalize_ready`.
- `teleclaude/core/next_machine/_types.py:78` — `WorkPhase` enum, the canonical phase set; `HANDED_OFF` is not a member.
- `teleclaude/core/next_machine/_types.py:114` — `_WORK_LOOP_LIMIT = 10` in-call iteration bound.
- `teleclaude/core/next_machine/worktrees.py:111` — `_create_or_attach_worktree()` branches from `origin/main` as the single source of truth.
- `teleclaude/api/todo_routes.py:162` — `POST /todos/work` HTTP entrypoint preserving caller `session_id` for finalize ownership.

### Cross-context references

- `agent_runtime` — every dispatch instruction is a verbatim `telec sessions run` script that spawns a builder, bugs-fixer, reviewer, deferrals worker, or finalizer session.
- `integration` — on any owned write that lands `lifecycle_phase=finalize_ready`, the TodosDb chokepoint emits `domain.software-development.planning.todo_finalize_ready` (event in the workflow domain). `IntegrationTriggerCartridge` dedups by `(slug, sha, worker_session_id)` before spawning the singleton integrator; the periodic scanner remains the safety net for daemon-down or caller-owned transaction paths.
- `session_ledger` — the caller's `session_id` is propagated through the HTTP entry into `next_work`, recorded on the finalize state, and used by the peer-conversation contract that lets the reviewer relay findings directly to the live builder/fixer.

## Known caveats

- Worktrees branch from `origin/main`, not the local `main`, so the slug's todo artifacts must already exist on `origin/main` before worktree creation; a local-only artifact will not be visible inside the worktree.
- A holder Todo cannot itself enter work. The orchestrator is always routed to its direct, runnable children via the same holder-resolution helpers prepare uses.
- The single-flight lock is per `(canonical project root, slug)`. Same slug in a different repo runs independently — this is the explicit behavior, not a leak.
- Bug-kind Todos require an explicit `telec todo stamp <slug> --build-complete` even when the build session committed and exited; the machine will not advance on commit alone.
- Review round limit is not an escape hatch. Hitting it surfaces an error pointing at `review-findings`; the orchestrator must address Requirement-Violation / Critical / Important findings rather than raising the limit.
- The `_WORK_LOOP_LIMIT` of 10 internal iterations bounds in-call transitions. Hitting it means the derived Phase keeps changing without converging — fix the underlying state, do not raise the limit.
- `finalize_ready` is gated by a triple-ref check (`worktree HEAD == branch ref == remote ref`) AND the Stamped SHA must equal worktree HEAD; any mismatch refuses the transition and requires a re-stamp.
- Chokepoint emission is at-least-once at the bus layer under concurrent first-transition writers. Integrator spawning remains at-most-once for duplicate same-key events through cartridge dedup, and distinct-key races are serialized by the integration singleton lease.
- Stash debt in the project root blocks work entirely; the machine refuses to dispatch until the stash is drained, because stash state can silently reintroduce unrelated changes into the worktree branch.
- Worktree prep failures bubble up as `reason=unexpected_<ExceptionType>` in the `NEXT_WORK_PHASE` log line so the orchestrator can diagnose without round-tripping through daemon logs.
