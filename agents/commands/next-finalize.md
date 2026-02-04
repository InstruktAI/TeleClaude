---
argument-hint: '[slug]'
description: Worker command - merge, log delivery, cleanup after review passes
---

# Finalize

You are now the Finalizer.

## Required reads

- @~/.teleclaude/docs/software-development/concept/finalizer.md
- @~/.teleclaude/docs/software-development/procedure/lifecycle/finalize.md

## Purpose

Merge approved work, log delivery, and clean up.

## Inputs

- Slug: "$ARGUMENTS"
- Approved review status

## Outputs

- Merged branch
- Delivery log entry
- Cleaned worktree
- Report format:

  ```
  FINALIZE COMPLETE: {slug}

  Branch merged: {branch_name}
  Delivery logged: YES
  Cleanup: COMPLETE

  Work item delivered.
  ```

## Steps

- Verify review is APPROVED.
- Merge the worktree branch to main.
- Log delivery.
- Clean up.
