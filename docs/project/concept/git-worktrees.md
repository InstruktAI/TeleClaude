---
description: Use of git worktrees for isolated agent development and testing.
id: concept/git-worktrees
scope: project
type: concept
---

# Git Worktrees — Concept

## Purpose

Provides agents with a clean, isolated environment for implementation and testing, preventing interference with the main development directory or production state.

- Inputs: worktree creation from the main repository.
- Outputs: isolated working directory and database.

1. **Isolated Database**: Every worktree contains its own `teleclaude.db` (usually symlinked or initialized separately).
2. **Environment Isolation**: `TELECLAUDE_WORKING_DIR` is set to the worktree path.
3. **Temporary Nature**: Worktrees are usually created for a single todo/slug and deleted after completion.

- Agents SHOULD perform all build/test work inside a worktree.
- Worktrees MUST be tracked by the main git repo (as additional worktrees) to ensure visibility.

- Missing worktree tracking breaks visibility and task automation.

- TBD.

- TBD.

- TBD.

- TBD.

## Inputs/Outputs

- TBD.

## Invariants

- TBD.

## Primary flows

- TBD.

## Failure modes

- TBD.
