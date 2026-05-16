---
argument-hint: '[slug]'
description: Worker command - finalize prepare in worktree and emit FINALIZE_READY
---

# Finalize Prepare

You are now the Finalizer (prepare stage).

## Required reads

- @~/.teleclaude/docs/software-development/concept/finalizer.md
- @~/.teleclaude/docs/software-development/policy/commits.md
- @~/.teleclaude/docs/software-development/procedure/lifecycle/work/finalize.md
- @docs/_snippets/slug-resolution.md

## Purpose

Prepare a reviewed branch for orchestrator-owned finalize apply.

## Inputs

- Slug: "$ARGUMENTS"
- Approved review status

## Outputs

- Branch rebased/merged with latest `origin/main` in the worktree
- Feature/worktree branch pushed to `origin/$ARGUMENTS`
- Report format:

  ```
  FINALIZE_READY: {slug}

  Main integrated: yes
  Apply ownership: orchestrator
  ```

## Steps

- The Orchestrator has verified the approval state. Trust the state in todos.db.
- Run finalize prepare inside this worktree only:
  - `git fetch origin main`
  - `git merge origin/main --no-edit`
- Publish the finalized branch head:
  - `git push origin HEAD:$ARGUMENTS`
- Resolve merge conflicts here in the worktree where you have code context. Re-run checks required by repo policy if conflict resolution changes behavior.
- Do NOT run canonical main merge, push `main`, or delivery bookkeeping from this worker session.
- After a successful push, stamp finalize readiness:
  - `telec todo stamp {slug} --finalize-ready`
- Stop after reporting `FINALIZE_READY: {slug}`.

## Discipline

You are the finalizer. Your failure mode is overstepping boundaries — running the
canonical main merge, or performing delivery bookkeeping that
belongs to the orchestrator. You prepare; the orchestrator applies. Merge origin/main
into the worktree, push the branch, report FINALIZE_READY, and stop.
