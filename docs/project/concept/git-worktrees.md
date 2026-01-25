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

## Inputs/Outputs

- **Inputs**: worktree creation from the main repository.
- **Outputs**: isolated working directory and database.

## Invariants

- Each worktree has an isolated `teleclaude.db`.
- Worktree paths must be registered in git for discovery.

## Primary flows

- `git worktree add` → set `TELECLAUDE_WORKING_DIR` → run commands in worktree.

## Failure modes

- Untracked worktrees are invisible to tooling and automation.
- Shared database between worktrees causes state contamination.
