---
description: 'Phase B state machine driving a prepared Todo through build → review → fix → terminal finalize_ready inside a per-slug worktree, with a single-flight lock per (project_root, slug) and caller-session ownership for finalize.'
visibility: 'public'
---

# Work State Machine — Spec

## Required reads

- @~/.teleclaude/docs/software-development/principle/domain-driven-design.md
- @~/.teleclaude/docs/software-development/spec/domain-spec.md
- @docs/project/spec/domain/workflow.md

## What it is

The work state machine is the workflow capability that drives a prepared Todo through Phase B — `prepared` → `build_started` → `build_complete` → `review_changes_requested` (zero-or-more loops) → `review_approved` → terminal `finalize_ready`. Each call by the orchestrator reads the authoritative `lifecycle_phase`, dispatches the matching Phase handler, and returns a verbatim instruction telling the orchestrator what to do next — dispatch a builder, dispatch a reviewer, relay findings to an already-live builder, dispatch a finalizer, or perform terminal worker-session cleanup. Integration emission is owned by the workflow service's phase-transition chokepoint when an owned write lands `lifecycle_phase=finalize_ready`. Build-review verdicts (`approve` | `changes_requested`) drive transitions between build, fix, and finalize; prepare-review vocabulary (`approve` | `needs_work` | `needs_decision`) is unchanged and applies only to the prepare phases.

The work orchestrator is scoped to one current slug. It does not select
unrelated follow-up work after the slug reaches `finalize_ready`; the terminal
finalize-ready instruction ends the slug's workers and then ends the
orchestrator session. Daemon-runner pickup is a separate concern outside this
per-slug orchestration contract.

<!-- planned:task-lane -->

Task execution is a separate non-SDLC lane. The lifecycle runner starts `/next-run-task <slug>` for a prepared, authorized task; the Phase B build/review/finalize machine does not handle task execution and does not create a worktree. `/next-run-task` reads and grooms `task-plan`, performs the authorized work, records results in the task-plan, and stays alive for human follow-up instead of self-ending through finalize-ready cleanup.

<!-- /planned:task-lane -->

Work is the first stage that materializes a per-slug worktree under `trees/<slug>`, branched from `origin/main` so the worktree baseline is a single source of truth shared by every concurrent worker. A single-flight lock keyed per `(canonical_project_root, slug)` makes same-slug calls in the same repo wait and reuse the prepared worktree, while same-slug calls in different repos remain fully independent. The caller's session identity is preserved across phase handlers so the finalize Phase records who owns the handoff — the peer-conversation contract that lets builders and reviewers iterate directly without context-destroying churn. A loop guard bounds in-call internal transitions, every Phase emits a grep-friendly log line with decision and duration, and worktree prep failures surface as `unexpected_<ExceptionType>` reasons so the orchestrator can diagnose without inspecting daemon logs.

Before the `prepared → build_started` handoff and BEFORE worktree preparation, work calls the shared drift derivation (the same function the prepare state machine uses; see `@spec/feature/workflow/drift-detection`). The state read that drives the derivation happens ahead of worktree creation: slug resolution and non-worktree preconditions happen first, then the workflow state is read, then drift derivation is called against repo-root state. When any tracked artifact's collapsed drift status is `pending` or `substantive`, work does NOT mutate work-state, does NOT create or touch a worktree on this call, and does NOT dispatch any worker; it returns an orchestrator script telling the caller to run `telec todo prepare {slug}` to resolve drift. For bug-kind Todos, work-entry drift evaluates the approved `implementation-plan`; bug `input` is frozen, and `diagnosis` is consumed only through the plan's upstream diagnosis digest. Work entry never bounces directly on `input` or `diagnosis` drift. The prepare flow's existing BLOCKED branch routes the drift analyzer; when prepare reaches `prepared` again, its terminal's lineage-conditioned resume reminder has the bounced work orchestrator resume `telec todo work {slug}` (a fresh prepare that never bounced self-ends instead). The continuation across the bounce is the existing script-driven contract — no new mechanism, no human gate on cosmetic verdicts, and substantive verdicts cascade through the existing re-derivation chain back into a prepared Todo.

## Canonical fields

### Use cases

#### UC-WSM0: Prepared entry starts build work

```
Given a Todo at lifecycle_phase=prepared with no worktree
When the orchestrator calls "telec todo work my-feature"
Then the machine acquires the (project_root, my-feature) single-flight lock
And calls drift derivation against current evidence
And every tracked artifact's collapsed drift status is fresh or cosmetic with a valid anchor
And creates a worktree at trees/my-feature branched from origin/main
And merges origin/main into the worktree once before dispatch
And advances lifecycle_phase from prepared to build_started in a machine-owned transition
And on the same call dispatches the next-build worker session
```

