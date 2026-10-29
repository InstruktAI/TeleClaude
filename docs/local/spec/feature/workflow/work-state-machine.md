---
description: 'Phase B state machine driving a prepared Todo through build → review → fix → terminal finalize_ready inside a per-slug worktree, with a single-flight lock per (project_root, slug) and caller-session ownership for finalize.'
visibility: 'public'
---

# Work State Machine — Spec

## What it is

The work state machine is the workflow capability that drives a prepared Todo through Phase B — `prepared` → `build_started` → `build_complete` → `review_changes_requested` (zero-or-more loops) → `review_approved` → terminal `finalize_ready`. Each call by the orchestrator reads the authoritative `lifecycle_phase`, dispatches the matching Phase handler, and returns a verbatim instruction telling the orchestrator what to do next — dispatch a builder, dispatch a reviewer, relay findings to an already-live builder, dispatch a finalizer, or perform terminal worker-session cleanup. Integration emission is owned by the workflow service's phase-transition chokepoint when an owned write lands `lifecycle_phase=finalize_ready`. Build-review verdicts (`approve` | `changes_requested`) drive transitions between build, fix, and finalize; prepare-review vocabulary (`approve` | `needs_work` | `needs_decision`) is unchanged and applies only to the prepare phases.

The work orchestrator is scoped to one current slug. It does not select
unrelated follow-up work after the slug reaches `finalize_ready`; the terminal
finalize-ready instruction ends the slug's workers and then ends the
orchestrator session. Daemon-runner pickup is a separate concern outside this
per-slug orchestration contract.

Task execution is a separate non-SDLC lane. The lifecycle runner starts `sdlc/procedure/lifecycle/task/run-task <slug>` for a prepared, authorized task; the Phase B build/review/finalize machine does not handle task execution and does not create a worktree. `sdlc/procedure/lifecycle/task/run-task` reads and grooms `task-plan`, performs the authorized work, records results in the task-plan, and ends on a `success` firing — a recurring task is re-run as a fresh `sdlc/procedure/lifecycle/task/run-task` at its next due instant — while an `error` firing stays alive for human follow-up; it never self-ends through finalize-ready cleanup.

<!-- planned:task-firing-timestamp-line -->

Each task firing records when it started. The session running a firing stamps
its start (`--task-firing-started`,
`local/projects/teleclaude/spec/feature/workflow/state-stamping`) before it reads
the task's `log`: a fresh `sdlc/procedure/lifecycle/task/run-task` session as its
first act, and a session that takes a task up by hand to run the firing in place
as the first act of that firing. The stamp appends exactly one line,
`[HH:MM:SS-DD/MM] execution`, to the end of the task's `log`. The line carries the
stamp's instant from the system clock as 24-hour time and day/month in the
computer's configured timezone (`computer.timezone`,
`local/projects/teleclaude/spec/teleclaude-config`). A session that never begins
its firing appends nothing, and a session's further firing-start stamps on the
same task append nothing. A failed stamp leaves the firing running with at most one line.
The `log`'s only writers are therefore the firing's own session and the stamp it
invokes, in that session's order; the platform writes no other part of the `log`,
and the run session carries every firing line verbatim
(`sdlc/procedure/lifecycle/task/run-task`).

<!-- /planned:task-firing-timestamp-line -->

Work is the first stage that materializes a per-slug worktree under `trees/<slug>`, branched from `origin/main` so the worktree baseline is a single source of truth shared by every concurrent worker. `origin/main` is also the only baseline the worktree references afterwards: an agent inside `trees/<slug>` does not name the local `main` branch in any git invocation, for any subcommand. A single-flight lock keyed per `(canonical_project_root, slug)` makes same-slug calls in the same repo wait and reuse the prepared worktree, while same-slug calls in different repos remain fully independent. The caller's session identity is preserved across phase handlers so the finalize Phase records who owns the handoff. A loop guard bounds in-call internal transitions, every Phase emits a grep-friendly log line with decision and duration, and worktree prep failures surface as `unexpected_<ExceptionType>` reasons so the orchestrator can diagnose without inspecting daemon logs.

