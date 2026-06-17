---
description: 'Work stage overview. Build, review, fix, finalize cycle driven by the work state machine.'
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

## Preconditions

- Target slug has completed preparation (state: PREPARED).
- `telec todo artifacts read {slug} prd` and `telec todo artifacts read {slug} implementation-plan` exist and are approved.
- Optional `architecture` artifacts are approved or explicitly skipped.
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
- **Reviewers**: `med` (we used slow in the past but have well specced out process to follow so `med` is sufficient).
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

Recoverable process failures use the same child-recovery posture even when the
child did not encounter the failure directly. The work state machine merges
`origin/main` into the worktree before dispatch/review; if that machine-owned
merge returns `MERGE_MAIN_FAILED`, the orchestrator owns the awareness. It reads
the relevant child command instructions, inspects the state-machine output and
worktree evidence, and sends the existing builder concrete recovery guidance:
accepted `origin/main` is the leading baseline, the todo's prepared intent is
reapplied on top, conflicts are resolved in the worktree, gates are rerun, and
the correct lifecycle stamp/report is emitted. Failed lint/test gates, dirty
worktrees, missing stamps, and stale branch publication follow the same pattern:
the orchestrator gives timely guidance, the child mutates the worktree. The
orchestrator escalates only when the blocker is human-owned or architectural.

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

## Outputs

- Code changes implementing the plan, committed and reviewed.
- Review findings addressed.
- Branch finalized and ready for integration.
- Deferrals processed into new todos when applicable.

## Recovery

- If a worker stalls, read its command instructions, inspect the evidence, and open direct conversation with concrete recovery guidance.
- If stuck after two recovery iterations, record blockers only with evidence that the remaining decision is human-owned, architectural, or outside work scope.
- If review/fix loops hit the cap, the orchestrator owns pragmatic closure.
- The state machine checkpoint is crash-safe — re-calling `telec todo work` resumes from last state.

## See also

- ~/.teleclaude/docs/software-development/procedure/lifecycle/work/build.md
- ~/.teleclaude/docs/software-development/procedure/lifecycle/work/review.md
- ~/.teleclaude/docs/software-development/procedure/lifecycle/fix-review-findings.md
- ~/.teleclaude/docs/software-development/procedure/lifecycle/work/finalize.md
- ~/.teleclaude/docs/software-development/procedure/lifecycle/work/deferrals.md
