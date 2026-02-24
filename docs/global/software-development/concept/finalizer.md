---
description: 'Post-review delivery role. Merge, clean up, and log delivery after approval.'
id: 'software-development/concept/finalizer'
scope: 'domain'
type: 'concept'
---

# Finalizer — Concept

## Required reads

- @~/.teleclaude/docs/software-development/procedure/lifecycle-overview.md

## What

Post-review delivery role. Run finalize prepare in the worktree, then orchestrator apply from canonical main.

1. **Verify approval** - Only finalize after explicit APPROVE verdict.
2. **Finalize prepare** - Integrate `origin/main` in the worktree and report `FINALIZE_READY`.
3. **Finalize apply (orchestrator)** - Merge/push from canonical root only.
4. **Log delivery** - Update `todos/delivered.yaml` and `todos/roadmap.yaml`.
5. **Cleanup** - Remove worktrees and delivery artifacts after apply.

## Why

Finalizes only approved work, keeps local main safe, and preserves existing changes while completing delivery.