Before the `prepared → build_started` handoff and BEFORE worktree preparation, work calls the shared drift derivation (the same function the prepare state machine uses; see `@spec/feature/workflow/drift-detection`). The state read that drives the derivation happens ahead of worktree creation: slug resolution and non-worktree preconditions happen first, then the workflow state is read, then drift derivation is called against repo-root state. The work state machine owns the work-entry drift path end-to-end. When a tracked artifact's collapsed drift status is `pending`, work does NOT mutate work-state and does NOT create or touch a worktree; its bounce returns a script that dispatches the `sdlc/procedure/lifecycle/prepare/drift-analyze` worker and tells the orchestrator to re-enter `telec todo work {slug}` once the analyzer idles — this path never enters the prepare machine. The analyzer stamps its `--drift-reviewed` verdict and drives no transition. For bug-kind Todos, work-entry drift evaluates the approved `implementation-plan`; bug `input` is frozen, and `diagnosis` is consumed only through the plan's upstream diagnosis digest. Work entry never bounces directly on `input` or `diagnosis` drift. On re-entry the work machine reads the stamped verdict. A `cosmetic` verdict is non-blocking: work proceeds to worktree creation and build dispatch. A `substantive` verdict returns the Todo to preparation through the lifecycle runner: the work machine releases the Todo's lifecycle claim, and the platform ends the slug's work-lane sessions — every session the calling work orchestrator started, then the work orchestrator itself — only after the machine has answered the orchestrator's call. The worktree, local and remote branch, workspace directory, and build commits remain. No session changes lanes: the lifecycle runner dispatches a fresh prepare orchestrator, which re-derives the affected artifact; at `prepared` that orchestrator ends like any other and releases the claim, and the lifecycle runner dispatches a fresh work orchestrator, which continues the existing build against the changed plan (UC-WSM10). Neither lifecycle machine adopts a session that holds the slug in the other lane; each refuses it instead. The cosmetic path attempts no artifact write, so it never contends with the write-authority guard.

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
And on the same call dispatches the sdlc/procedure/lifecycle/work/build worker session
```

```gherkin
Given a Todo has a live sdlc/procedure/lifecycle/work/build session for its worktree
And `telec todo work` merges origin/main into that worktree before dispatch/review
When the merge fails with conflicts
Then `telec todo work` returns a recovery handoff for the orchestrator
And the orchestrator sends the live builder the merge-conflict recovery instructions
And the recovery message says origin/main is the leading baseline
And the builder reapplies the prepared todo intent on top, resolves conflicts, verifies, commits, and stamps build-complete
And the orchestrator re-enters `telec todo work` after the builder idles so the workflow continues from the recovered HEAD
```

```gherkin
Given a Todo is already at lifecycle_phase=build_complete
And `telec todo work` merges origin/main into that worktree before dispatching review
When the merge fails with conflicts
Then `telec todo work` returns a recovery handoff for the orchestrator
And the orchestrator sends the live builder the merge-conflict recovery instructions
And the builder resolves conflicts, verifies, commits, and reports MERGE RECOVERY COMPLETE
And the orchestrator re-enters `telec todo work` after the builder idles so review can proceed from the recovered HEAD
```

```
Given a Todo at lifecycle_phase=prepared whose plan artifact's owned-snippet digests no longer match current truth
When the orchestrator calls "telec todo work my-feature"
Then drift derivation reports drift.implementation-plan = pending
And the machine does NOT advance lifecycle_phase
And the machine does NOT create or touch the worktree
And the machine returns a script that dispatches the sdlc/procedure/lifecycle/prepare/drift-analyze worker and tells the orchestrator to re-enter "telec todo work my-feature" once the analyzer idles
And the work orchestrator never calls "telec todo prepare my-feature"
And on re-entry after a cosmetic verdict the machine observes non-blocking drift and proceeds with worktree creation and dispatch
And on re-entry after a substantive verdict the work machine releases the Todo's lifecycle claim and the platform ends the work orchestrator and every session it started
And the lifecycle runner dispatches a fresh prepare orchestrator, which re-derives the affected artifact with no 403 write refusal and no 409 claim conflict, and reaches prepared
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

