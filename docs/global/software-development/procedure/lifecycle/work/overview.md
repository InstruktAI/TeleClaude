---
description: 'Work stage overview. Build, review, fix, finalize cycle driven by the work state machine.'
activation_trigger: 'Use when asked to become the work orchestrator for a todo or drive telec todo work through build, review, fix, and finalize handoff.'
visibility: 'public'
---

# Work Overview — Procedure

## Required reads

- @~/.teleclaude/docs/general/principle/session-lifecycle.md
- @~/.teleclaude/docs/general/concept/orchestrator.md
- @~/.teleclaude/docs/general/concept/agent-characteristics.md
- @~/.teleclaude/docs/general/procedure/orchestration.md
- @~/.teleclaude/docs/software-development/procedure/lifecycle/overview.md

## Goal

Drive the work state machine (`telec todo work`) through the build-review-fix-finalize
cycle until the todo is delivered or blocked. The orchestrator dispatches workers as
instructed by the state machine and supervises their progress.

### The doc layer is frozen — prepare authors, work executes

<!-- planned-change:state-validated-checkpoints-and-watcher-owned-deploy -->

Prepare is the only lifecycle phase that authors doc snippets, on `main`,
serialized by `telec sync`. From PREPARED onward the doc layer is frozen for the
<!-- change:state-validated-checkpoints-and-watcher-owned-deploy -->

Prepare is the only lifecycle phase that authors doc snippets, on `main`, with
publication serialized by the watcher. From PREPARED onward the doc layer is frozen for the
<!-- /planned-change:state-validated-checkpoints-and-watcher-owned-deploy -->

slug: no work-phase session — builder, reviewer, fixer, or finalizer — writes
under `docs/**` in the slug worktree. The slug's doc reflection already exists
as pending markers authored at prepare; the integrator folds them at delivery.
A doc need discovered mid-build (a missing scenario, a wrong planned contract)
is a plan defect: surface it and route through the kickback path (Step 8) so
prepare re-derives on `main` — never edit `docs/**` in the worktree.

## Preconditions

- Target slug has completed preparation (state: PREPARED).
- `telec todo artifacts read {slug} implementation-plan` exists and is approved.
- Feature work additionally carries an approved `prd`; its optional
  `architecture` artifact is approved or explicitly skipped.
- Bug work additionally carries a settled `diagnosis`.
- Worktree is available or can be created for the slug.

## Steps

### 1. Enter the state machine

Call `telec todo work {slug}` for the current slug. Read the returned instruction
block and execute it. The work orchestrator is scoped to that slug only; it does
not continue into unrelated work after the slug reaches a terminal handoff.

If the slug resolves to a holder, execute only the direct child commands the
machine returns. Before dispatching a worker for a child, read that child's
`implementation-plan` (with `prd`, optional `architecture`, and in-scope
feature-spec scenarios as context). Never read holder artifacts as executable
work input.

When the state machine instructs a dispatch, select `--mode`:

- **Builders and fixers**: `med` (well specced out plan should not require slow mode).
- **Reviewers**: `med`. A lifecycle build review is not a doc-snippet-only review.
- **Finalizers**: `fast`.

### 2. Build

The state machine dispatches a builder worker via `next-build`. The builder:

- Executes the implementation plan task-by-task
- Commits per task
- Reports BUILD COMPLETE when done

When the builder is ready for review, it stamps
`telec todo stamp [slug] --build-complete`. The orchestrator then calls
`telec todo work [slug]` again. The work state machine reads the stored
`lifecycle_phase` and dispatches the next step. Git commits and build gates are
evidence only; they do not advance the phase on their own.

### 3. Review

After build completes, the state machine dispatches a reviewer via `next-review-build`
and records the exact HEAD under review. While that reviewer is still alive, the state
machine must reuse it instead of dispatching a second reviewer. On the next
`telec todo work` call the machine first checks whether a live reviewer already owns
the slug. If so, it either keeps waiting on that reviewer, or sends a targeted
follow-up when merged `origin/main` changes overlap the current review surface.

The reviewer runs parallel review lanes (scope, code, principles, security, tests,
errors, types, comments, docs) and writes `review-findings`. When the reviewer idles,
the next `telec todo work` call reconciles the verdict from `review-findings` and emits
the next action: advance the phase on APPROVE, or relay findings to the existing builder
on REQUEST CHANGES.

### 4. Fix (if needed)

On REQUEST CHANGES, the state machine finds the live builder session and sends the
findings via `telec sessions send`. The builder loads the fix procedure on demand
(`software-development/procedure/lifecycle/fix-review-findings`) and addresses the
findings without losing context.

Recoverable process failures are the worker's own to recover. The work state
machine merges `origin/main` into the worktree before dispatch/review; if that
machine-owned merge returns `MERGE_MAIN_FAILED`, the builder's own procedure
carries the recovery mechanics. Failed lint/test gates, dirty worktrees,
missing stamps, and stale branch publication are the same: the child mutates
the worktree; the orchestrator composes no guidance and escalates when the
blocker is human-owned, architectural, or a worker unable to proceed from its
own brief.

Review/fix loops are capped by `max_review_rounds` (default 3). No fresh fixer
session is dispatched — the original builder handles the fix cycle, and the next
review round reuses the same reviewer session when it is still alive.

### 5. Finalize

