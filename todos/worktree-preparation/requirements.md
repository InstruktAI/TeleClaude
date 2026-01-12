# Worktree Preparation

## Problem

When `next_work()` creates a worktree and dispatches a worker AI into it, the worktree is not prepared. The worker AI receives vague instructions ("ensure all dependencies are installed") which leads to running `make install` from within the worktree. This hijacks the main daemon:

1. `bin/install.sh` resolves `INSTALL_DIR` from its own location (the worktree)
2. Global CLI symlink gets repointed to worktree
3. Systemd/launchd service may get reconfigured to worktree paths
4. Main daemon breaks because worktree lacks `config.yml`

**Error observed:**
```
FileNotFoundError: Config file not found: /Users/Morriz/Documents/Workspace/InstruktAI/TeleClaude/trees/cache-deferreds/config.yml
```

## Root Cause

1. `ensure_worktree()` only creates a bare git worktree - no environment preparation
2. `next-build.md` Step 1.b tells worker to "ensure dependencies are installed" without specifics
3. `bin/install.sh` and `bin/init.sh` have no guards against running from worktrees

## Required Outcomes

### 1. Worktree arrives ready

When worker AI lands in a worktree, the environment must already be prepared. No environment setup instructions should exist in worker commands.

### 2. Project-owned preparation hook

`ensure_worktree()` calls a project-specific preparation hook after git worktree creation:
- Python projects (Makefile): `make worktree:prepare SLUG={slug}`
- TypeScript projects (package.json): `npm run worktree:prepare -- {slug}`

Each project owns what "preparation" means for itself.

### 3. Remove environment instructions from worker commands

Delete Step 1.b "Prepare Environment" from `~/.agents/commands/next-build.md`. Worker commands must not contain environment setup instructions.

### 4. Guard install/init scripts

`bin/install.sh` and `bin/init.sh` must detect when running from a worktree and refuse with a clear error message.

## Files Involved

- `teleclaude/core/next_machine.py` - `ensure_worktree()` function
- `~/.agents/commands/next-build.md` - Step 1.b to remove
- `bin/install.sh` - needs worktree guard
- `bin/init.sh` - needs worktree guard
- `Makefile` - needs `worktree:prepare` target
- New preparation logic (location TBD by implementer)

## Acceptance Criteria

- [ ] Running `make install` from a worktree fails with clear error
- [ ] Running `make init` from a worktree fails with clear error
- [ ] `next_work()` creates a worktree that is immediately ready for work
- [ ] Worker AI in worktree can run `make test` without any setup steps
- [ ] `next-build.md` contains no environment setup instructions
