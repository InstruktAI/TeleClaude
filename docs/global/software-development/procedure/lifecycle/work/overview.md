---
id: 'software-development/procedure/lifecycle/work/overview'
type: 'procedure'
domain: 'software-development'
scope: 'domain'
description: 'Work stage overview. Build, review, fix, finalize cycle driven by the work state machine.'
---

# Work Overview — Procedure

## Goal

Drive the work state machine (`telec todo work`) through the build-review-fix-finalize
cycle until the todo is delivered or blocked. The orchestrator dispatches workers as
instructed by the state machine and supervises their progress.

## Preconditions

- Target slug has completed preparation (state: PREPARED).
- `telec todo artifacts read {slug} requirements` and `telec todo artifacts read {slug} implementation-plan` exist and are approved.
- Worktree is available or can be created for the slug.

## Steps

### 1. Enter the state machine

Call `telec todo work [slug]`. Read the returned instruction block and execute it.

### 2. Build

The state machine dispatches a builder worker via `next-build`. The builder:

- Executes the implementation plan task-by-task
- Commits per task
- Reports BUILD COMPLETE when done

When the builder reports success, the orchestrator persists the build transition
before advancing — normally `telec todo mark-phase {slug} --phase build --status complete`.
Only after that bookkeeping step does it call `telec todo work [slug]` again.
If build gates fail, the orchestrator keeps the builder session alive, sends the
gate failures back to the builder, and retries the same post-completion loop.

### 3. Review

After build completes, the state machine dispatches a reviewer via `next-review-build`.
The reviewer runs parallel review lanes (scope, code, principles, security, tests,
errors, types, comments, docs) and delivers a verdict.

The orchestrator persists the review transition before advancing:

- APPROVE → `telec todo mark-phase {slug} --target review_approved`
- REQUEST CHANGES → `telec todo mark-phase {slug} --target review_changes_requested`

On approval it ends the reviewer session and calls `telec todo work [slug]` again.
On requested changes it keeps the reviewer alive, dispatches a fixer, and follows
the fix/re-review loop.

### 4. Fix (if needed)

On REQUEST CHANGES, the state machine dispatches a fixer via `next-fix-review`.
The fixer addresses Critical and Important findings minimally. The cycle returns
to Review. Review/fix loops are capped by `max_review_rounds` (default 3).

When the fixer reports completion, the orchestrator ends the fixer session, marks
the review as pending again via `telec todo mark-phase {slug} --target review_pending`,
and re-enters `telec todo work [slug]`.

### 5. Finalize

On APPROVE, the state machine dispatches a finalizer via `next-finalize`. The
finalizer integrates latest main into the worktree, resolves conflicts, pushes
the branch, and reports FINALIZE_READY. The orchestrator records durable finalize
state and hands off to integration.

The finalize handoff is also persisted before re-entry:
`telec todo mark-phase {slug} --target finalize_ready`, then the finalizer session
is ended and `telec todo work [slug]` is called again.

### 6. Deferrals

If `deferrals.md` exists, the state machine dispatches deferral resolution via
`next-defer` before or after finalize. New todos are created from justified deferrals.

### 7. Bug fix

For bug-type work items, the state machine dispatches `next-bugs-fix` instead of
the standard build flow. The bug fixer follows systematic debugging methodology.

Its post-completion bookkeeping matches the normal build path: persist the build
completion transition first, then re-enter `telec todo work [slug]`, and loop on
build-gate failures until they pass or a blocker remains.

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
- ~/.teleclaude/docs/software-development/procedure/lifecycle/work/fix-review.md
- ~/.teleclaude/docs/software-development/procedure/lifecycle/work/finalize.md
- ~/.teleclaude/docs/software-development/procedure/lifecycle/work/deferrals.md
- ~/.teleclaude/docs/software-development/procedure/lifecycle/work/bug-fix.md