#### UC-WSM5: A substantive work-entry drift verdict returns the Todo to preparation through the lifecycle runner

```gherkin
Given a work-entry drift bounce dispatched the sdlc/procedure/lifecycle/prepare/drift-analyze worker for a slug whose lifecycle claim the calling work orchestrator holds
And that work orchestrator has started worker sessions for the slug
When the analyzer stamps a substantive --drift-reviewed verdict and the work orchestrator re-enters "telec todo work my-feature"
Then the work machine releases the Todo's lifecycle claim
And the platform ends every session the work orchestrator started, then the work orchestrator itself, without any agent ending them
And the work orchestrator's own session ends only after the machine has answered its call
And the worktree, local and remote branch, workspace directory, and build commits remain
And the lifecycle runner then dispatches a fresh prepare orchestrator for the Todo under its normal dispatch policy
And no human is notified
```

```
Given a Todo at lifecycle_phase=build_started with a live builder session
When the orchestrator calls "telec todo work my-feature" while the builder is still active
Then the machine refuses to dispatch a second builder
And returns an instruction to wait for the builder to run "telec todo stamp my-feature --build-complete"
```

#### UC-WSM4: Task execution uses run-task, not Phase B build

```gherkin
Given a Todo has kind="task", lifecycle_phase="prepared", a `task-plan`, and a task authorization stamp
And the task has no schedule, or its schedule's current due instant is at or before the runner evaluation instant
When the lifecycle runner evaluates eligible work for the project
Then it starts `sdlc/procedure/lifecycle/task/run-task <slug>` without creating a worktree
And records the spawned task session as the Todo's `active_runner`
And no reservation, expiry, or other pre-ownership state participates
And records or preserves lifecycle_phase="task_running" while the task session is live
```

```gherkin
Given a task lacks authorization, lacks a `task-plan`, has a future schedule, is held, or already names a live task session as `active_runner`
When the lifecycle runner evaluates eligible work for the project
Then it does not start `sdlc/procedure/lifecycle/task/run-task`
And it leaves the SDLC work state machine untouched
```

```gherkin
Given `sdlc/procedure/lifecycle/task/run-task` reaches the end of the task-plan
When it stamps the firing outcome
Then a `success` firing ends the session — a one-shot delivers the todo, a recurring records the firing and leaves the todo live for its next instant
And an `error` firing holds the todo and stays alive as the human-inspection beacon
And it does not stamp build-complete, dispatch review, or enter finalize-ready
```

```gherkin
Given a recurring task has a live `sdlc/procedure/lifecycle/task/run-task` session and its schedule reaches a new due instant
When the lifecycle runner evaluates eligible work for the project
Then it does not start a second `sdlc/procedure/lifecycle/task/run-task`
And it does not signal the live run session
```

```gherkin
Given a recurring task has no live `sdlc/procedure/lifecycle/task/run-task` session and its schedule reaches a due instant
When the lifecycle runner evaluates eligible work for the project
Then it dispatches a fresh `sdlc/procedure/lifecycle/task/run-task`, exactly like a one-shot
```

```
Given a Todo whose builder has Stamped build-complete and committed its work
When the orchestrator calls "telec todo work my-feature"
Then the machine runs the build gates against the worktree
And on pass advances lifecycle_phase to build_complete and dispatches the sdlc/procedure/lifecycle/work/review-build worker
And on fail relays the gate output back to the live builder session via "telec sessions send"
And does NOT advance the lifecycle_phase until the builder restamps build-complete with a passing gate
```