```gherkin
Given a Todo has a live next-build session for its worktree
And the work state machine merges origin/main into that worktree before dispatch/review
When the merge fails with conflicts
Then the machine returns a recovery script that sends the merge failure to the live builder
And the recovery message says origin/main is the leading baseline
And the recovery message asks the builder to reapply the prepared todo intent on top, resolve conflicts, rerun gates, commit, and restamp build-complete
And the machine does not leave the orchestrator to treat the recoverable merge failure as a passive human blocker
```

```
Given a Todo at lifecycle_phase=prepared whose plan artifact's owned-snippet digests no longer match current truth
When the orchestrator calls "telec todo work my-feature"
Then drift derivation reports drift.implementation-plan = pending
And the machine does NOT advance lifecycle_phase
And the machine does NOT create or touch the worktree
And the machine returns an orchestrator script saying "Drift detected on implementation-plan. Call `telec todo prepare my-feature` to resolve."
And the orchestrator follows the script verbatim
And the prepare BLOCKED branch dispatches the next-drift-analyze worker
And on cosmetic verdict the prepare machine reaches PREPARED again and its terminal's lineage-conditioned reminder resumes the bounced work orchestrator at "telec todo work my-feature"
And on substantive verdict the prepare machine clears the affected review verdicts and re-derives through draft → review → PREPARED, then the same lineage-conditioned reminder resumes work
And work re-runs drift derivation, observes fresh / valid-anchor status, and proceeds with worktree creation and dispatch
```

```gherkin
Given a bug-kind Todo at lifecycle_phase=prepared with an approved implementation-plan
And the bug has input and diagnosis artifacts
When the orchestrator calls "telec todo work my-bug"
Then work-entry drift evaluates implementation-plan
And work-entry drift does not evaluate input as a tracked artifact
And work-entry drift does not evaluate diagnosis as a tracked artifact
And the machine never returns WORK_ENTRY_DRIFT for drift.input or drift.diagnosis
```

```
Given a Todo at lifecycle_phase=build_started with a live builder session
When the orchestrator calls "telec todo work my-feature" while the builder is still active
Then the machine refuses to dispatch a second builder
And returns an instruction to wait for the builder to run "telec todo stamp my-feature --build-complete"
```

<!-- planned:task-lane -->

#### UC-WSM4: Task execution uses next-run-task, not Phase B build

```gherkin
Given a Todo has kind="task", lifecycle_phase="prepared", a `task-plan`, and a task authorization stamp
And the task has no datetime, or its datetime is at or before the runner evaluation instant
When the lifecycle runner evaluates eligible work for the project
Then it acquires a `(project, slug, task-run)` dispatch claim
And starts `/next-run-task <slug>` without creating a worktree
And records or preserves lifecycle_phase="task_running" while the task session is live
```

```gherkin
Given a task lacks authorization, lacks a `task-plan`, has a future datetime, is held, or already has a live task-run session/claim
When the lifecycle runner evaluates eligible work for the project
Then it does not start `/next-run-task`
And it leaves the SDLC work state machine untouched
```

```gherkin
Given `/next-run-task` reaches the end of the task-plan
When it has recorded results in the `task-plan`
Then the task session stays alive for human follow-up
And it does not self-end, stamp build-complete, dispatch review, or enter finalize-ready
```

<!-- /planned:task-lane -->

```
Given a Todo whose builder has Stamped build-complete and committed its work
When the orchestrator calls "telec todo work my-feature"
Then the machine runs the build gates against the worktree
And on pass advances lifecycle_phase to build_complete and dispatches the next-review-build worker
And on fail relays the gate output back to the live builder session via "telec sessions send"
And does NOT advance the lifecycle_phase until the builder restamps build-complete with a passing gate
```

```
Given a Todo at lifecycle_phase=build_complete whose reviewer Stamped verdict=changes_requested
When the orchestrator calls "telec todo work my-feature"
Then the machine advances lifecycle_phase to review_changes_requested
And relays the review-findings to the live builder session via the reviewer's direct-fix message
And refuses to dispatch a fresh reviewer until the builder restamps build-complete from the new HEAD
And on every re-review round the reviewer is re-dispatched against the merge-base diff, not the full diff
```

```
Given a Todo at lifecycle_phase=review_approved with no pending deferrals
When the orchestrator calls "telec todo work my-feature"
Then the machine dispatches the next-finalize worker
And when the finalizer Stamps finalize_ready with a sha matching worktree HEAD, branch ref, and remote ref
Then the machine advances to lifecycle_phase=finalize_ready through the state-write boundary
And the phase-transition chokepoint emits the workflow.todo.phase_advanced event (with phase=finalize_ready in payload)
And worker-session cleanup happens inside the finalize_ready step
And the machine emits "telec sessions end self" for the work orchestrator
And the machine does NOT instruct the orchestrator to call "telec todo work my-feature" again
And the machine does NOT instruct the orchestrator to continue to unrelated work
And on any triple-ref mismatch (uncommitted, branch≠HEAD, remote≠local, stamped sha≠HEAD) refuses to advance and instructs the operator to re-stamp
```

