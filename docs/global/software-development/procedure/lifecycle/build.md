---
description: 'Build phase. Execute implementation plan tasks, commit per task, and manage deferrals.'
id: 'software-development/procedure/lifecycle/build'
scope: 'domain'
type: 'procedure'
---

# Build — Procedure

## Required reads

- @~/.teleclaude/docs/software-development/policy/commits.md
- @~/.teleclaude/docs/software-development/policy/version-control-safety.md

## Goal

Execute the implementation plan for a todo and produce verified, review-ready changes.

## Preconditions

- `todos/{slug}/requirements.md` exists and is readable.
- `todos/{slug}/implementation-plan.md` exists and is readable.
- `todos/{slug}/quality-checklist.md` exists and includes `## Build Gates (Builder)`.
- The todo scope is implementable in one build phase.

## Steps

1. Read `requirements.md` to confirm intent and constraints.
2. Read `implementation-plan.md` and identify unchecked tasks.
3. Execute tasks sequentially:
   - Implement the task.
   - Commit changes for the task (one commit per task).
   - Update the task checkbox to `[x]` and include that change in the same commit.
   - Do not use `git stash`/`git stash pop`; keep the flow commit-based inside the current worktree.
   - When adding or updating tests, assert behavioral contracts; avoid exact wording assertions on docs/agent prose unless execution depends on that exact token.
4. If a task is truly out of scope, create `deferrals.md` with the required template and continue with remaining tasks.
5. Update only the Build section in `quality-checklist.md`.
   - Do not edit Review or Finalize sections.

## Pre-completion checklist

1. All tasks in `implementation-plan.md` are `[x]`.
2. Tests pass: `make test`.
3. Lint passes: `make lint`.
4. Working tree is clean: `git status`.
   - If not clean, commit remaining build-phase changes following the commits policy.
   - Treat pre-existing out-of-scope drift as non-blocking.
   - Orchestrator-synced planning drift is a common non-blocking case:
     - `todos/roadmap.md`
     - `todos/dependencies.json`
   - If dirty files do not overlap this slug's build scope, continue; do not force-commit unrelated files during build unless the task explicitly requires editing them.
5. Verify commits exist: `git log --oneline -10`.
6. Build section in `quality-checklist.md` is fully checked.

## Report format

```
BUILD COMPLETE: {slug}

Tasks completed: {count}
Commits made: {count}
Tests: PASSING
Lint: PASSING

Ready for review.
```

## Outputs

- Code changes implementing the plan.
- Updated `implementation-plan.md` with checked tasks.
- Commits for each task.
- Optional `deferrals.md` when scope must be escalated.

## Recovery

- If a task fails, log the error in `implementation-plan.md` notes and retry.
- If stuck after two attempts, stop and report the blocker.
