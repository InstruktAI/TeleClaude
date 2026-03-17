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
- **`git revert` requires inspection.** Before reverting any commit, run `git show --stat <commit>` and verify that _every_ file in the commit belongs to the scope you intend to undo. Commits in a multi-agent environment routinely contain changes from multiple workers — a blind revert destroys other agents' work. The git wrapper enforces this: bare `git revert` is blocked; pass `--confirmed` to acknowledge you have inspected the commit. Use `git revert` only as an escape hatch, not as a routine undo mechanism.
- Dirty `main` is allowed. Agents may continue work in files required by the active task.
- Repo root cleanliness is not required for integration. The integrator operates in an isolated worktree (`trees/_integration/`), independent of repo root state.
- Unrelated local changes may be reported for awareness, but they are non-blocking and must not change task execution.
- Only treat local changes as blockers when they overlap current task scope or create a concrete data-loss risk.
- In worktrees, all files belong to the task. Commit everything — orchestrator writes to `todos/roadmap.yaml` and `todos/{slug}/state.yaml` are part of the task context, not drift.
- Only modify files required by the request.
- Complete task changes in a commit before reporting done.
- Avoid surgical staging by default; prefer straightforward task-scoped commits.

## Rationale

- Prevents accidental data loss and preserves ownership of in‑progress work.
- `git stash` state is repository-wide, not isolated per worktree. In multi-worktree flows, stash pop/apply can reintroduce unrelated changes into the wrong branch.
- Integration worktree isolation ensures delivery proceeds regardless of repo root state. Conflicts between local main and delivered changes surface naturally when the user pushes.

## Scope

- Applies to all repositories and all agents.
- Applies to build/review/fix orchestration and worker command artifacts.

## Enforcement

- **Git wrapper** (`~/.teleclaude/bin/git`): A PATH-based binary wrapper prepended to all agent tmux sessions via `tmux_bridge.py`. Blocks `stash`, `checkout`, `restore`, `clean`, and `reset --hard/--merge/--keep` at the shell level, below AI reasoning. Agents cannot bypass this. `git revert` requires `--confirmed` flag; bare `git revert` is blocked with a warning explaining the inspection requirement.
- **System role permissions:** The wrapper reads `TELECLAUDE_SYSTEM_ROLE` (set by the daemon from `session_metadata.system_role`) to determine permission scope. Four roles:
  - `worker` (default): Standard restrictions.
  - `orchestrator`: Auth-only; equivalent to worker permissions.
  - `integrator`: stash + file-scoped checkout.
  - `system`: commit/push on main + file-scoped checkout (stash remains blocked).
    Agents must never set this variable on their own initiative.
- Never discard or overwrite uncommitted work unless told to.
- Do not stop, reroute, or escalate solely because unrelated files are dirty.
- Agent instruction artifacts must not include stash workflows.
- Lint guardrails fail when `git stash*` commands appear in `agents/` or `.agents/`.

## Exceptions

- None.