```
Given a Todo is already at lifecycle_phase=finalize_ready
When the same phase value is written again
Then the phase-transition chokepoint suppresses emission
And no duplicate integrator spawn is requested for that rewrite
```

```
Given two orchestrator sessions in the same project call "telec todo work my-feature" concurrently
When both calls reach the worktree-ensure boundary
Then the (project_root, my-feature) single-flight lock serializes them
And the second call observes the prepared worktree and reuses it
And the same slug called concurrently from a different project root acquires a separate lock and runs in parallel
```

#### UC-WSM1: Bug build dispatches the next-build worker with the plan + diagnosis contract

```
Given a bug-kind Todo at lifecycle_phase=build_started
When the orchestrator calls "telec todo work my-bug"
Then the machine dispatches the next-build worker (same as change/feature)
And the artifact contract names the reviewed implementation-plan and the diagnosis as the worker's mandate
And the lifecycle still requires an explicit "telec todo stamp my-bug --build-complete" before review can dispatch
```

#### UC-WSM2: Explicit work rejects unknown slugs without creating roadmap rows

```gherkin
Given no active or iceboxed Todo exists for "unknown-work"
When the orchestrator runs "telec todo work unknown-work"
Then the work machine returns TODO_NOT_FOUND with a concrete todo-create next step
And no roadmap row is created for "unknown-work"
```

#### UC-WSM3: Bare work call terminalizes instead of selecting unrelated work

```gherkin
Given a work orchestrator has no current slug
When the orchestrator runs "telec todo work"
Then the work machine returns NO_CURRENT_WORK_SLUG
And the machine emits "telec sessions end self"
And the machine does NOT select a ready todo from the roadmap
```

### Cross-context references

- `agent_runtime` — every dispatch instruction is a verbatim `telec sessions run` script that spawns a builder, reviewer, deferrals worker, or finalizer session.
- `integration` — on any owned write that lands `lifecycle_phase=finalize_ready`, the workflow phase-transition chokepoint emits `workflow.todo.phase_advanced` (with `phase=finalize_ready` in payload). `IntegrationTriggerCartridge` dedups by `(slug, sha, worker_session_id)` before spawning the singleton integrator; the periodic scanner remains the safety net for daemon-down or caller-owned transaction paths.
- `session_ledger` — the caller's session identity is propagated through the work entry, recorded on the finalize state, and used by the peer-conversation contract that lets the reviewer relay findings directly to the live builder.
- `daemon runner` — future unattended pickup may choose the next slug outside the
  work orchestrator session. The Phase B orchestrator remains per-slug and
  terminal after finalize-ready cleanup.

- `workflow.lifecycle_runner` — unattended pickup is the sole automatic selector
  for ready work. It evaluates the project todo set, acquires a
  `(canonical_project_root, slug, work)` dispatch claim, verifies no live
  `/next-work` session already owns that project/slug/lane, and then starts
  `/next-work --args <slug>`. The work state machine remains per-slug: a bare
  `telec todo work` call without current slug terminalizes as `NO_CURRENT_WORK_SLUG`
  and never scans the roadmap opportunistically.

## Known caveats

- Worktrees branch from `origin/main`, not the local `main`, so the slug's todo artifacts must already exist on `origin/main` before worktree creation; a local-only artifact will not be visible inside the worktree.
- A holder entry cannot itself enter work. The orchestrator is always routed to its direct, runnable children via the same holder-resolution helpers prepare uses.
- The single-flight lock is per `(canonical project root, slug)`. Same slug in a different repo runs independently — this is the explicit behavior, not a leak.
- Bug-kind Todos require an explicit `telec todo stamp <slug> --build-complete` even when the build session committed and exited; the machine will not advance on commit alone.
- Review round limit is not an escape hatch. Hitting it surfaces an error pointing at `review-findings`; the orchestrator must address Requirement-Violation / Critical / Important findings rather than raising the limit.
- The work loop limit bounds in-call transitions. Hitting it means the derived Phase keeps changing without converging — fix the underlying state, do not raise the limit.
- `finalize_ready` is gated by a triple-ref check (`worktree HEAD == branch ref == remote ref`) AND the Stamped SHA must equal worktree HEAD; any mismatch refuses the transition and requires a re-stamp.
- Chokepoint emission is at-least-once at the bus layer under concurrent first-transition writers. Integrator spawning remains at-most-once for duplicate same-key events through cartridge dedup, and distinct-key races are serialized by the integration singleton lease.
- Stash debt in the project root blocks work entirely; the machine refuses to dispatch until the stash is drained, because stash state can silently reintroduce unrelated changes into the worktree branch.
- Worktree prep failures bubble up as `reason=unexpected_<ExceptionType>` in the log line so the orchestrator can diagnose without round-tripping through daemon logs.
