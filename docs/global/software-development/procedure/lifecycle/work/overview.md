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
- `todos/{slug}/requirements.md` and `todos/{slug}/implementation-plan.md` exist and are approved.
- Worktree is available or can be created for the slug.

## Steps

### 1. Enter the state machine

Call `telec todo work [slug]`. Read the returned instruction block and execute it.

### 2. Build

The state machine dispatches a builder worker via `next-build`. The builder:

- Executes the implementation plan task-by-task
- Commits per task
- Validates demo artifacts
- Reports BUILD COMPLETE when done

### 3. Review

After build completes, the state machine dispatches a reviewer via `next-review-build`.
The reviewer runs parallel review lanes (scope, code, principles, security, tests,
errors, types, comments, demo, docs) and delivers a verdict.

### 4. Fix (if needed)

On REQUEST CHANGES, the state machine dispatches a fixer via `next-fix-review`.
The fixer addresses Critical and Important findings minimally. The cycle returns
to Review. Review/fix loops are capped by `max_review_rounds` (default 3).

### 5. Finalize

On APPROVE, the state machine dispatches a finalizer via `next-finalize`. The
finalizer integrates latest main into the worktree, resolves conflicts, pushes
the branch, and reports FINALIZE_READY. The orchestrator records durable finalize
state and hands off to integration.

### 6. Deferrals

If `deferrals.md` exists, the state machine dispatches deferral resolution via
`next-defer` before or after finalize. New todos are created from justified deferrals.

### 7. Demo

Demo validation happens during build. Demo execution (`telec todo demo run`) happens
after merge on main. Demo presentation happens via `next-demo`.

### 8. Bug fix

For bug-type work items, the state machine dispatches `next-bugs-fix` instead of
the standard build flow. The bug fixer follows systematic debugging methodology.

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
- ~/.teleclaude/docs/software-development/procedure/lifecycle/work/demo.md
- ~/.teleclaude/docs/software-development/procedure/lifecycle/work/bug-fix.md
