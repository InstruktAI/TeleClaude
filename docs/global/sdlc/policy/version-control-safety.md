---
description: 'Safety rules for git operations and handling uncommitted work.'
visibility: 'public'
---

# Version Control Safety — Policy

## Rules

- Dirty `main` is allowed. Agents may continue work in files required by the active task.
- Repo root cleanliness is not required for integration. The integrator operates in an isolated worktree (`trees/_integration/`), independent of repo root state.
- Unrelated local changes may be reported for awareness, but they are non-blocking and must not change task execution.
- Only treat local changes as blockers when they overlap current task scope or create a concrete data-loss risk.
- In worktrees, all files belong to the task. Commit everything.
- Only modify files required by the request.
- Complete task changes in a commit before reporting done.
- Avoid surgical staging by default; prefer straightforward task-scoped commits.
- Never discard or overwrite uncommitted work unless explicitly told to.
- Do not stop, reroute, or escalate solely because unrelated files are dirty.

## Rationale

- Prevents accidental data loss and preserves ownership of in‑progress work.
- Integration worktree isolation ensures delivery proceeds regardless of repo root state. Conflicts between local main and delivered changes surface naturally when the user pushes.

## Scope

- Applies to all repositories and all agents.

## Enforcement

`telec code commit` is the canonical commit interface. The wrapper handles workspace scoping, staging, and hooks automatically. Direct git operations that would conflict with these guarantees are blocked at the shell level and self-document the right next step on the error path.

## Exceptions

- None.
