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
- Dirty `main` is allowed. Agents may continue work in files required by the active task.
- Unrelated local changes may be reported for awareness, but they are non-blocking and must not change task execution.
- Only treat local changes as blockers when they overlap current task scope or create a concrete data-loss risk.
- In worker worktrees, treat orchestrator-managed planning/state drift as non-blocking:
  - `todos/roadmap.yaml`
  - `todos/{slug}/state.yaml`
- Do not commit those orchestrator-managed drift files unless the active task explicitly requires planning/state edits.
- Do not repeatedly report expected orchestrator-managed drift; only escalate cleanliness issues for additional dirty files outside this allowlist.
- Only modify files required by the request.
- Complete task changes in a commit before reporting done.
- Avoid surgical staging by default; prefer straightforward task-scoped commits.

## Rationale

- Prevents accidental data loss and preserves ownership of in‑progress work.
- `git stash` state is repository-wide, not isolated per worktree. In multi-worktree flows, stash pop/apply can reintroduce unrelated changes into the wrong branch.

## Scope

- Applies to all repositories and all agents.
- Applies to build/review/fix orchestration and worker command artifacts.

## Enforcement

- **Git wrapper** (`~/.teleclaude/bin/git`): A PATH-based binary wrapper prepended to all agent tmux sessions via `tmux_bridge.py`. Blocks `stash`, `checkout`, `restore`, `clean`, and `reset --hard/--merge/--keep` at the shell level, below AI reasoning. Agents cannot bypass this.
- Never discard or overwrite uncommitted work unless told to.
- Do not stop, reroute, or escalate solely because unrelated files are dirty.
- Agent instruction artifacts must not include stash workflows.
- Lint guardrails fail when `git stash*` commands appear in `agents/` or `.agents/`.

## Exceptions

- None.
