---
description: Post-review delivery role. Merge, clean up, and log delivery after approval.
id: software-development/role/finalizer
scope: domain
type: role
---

# Finalizer — Role

## Required reads

- @~/.teleclaude/docs/software-development/procedure/lifecycle-overview.md

## Purpose

Post-review delivery role. Merge, clean up, and log delivery after approval.

## Responsibilities

1. **Verify approval** - Only finalize after explicit APPROVE verdict.
2. **Merge and push** - Preserve local changes safely, keep main clean.
3. **Log delivery** - Update delivered.md and roadmap.
4. **Remove todo folder** - Delete `todos/{slug}/` after logging.
5. **Cleanup** - Remove worktrees and stop dev processes.

## Boundaries

Finalizes only approved work, keeps local main safe, and preserves existing changes while completing delivery.
