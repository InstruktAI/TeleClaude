---
argument-hint: '[slug]'
description: Worker command - finalize prepare in worktree and emit FINALIZE_READY
---

# Finalize Prepare

You are now the Finalizer (prepare stage).

## Required reads

- @~/.teleclaude/docs/software-development/concept/finalizer.md
- @~/.teleclaude/docs/software-development/policy/commits.md
- @~/.teleclaude/docs/software-development/procedure/lifecycle/finalize.md

## Purpose

Prepare a reviewed branch for orchestrator-owned finalize apply.

## Inputs

- Slug: "$ARGUMENTS"
- Approved review status

## Outputs

- Branch rebased/merged with latest `origin/main` in the worktree
- Report format:

  ```
  FINALIZE_READY: {slug}

  Main integrated: yes
  Apply ownership: orchestrator
  ```

## Steps

- The Orchestrator has verified the approval state. Trust the state.yaml.
- Run finalize prepare inside this worktree only:
  - `git fetch origin main`
  - `git merge origin/main --no-edit`
- Resolve merge conflicts here in the worktree where you have code context. Re-run checks required by repo policy if conflict resolution changes behavior.
- Do NOT run canonical main merge, push, or delivery bookkeeping from this worker session.
- Stop after reporting `FINALIZE_READY: {slug}`.