```
Given a Todo at lifecycle_phase=build_complete whose reviewer Stamped verdict=changes_requested
When the orchestrator calls "telec todo work my-feature"
Then the machine advances lifecycle_phase to review_changes_requested
And directs the orchestrator to point the live builder session at the review-findings artifact, with no message between the reviewer and the builder
And refuses to dispatch a fresh reviewer until the builder restamps build-complete from the new HEAD
And on every re-review round the reviewer is re-dispatched against the merge-base diff, not the full diff, and directed to the builder's dispositions and fix commits
```

```
Given a Todo at lifecycle_phase=review_approved with no pending deferrals
When the orchestrator calls "telec todo work my-feature"
Then the machine dispatches the sdlc/procedure/lifecycle/work/finalize worker
And when the finalizer Stamps finalize_ready with a sha matching worktree HEAD, branch ref, and remote ref
Then the machine advances to lifecycle_phase=finalize_ready through the state-write boundary
And the phase-transition chokepoint emits the todo's finalize-ready event
And worker-session cleanup happens inside the finalize_ready step
And the machine emits "telec reminders set session-departure" for the work orchestrator
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

<!-- planned:task-firing-timestamp-line -->

#### UC-WSM20: The operator reads when each task firing started

```gherkin
Given an operator's authorized task has started three firings, one after another
And one further start of it was refused before any run session existed
When the operator reads the task's log
Then the log holds exactly three "[HH:MM:SS-DD/MM] execution" lines, in the order the firings started
And each line shows its firing's start time in the computer's configured timezone
```

<!-- /planned:task-firing-timestamp-line -->

#### UC-WSM1: Bug build dispatches the build worker with the plan + diagnosis contract

```
Given a bug-kind Todo at lifecycle_phase=build_started
When the orchestrator calls "telec todo work my-bug"
Then the machine dispatches the sdlc/procedure/lifecycle/work/build worker (same as change/feature)
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
And the machine emits "telec reminders set session-departure"
And the machine does NOT select a ready todo from the roadmap
```

#### UC-WSM6: Prepared entry seeds a missing quality-checklist

```gherkin
Given a Todo at lifecycle_phase=prepared with no quality-checklist artifact or one with only whitespace/heading content
When the machine advances lifecycle_phase from prepared to build_started
Then the quality-checklist artifact exists with the standard checklist template including "## Build Gates (Builder)"
And a prepared Todo whose quality-checklist already has substantive content keeps it unchanged
```

#### UC-WSM8: Build review consumes only a current report and an unchanged todo change

```gherkin
Given a build reviewer writes `review-findings` and stamps approve or changes_requested against worktree HEAD H and report digest R
When the work orchestrator re-enters `telec todo work my-feature`
Then the machine consumes the verdict only when the current `review-findings` digest is R and the todo's own change is unchanged since H
And the todo's own change is unchanged since H when H is an ancestor of the current worktree HEAD and every commit the todo branch gained on its own line since H is a conflict-free automatic merge of origin/main whose content is exactly the automatic merge of its parents
And an absent binding, missing report, later report rewrite, or any other commit the todo branch gained since H leaves the build review pending for re-review
And when the machine cannot determine whether the todo's own change is unchanged since H, it reports that to the orchestrator and neither consumes nor revokes the verdict
And only a current approve advances to review_approved
And only a current changes_requested advances to review_changes_requested and relays the bound report to the builder
```

#### UC-WSM9: Work entry on a kicked-back Todo returns it to preparation through the lifecycle runner

```gherkin
Given a Todo whose implementation-plan review was cleared-by-substantive-drift by a kickback stamp
And that review no longer approves the current implementation-plan digest
And the Todo has a worktree with build commits and a branch
When a work orchestrator enters "telec todo work my-feature"
Then the machine recognizes the kickback before evaluating work-entry drift
And it returns the Todo to preparation exactly as a substantive work-entry drift verdict does: the claim is released and the platform ends the work orchestrator and every session it started
And the worktree, local and remote branch, workspace directory, and build commits remain
And the prepare orchestrator the lifecycle runner dispatches reads the durable kickback reason in input as re-derivation context
```

#### UC-WSM11: Finalize-ready kickback recovery returns to prepare

```gherkin
Given a Todo whose implementation-plan review was cleared-by-substantive-drift by a kickback stamp
And that review no longer approves the current implementation-plan digest
And no live driver holds the Todo
And the stored lifecycle phase is finalize_ready
When the lifecycle runner re-evaluates the Todo
Then it does not skip the Todo as an ordinary finalize-ready candidate
And it routes the Todo into the prepare lane without deleting its worktree, branches, or workspace directory
```

#### UC-WSM10: Build re-entry after a plan amendment hands the builder reconcile instructions

```gherkin
Given a Todo whose build started against one implementation-plan version and whose plan was later amended and re-approved
When the work machine re-enters the build phase
Then the dispatch to the builder carries machine-derived reconcile instructions naming the plan version the build started against and the currently approved version
And the instructions include the exact command that renders the diff between those two versions
And the instructions direct the builder to revert commits the amendment invalidates, keep commits the amended plan still requires, and continue from the amended plan
And a live builder receives the same instructions as a message instead of a second builder being dispatched
And the record of which plan version the build executes against settles only when the builder stamps build-complete under the amended plan
And a crash-recovered session re-entering the build derives identical instructions from durable state alone
```

#### UC-WSM12: Build review reports its crossed threshold once and summons no session

```gherkin
Given a Todo has admitted build-review passes up to its configured round threshold
And no approve verdict is current under UC-WSM8
When the orchestrator calls "telec todo work my-feature"
Then the machine reports the phase, admitted-pass count, threshold and current review evidence, and points the orchestrator at the shared convergence contract before another pass
And it refuses no reviewer dispatch, emits no continuation stamp, and instructs no additional session to be dispatched
And it preserves the arithmetic verdict, lifecycle phase, active runner, worktree, builder, and reviewer sessions
And a new worktree commit or review-findings rewrite does not reset the admitted-pass count
And it reports the crossing once, on the crossing pass, and not on later passes
And the admitted-pass count keeps rendering on later passes
And only a decision the closed human lane assigns to the human, or a safety gate, reaches the human
```

#### UC-WSM13: Terminal work cleanup is caller-scoped and precedes departure

```gherkin
Given a work orchestrator reaches a true terminal path at finalize-ready or without a current work slug
When the work machine emits its terminal execution script
Then the script closes every live direct child of the work orchestrator through the caller-scoped bulk session-end operation
And only after that operation succeeds does the script direct the orchestrator to end itself
And the script contains neither remembered child identifiers nor a manual child-listing loop
And non-terminal handoffs, retries, and reviews emit no bulk child cleanup
```

#### UC-WSM18: The finalize-ready handoff releases the work orchestrator's lifecycle claim

```gherkin
Given a Todo whose lifecycle claim is held by the work orchestrator session W
When W calls "telec todo work my-feature" and the machine performs the finalize-ready handoff
Then W no longer holds the lifecycle claim on my-feature
And the Todo's next owner takes it up whether or not W remains open
And the terminal script states that W no longer holds the claim on my-feature
And no claim held by a different live session is changed
```

#### UC-WSM14: Every command the work machine emits is domain-qualified

```gherkin
Given the work machine composes a build, review, fix, finalize, or drift dispatch
When it names a command in that script
Then the name is that command's canonical domain-qualified value
And the dispatch request handed to agent runtime carries that same value
```

#### UC-WSM15: A successful origin/main merge preserves all work in the todo worktree

```gherkin
Given a work orchestrator agent or finalizer agent operates a Todo worktree carrying any of uncommitted builder edits, build commits, a build-complete claim, a stamped build-review verdict, a live review, admitted review rounds, or a finalize-ready claim
When origin/main is merged into that worktree without conflicts during work entry or finalization
Then every uncommitted edit, build commit, build-complete fact, review verdict, admitted review-round count, and finalize-ready claim remains in force
And the work orchestrator agent receives no reviewer dispatch, no follow-up for its live reviewer agent, no attribution of a merge commit to its builder agent, and no request for its finalizer agent to push or re-stamp solely because of that merge
```

#### UC-WSM16:

#### UC-WSM17:

#### UC-WSM19: The work machine refuses a session that holds the slug in the prepare lane

```gherkin
Given a prepare orchestrator session P holds my-feature's lifecycle claim
When P calls "telec todo work my-feature"
Then the work machine refuses without adopting P into the work lane, and P's role, title, and claim are unchanged
And the refusal names the sanctioned path: P completes its prepare lifecycle, whose terminal releases the claim, and the lifecycle runner dispatches a fresh work orchestrator
```

### Cross-context references

- `agent_runtime` — every dispatch instruction is a verbatim `telec sessions run` script that spawns a builder, reviewer, deferrals worker, or finalizer session.

- `integration` — on any owned write that lands `lifecycle_phase=finalize_ready`, the workflow phase-transition chokepoint emits the todo's finalize-ready event. That event's id is derived from `(slug, sha, worker_session_id)`, so the consumer framework hands the integration trigger consumer each logical transition once before it spawns the singleton integrator; the periodic scanner remains the safety net for daemon-down or caller-owned transaction paths.

- `session_ledger` — the caller's session identity is propagated through the work entry and recorded on the finalize state.

- `daemon runner` — future unattended pickup may choose the next slug outside the
  work orchestrator session. The Phase B orchestrator remains per-slug and
  terminal after finalize-ready cleanup.

- `workflow.lifecycle_runner` — unattended pickup is the sole automatic selector for ready work. It evaluates the project todo set, starts `sdlc/procedure/lifecycle/work/overview --args <slug>` for each selected item, and records the spawned session as that Todo's `active_runner`. The work state machine remains per-slug: a bare `telec todo work` call without current slug terminalizes as `NO_CURRENT_WORK_SLUG` and never scans the roadmap opportunistically. A Todo that a kickback or a substantive work-entry drift verdict returned to preparation is dispatched to a fresh `sdlc/procedure/lifecycle/prepare/overview` once no live driver holds it, and, once prepared again, to a fresh `sdlc/procedure/lifecycle/work/overview` under the kind's work-lane autostart policy like any other prepared Todo; that work orchestrator continues the existing build.

## Known caveats

- Worktrees branch from `origin/main`, not the local `main`, so the slug's todo artifacts must already exist on `origin/main` before worktree creation; a local-only artifact will not be visible inside the worktree.
- A holder entry cannot itself enter work. The orchestrator is always routed to its direct, runnable children via the same holder-resolution helpers prepare uses.
- The single-flight lock is per `(canonical project root, slug)`. Same slug in a different repo runs independently — this is the explicit behavior, not a leak.
- Bug-kind Todos require an explicit `telec todo stamp <slug> --build-complete` even when the build session committed and exited; the machine will not advance on commit alone.
- The review threshold is not an escape hatch. Crossing it points at `review-findings` and the shared convergence contract; the orchestrator must address Requirement-Violation / Critical / Important findings rather than moving the threshold.
- The work loop limit bounds in-call transitions. Hitting it means the derived Phase keeps changing without converging — fix the underlying state, do not raise the limit.
- `finalize_ready` is gated by a triple-ref check (`worktree HEAD == branch ref == remote ref`) AND the Stamped SHA must equal worktree HEAD; any mismatch refuses the transition and requires a re-stamp.
- Chokepoint emission is at-least-once at the bus layer under concurrent first-transition writers. Integrator spawning remains at-most-once for duplicate same-key events through cartridge dedup, and distinct-key races are serialized by the integration singleton lease.
- Stash debt in the project root blocks work entirely; the machine refuses to dispatch until the stash is drained, because stash state can silently reintroduce unrelated changes into the worktree branch.
- Worktree prep failures bubble up as `reason=unexpected_<ExceptionType>` in the log line so the orchestrator can diagnose without round-tripping through daemon logs.
