---
id: 'project/design/architecture/git-wrapper'
type: 'design'
scope: 'project'
description: 'Three-tier git wrapper permission model for agent sessions.'
---

# Git Wrapper — Design

## What it is

A PATH-based bash wrapper installed at `~/.teleclaude/bin/git` (symlink to
`teleclaude/install/wrappers/git`). Intercepts all shell `git` commands in
agent tmux sessions and enforces role-based permissions.

## Architecture

### Bypass layers

Two git execution paths exist:

1. **Shell git (through wrapper):** Agent tmux sessions have
   `~/.teleclaude/bin` first in PATH. All `git` commands go through the wrapper.
2. **GitPython (bypasses wrapper):** `teleclaude/git.py` resolves the real git
   binary by walking PATH and skipping the wrapper directory. All daemon
   Python code uses this path via `from teleclaude.git import Repo`.

The wrapper governs agent behavior. GitPython governs daemon internals.
They are independent layers.

### Permission model

Three tiers, applied in order:

| Tier        | Operations                                           | Behavior                |
| ----------- | ---------------------------------------------------- | ----------------------- |
| DESTRUCTIVE | restore, clean, switch, reset (bare), revert (bare)  | Blocked for all roles   |
| PROTECTED   | stash (integrator), commit/push on main (integrator) | Role-gated              |
| RESTRICTED  | commit (orchestrator)                                | Blocked on all branches |

### Roles

| Role         | Set by           | Use case                                                  |
| ------------ | ---------------- | --------------------------------------------------------- |
| (unset)      | Default          | Human interactive session — worker permissions internally |
| worker       | Daemon bootstrap | Worktree-scoped builders, fixers, reviewers               |
| system       | Daemon bootstrap | Job runners — same restrictions as worker                 |
| orchestrator | Daemon bootstrap | State machine drivers — no commits anywhere               |
| integrator   | Daemon bootstrap | Merge workflow — full protected access                    |

### Autostash prevention

Git's `merge.autoStash` and `rebase.autoStash` create repo-wide stash entries
silently. In multi-worktree environments, this corrupts other worktrees.

Prevention layers:

1. **Wrapper:** Injects `GIT_CONFIG_COUNT/KEY/VALUE` env vars disabling both
   `rebase.autoStash` and `merge.autoStash` for every command.
2. **GitPython:** `no_autostash_env()` helper returns an env dict with the
   same config injection, scoped to individual subprocess calls.
3. **Explicit flags:** `--no-autostash` on merge and pull-rebase calls.

### Observability

When `TELECLAUDE_GIT_WRAPPER_LOG` is set (injected by daemon bootstrap), the
wrapper logs every invocation with timestamp, role, subcommand, args, and cwd.

### Test isolation

Wrapper permission tests (`test_git_wrapper_permissions.py`) MUST use
`tmp_path` temp repos for any test where the wrapper allows the operation
(e.g., stash with integrator role, commit with worker role). This prevents
test-created git state from polluting the shared repository.

### Symlink architecture

```
~/.teleclaude/bin/git  →  <repo>/teleclaude/install/wrappers/git  (symlink)
```

Worktrees contain stale copies of the wrapper source file. These copies are
NEVER invoked — all sessions resolve `git` via PATH which hits the symlink.
The test file resolves `WRAPPER` from `Path(__file__).parents[3]` which in
worktrees points to the stale copy. This is acceptable because tests test the
wrapper behavior, not the installed version — but tests must use temp repos
to prevent side effects.

## Known caveats

- The wrapper cannot intercept git operations performed internally by other
  git commands (e.g., autostash during merge). This is handled by config
  injection at the wrapper and GitPython levels.
- `TELECLAUDE_SYSTEM_ROLE` is a bash variable local to the wrapper script.
  It does not export or bleed into the session environment.
- Pre-commit's staged-file isolation uses `git checkout -- .` which goes
  through the wrapper. File-scoped checkout is allowed for all roles.
