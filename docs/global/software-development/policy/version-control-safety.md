---
id: 'software-development/policy/version-control-safety'
type: 'policy'
scope: 'domain'
description: 'Safety rules for git operations and handling uncommitted work.'
---

# Version Control Safety — Policy

## Rules

- Never use `git checkout`, `git restore`, `git reset`, `git clean`, or delete files unless explicitly instructed by the user.
- Never use `git stash`, `git stash pop`, `git stash apply`, or `git stash drop` in agent workflows.
- If a file has uncommitted changes and you must edit it, ask first.
- Only modify files required by the request.
- Keep worktree context switches commit-based:
  - commit in-scope changes on the current branch, or
  - create/use a dedicated worktree for parallel changes.

## Rationale

- Prevents accidental data loss and preserves ownership of in‑progress work.
- `git stash` state is repository-wide, not isolated per worktree. In multi-worktree flows, stash pop/apply can reintroduce unrelated changes into the wrong branch.

## Scope

- Applies to all repositories and all agents.
- Applies to build/review/fix orchestration and worker command artifacts.

## Enforcement

- Stop and ask before touching files with uncommitted changes.
- Never discard or overwrite uncommitted work unless told to.
- Agent instruction artifacts must not include stash workflows.
- Lint guardrails fail when `git stash*` commands appear in `agents/` or `.agents/`.

## Exceptions

- None.
