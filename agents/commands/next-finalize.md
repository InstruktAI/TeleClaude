---
argument-hint: '[slug]'
description: Worker command - merge, log delivery, cleanup after review passes
---

@~/.teleclaude/docs/software-development/role/finalizer.md
@~/.teleclaude/docs/software-development/procedure/lifecycle/finalize.md

# Finalize

You are now the Finalizer.

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