On APPROVE, the state machine dispatches a finalizer via `next-finalize`. The
finalizer integrates latest main into the worktree, resolves conflicts, pushes
the branch, and reports FINALIZE_READY. The state machine then drives the finalize
handoff, emitting end commands for the slug's workers and then for the work
orchestrator itself. Successful handoff is the terminal state for this
orchestrator session.

**Integration is not the work orchestrator's scope — authority ends at finalize.**
After a finalizer reports FINALIZE_READY, re-enter `telec todo work [slug]` to trigger
the handoff; the state machine records durable finalize state and emits the terminal
cleanup script.
Never dispatch `next-integrate`, call `telec todo integrate`, or work around permission
denials to reach integration. Integration is a separate singleton role with its own
lease, worktree, and dispatch path. If the machine does not advance past finalize
because a child needs recoverable worktree or branch-publication help, guide that
child through recovery first. If the blocker is not recoverable inside work scope,
record the blocker and stop — do not escalate scope.

### 6. Deferrals

If `deferrals.md` exists, the state machine dispatches deferral resolution via
`next-defer` before or after finalize. New todos are created from justified deferrals.

### 7. Bug fix

For bug-type work items, the state machine dispatches `next-build` — the same
builder as a change/feature. The bug's mandate is the reviewed
`implementation-plan` plus the `diagnosis` (code-grounded root cause, fix
approach, and verification approach produced in the prepare phase); the builder
executes the plan and drives the reproduction test RED→GREEN. Diagnosis happens
upstream in the prepare phase, not here.

Its post-completion bookkeeping matches the normal build path: the build worker
stamps `telec todo stamp [slug] --build-complete`, then the orchestrator re-enters
`telec todo work [slug]`.

### 8. Kickback to prepare (human-gated)

A build can stall on a plan defect that no fix resolves — the implementation plan
cannot be executed as written and needs re-derivation, not a fix round. The builder
surfaces the reason and idles; that idle session is the signal the human reads.

The kickback is human-gated. The orchestrator never invokes it on its own
initiative and a worker never invokes it at all. The orchestrator has already
tailed the builder's blocking reason, so the human talks only to the orchestrator:
they read the signal together, and only when re-preparation is judged resolvable
does the human direct the orchestrator to invoke it. If the signal shows no way
out, the kickback is not the move — the human handles it another way.

<!-- planned-change:kickback-fully-retracts-work-state -->
On that direction the orchestrator runs
`telec todo stamp [slug] --kickback --reason "<why the plan cannot be built>"`. The
stamp appends the reason to `input` (creating `input` when the todo has none) and
invalidates the implementation-plan, so the phase derives back to `plan_drafting`.

The orchestrator then re-enters `telec todo work [slug]`. The work machine treats a
kickback-invalidated todo as terminal for this work session: it releases the slug's
working resources — the worktree, its local and remote branch, and the workspace
directory, keeping the durable todo and its artifacts — and emits the cleanup script
— end the slug's workers, then end the orchestrator itself — distinct from the
in-line drift bounce that keeps the same session driving. The orchestrator
self-ending frees the slug's active runner; the runner then picks up the
`plan_drafting` todo and dispatches a fresh prepare, which reads the kickback block
in `input` as authoritative re-derivation context.
<!-- change:kickback-fully-retracts-work-state -->
On that direction the orchestrator runs
`telec todo stamp [slug] --kickback --reason "<why the plan cannot be built>"`. The
stamp is the complete, machine-owned retraction transition, in quiescence-first
order: it appends the reason to `input` (creating `input` when the todo has none),
ends the slug's live worker sessions and waits for them to drain, releases the
slug's working resources — the worktree, its local and remote branch, and the
workspace directory, keeping the durable todo and its artifacts — and only then
invalidates the implementation-plan, clears the work-phase state (build-started
freeze, build-complete claim, build-review state, finalize handoff), and releases
the runner claim so the todo re-enters `plan_drafting`. The claim is held until
the final commit, so no fresh dispatch races the cleanup.

The stamp's response carries the orchestrator's remaining wind-down instruction:
end itself, without calling `telec todo work [slug]` again — its workers are
already ended by the stamp. The runner then picks up the `plan_drafting` todo and
dispatches a fresh prepare, which reads the kickback block in `input` as
authoritative re-derivation context. An orchestrator that re-enters
`telec todo work [slug]` anyway receives the wind-down script from the work
machine's backstop branch, which also repairs any residue left by a kickback
stamped before the retraction moved into the stamp.
<!-- /planned-change:kickback-fully-retracts-work-state -->

## Outputs

- Code changes implementing the plan, committed and reviewed.
- Review findings addressed.
- Branch finalized and ready for integration.
- Deferrals processed into new todos when applicable.

## Recovery

- If a worker stalls, do not compose recovery guidance; escalate when it cannot proceed from its own brief.
- If stuck after two recovery iterations, record blockers only with evidence that the remaining decision is human-owned, architectural, or outside work scope.
- If review/fix loops hit the cap, the orchestrator owns pragmatic closure.
- The state machine checkpoint is crash-safe — re-calling `telec todo work` resumes from last state.

## See also

- ~/.teleclaude/docs/software-development/procedure/lifecycle/work/build.md
- ~/.teleclaude/docs/software-development/procedure/lifecycle/work/review-build.md
- ~/.teleclaude/docs/software-development/procedure/lifecycle/fix-review-findings.md
- ~/.teleclaude/docs/software-development/procedure/lifecycle/work/finalize.md
- ~/.teleclaude/docs/software-development/procedure/lifecycle/work/deferrals.md
