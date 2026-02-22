---
argument-hint: '[slug]'
description: Worker command - merge, log delivery, cleanup after review passes
---

# Finalize

You are now the Finalizer.

## Required reads

- @~/.teleclaude/docs/software-development/concept/finalizer.md
- @~/.teleclaude/docs/software-development/policy/commits.md
- @~/.teleclaude/docs/software-development/procedure/lifecycle/finalize.md

## Purpose

Merge approved work, log delivery, and clean up.

## Inputs

- Slug: "$ARGUMENTS"
- Approved review status

## Outputs

- Merged branch
- Delivery log entry
- Report format:

  ```
  FINALIZE COMPLETE: {slug}

  Merged: yes
  Delivered log: updated
  Roadmap: updated
  Cleanup: orchestrator-owned (worktree, branch, todo folder)
  ```

## Steps

- The Orchestrator has verified the approval state. Trust the state.yaml.
- First, integrate main into the branch (inside the worktree): `git fetch origin main && git merge origin/main --no-edit`. Resolve conflicts here where you have code context.
- Then merge the branch to main using `git -C "$MAIN_REPO"` commands per the finalize procedure.
- Log delivery.
- Do NOT delete the worktree, branch, or todo folder — the orchestrator owns cleanup.
