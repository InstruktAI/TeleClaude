---
id: 'project/design/architecture/git-wrapper'
type: 'design'
scope: 'project'
description: 'Three-tier git wrapper permission model for agent sessions.'
---

# Git Wrapper — Design

## Purpose

A PATH-based Python wrapper installed at `~/.teleclaude/bin/git` (symlink to
`teleclaude/install/wrappers/git`). Intercepts all shell `git` commands in
agent tmux sessions and enforces role-based permissions. Uses `uv run` with
gitpython to execute commands against the real git binary.

Two git execution paths exist:

1. **Shell git (through wrapper):** Agent tmux sessions have
   `~/.teleclaude/bin` first in PATH. All `git` commands go through the wrapper.
2. **GitPython (bypasses wrapper):** `teleclaude/git.py` resolves the real git
   binary by walking PATH and skipping the wrapper directory. All daemon
   Python code uses this path via `from teleclaude.git import Repo`.

The wrapper governs agent behavior. GitPython governs daemon internals.
They are independent layers.

Symlink architecture:

```
~/.teleclaude/bin/git  →  <repo>/teleclaude/install/wrappers/git  (symlink)
```

Worktrees contain stale copies of the wrapper source file. These copies are
NEVER invoked — all sessions resolve `git` via PATH which hits the symlink.

## Inputs/Outputs

**Inputs:**

- `$TMPDIR/teleclaude_identity.json` — per-session identity file containing `system_role`, `human_role`, `session_id`, and `session_token`. Written by daemon bootstrap.
- `TELECLAUDE_SYSTEM_ROLE` env var — human-only escape hatch. Honored only when `human_role` is present in the identity file. Pure agent sessions ignore this variable.
- `GIT_CONFIG_COUNT/KEY/VALUE` — env vars injected by the wrapper to disable autostash

**Outputs:**

- Blocked or allowed git operations based on role and tier
- Invocation logs (timestamp, role, subcommand, args, cwd) — best-effort to `/var/log/instrukt-ai/teleclaude/git-wrapper.log`
- `GIT_CONFIG` env vars propagated to the real git binary for autostash prevention

**Roles:**

| Role         | Set by                           | Use case                                               |
| ------------ | -------------------------------- | ------------------------------------------------------ |
| human_role   | Identity file (daemon bootstrap) | Human interactive session — directory scope check only |
| worker       | Identity file (daemon bootstrap) | Worktree-scoped builders, fixers, reviewers            |
| system       | Identity file (daemon bootstrap) | Job runners — same restrictions as worker              |
| orchestrator | Identity file (daemon bootstrap) | State machine drivers — no commits anywhere            |
| integrator   | Identity file (daemon bootstrap) | Merge workflow — full protected access                 |

Valid system roles: `worker`, `system`, `orchestrator`, `integrator`. Unknown roles fail fast.

## Invariants

Three permission tiers, applied in order for agent sessions:

| Tier        | Operations                                           | Behavior                |
| ----------- | ---------------------------------------------------- | ----------------------- |
| DESTRUCTIVE | restore, clean, switch, reset (bare), revert (bare)  | Blocked for all roles   |
| PROTECTED   | stash (integrator), commit/push on main (integrator) | Role-gated              |
| RESTRICTED  | commit (orchestrator)                                | Blocked on all branches |

Human sessions (identity file has `human_role`, no `system_role`):

- Git is allowed freely within the current working directory tree.
- Operations targeting directories outside cwd are blocked.

No identity (neither `system_role` nor `human_role` in identity file):

- Fail fast — contract violation.

- Wrapper permission tests MUST use `tmp_path` temp repos for any test where
  the wrapper allows the operation. This prevents test-created git state from
  polluting the shared repository.
- The env var escape hatch (`TELECLAUDE_SYSTEM_ROLE`) is only honored when
  `human_role` is present in the identity file. Agent sessions cannot
  self-escalate via environment variables.
- Pre-commit's staged-file isolation uses `git checkout -- .` which goes
  through the wrapper. File-scoped checkout is allowed for all roles.
- Branch resolution for main-branch protection uses `-C`, `--git-dir`, and
  `--work-tree` args to resolve against the correct repository context.

## Primary flows

Git's `merge.autoStash` and `rebase.autoStash` create repo-wide stash entries
silently. In multi-worktree environments, this corrupts other worktrees.
Prevention layers:

1. **Wrapper:** Injects `GIT_CONFIG_COUNT/KEY/VALUE` env vars disabling both
   `rebase.autoStash` and `merge.autoStash` for every command.
2. **GitPython:** `no_autostash_env()` helper returns an env dict with the
   same config injection, scoped to individual subprocess calls.
3. **Explicit flags:** `--no-autostash` on merge and pull-rebase calls.

The wrapper always logs invocations (best-effort) with timestamp, role,
subcommand, args, and cwd to a fixed log path.

## Failure modes

- The wrapper cannot intercept git operations performed internally by other
  git commands (e.g., autostash during merge). This is handled by config
  injection at the wrapper and GitPython levels.
- Worktree copies of the wrapper source are stale (frozen at worktree creation
  time). If invoked directly (bypassing PATH symlink), they enforce outdated
  permission rules. The test file resolves `WRAPPER` from
  `Path(__file__).parents[3]` which in worktrees points to the stale copy —
  acceptable because tests test wrapper behavior, not the installed version,
  but tests must use temp repos to prevent side effects.
- The wrapper sets `GIT_PYTHON_GIT_EXECUTABLE` to the real binary before
  importing gitpython to prevent `uv run` recursion through the wrapper symlink.
