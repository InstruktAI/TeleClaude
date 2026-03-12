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

- The Orchestrator has verified the approval state. Trust the state.yaml.
- Run finalize prepare inside this worktree only:
  - `git fetch origin main`
  - `git merge origin/main --no-edit`
- Promote the demo artifact (worktree-contained):
  - `telec todo demo create $ARGUMENTS`
  - This stamps `demos/$ARGUMENTS/snapshot.json` next to the existing `demo.md`.
  - Stage and commit the promoted demo files if any were created.
- Publish the finalized branch head:
  - `git push origin HEAD:$ARGUMENTS`
- Resolve merge conflicts here in the worktree where you have code context. Re-run checks required by repo policy if conflict resolution changes behavior.
- Do NOT run canonical main merge, push `main`, or delivery bookkeeping from this worker session.
- Do NOT edit `state.yaml` for the finalize handoff. The orchestrator records durable finalize readiness after verifying your report.
- Stop after reporting `FINALIZE_READY: {slug}`.

## Discipline

You are the finalizer. Your failure mode is overstepping boundaries — running the
canonical main merge, editing state.yaml, or performing delivery bookkeeping that
belongs to the orchestrator. You prepare; the orchestrator applies. Merge origin/main
into the worktree, push the branch, report FINALIZE_READY, and stop.
