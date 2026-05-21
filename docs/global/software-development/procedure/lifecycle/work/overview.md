---
description: 'Work stage overview. Build, review, fix, finalize cycle driven by the work state machine.'
domain: 'software-development'
id: 'software-development/procedure/lifecycle/work/overview'
scope: 'domain'
type: 'procedure'
visibility: 'public'
---

# Work Overview — Procedure

## Goal

Drive the work state machine (`telec todo work`) through the build-review-fix-finalize
cycle until the todo is delivered or blocked. The orchestrator dispatches workers as
instructed by the state machine and supervises their progress.

## Preconditions

- Target slug has completed preparation (state: PREPARED).
- `telec todo artifacts read {slug} prd` and `telec todo artifacts read {slug} implementation-plan` exist and are approved.
- Optional `architecture` and `test-specs` artifacts are approved or explicitly skipped.
- Worktree is available or can be created for the slug.

## Steps

### 1. Enter the state machine

Call `telec todo work [slug]`. Read the returned instruction block and execute it.

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
findings without losing context. Review/fix loops are capped by `max_review_rounds`
(default 3). No fresh fixer session is dispatched — the original builder handles the
fix cycle, and the next review round reuses the same reviewer session when it is still
alive.

### 5. Finalize

On APPROVE, the state machine dispatches a finalizer via `next-finalize`. The
finalizer integrates latest main into the worktree, resolves conflicts, pushes
the branch, and reports FINALIZE_READY. The state machine then drives the finalize
handoff, emitting end commands for the slug's workers. The work orchestrator advances
to the next ready slug (or self-ends if the queue is empty).

### 6. Deferrals

If `deferrals.md` exists, the state machine dispatches deferral resolution via
`next-defer` before or after finalize. New todos are created from justified deferrals.

### 7. Bug fix

For bug-type work items, the state machine dispatches `next-bugs-fix` instead of
the standard build flow. The bug fixer follows systematic debugging methodology.

Its post-completion bookkeeping matches the normal build path: the fixer stamps
`telec todo stamp [slug] --build-complete`, then the orchestrator re-enters
`telec todo work [slug]`.

## Outputs

- Code changes implementing the plan, committed and reviewed.
- Review findings addressed.
- Branch finalized and ready for integration.
- Deferrals processed into new todos when applicable.

## Recovery

- If a worker stalls, open direct conversation. If stuck after two iterations, record blockers.
- If review/fix loops hit the cap, the orchestrator owns pragmatic closure.
- The state machine checkpoint is crash-safe — re-calling `telec todo work` resumes from last state.

## See also

- ~/.teleclaude/docs/software-development/procedure/lifecycle/work/build.md
- ~/.teleclaude/docs/software-development/procedure/lifecycle/work/review.md
- ~/.teleclaude/docs/software-development/procedure/lifecycle/fix-review-findings.md
- ~/.teleclaude/docs/software-development/procedure/lifecycle/work/finalize.md
- ~/.teleclaude/docs/software-development/procedure/lifecycle/work/deferrals.md
- ~/.teleclaude/docs/software-development/procedure/lifecycle/work/bug-fix.md
