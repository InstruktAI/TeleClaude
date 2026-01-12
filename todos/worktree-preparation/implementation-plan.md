# Implementation Plan: worktree-preparation

## Overview

When `ensure_worktree()` creates a git worktree, it must call a project-owned preparation hook to make the worktree ready for work. Guards must prevent `make install` and `make init` from running in worktrees.

---

## Group 1: Guards (Defensive)

Prevent catastrophic hijacking by refusing to run install/init from worktrees.

- [x] **Add worktree detection to install.sh**
  - Compare `git rev-parse --show-toplevel` with parent of `git rev-parse --git-common-dir`
  - If in worktree: print clear error message, exit 1
  - Must happen early in script before any modifications

- [x] **Add worktree detection to init.sh**
  - Same detection logic as install.sh
  - If in worktree: print clear error message, exit 1

---

## Group 2: TeleClaude Preparation Hook

What `make worktree:prepare SLUG=xxx` does for this project specifically.

- [ ] **Create worktree preparation logic**
  - Receives SLUG as argument
  - Operates on `trees/{slug}/` from main repo context
  - Steps:
    1. Run `uv sync --extra test` in `trees/{slug}/` to create isolated `.venv`
    2. Generate `trees/{slug}/config.yml` based on main config but with relative database path (`teleclaude.db`)
    3. Create symlink `trees/{slug}/.env` → `../../.env`

- [ ] **Add Makefile target**
  - `worktree:prepare` target that calls the preparation logic
  - Accepts SLUG parameter

---

## Group 3: ensure_worktree() Integration

Modify `teleclaude/core/next_machine.py` to call preparation hook after git worktree creation.

- [ ] **Add project type detection**
  - Check if `{cwd}/Makefile` exists
  - If yes: verify `worktree:prepare` target exists via `make -n worktree:prepare` (dry run)
  - If no Makefile: check `{cwd}/package.json`
  - If yes: parse JSON, verify `scripts["worktree:prepare"]` exists
  - If file exists but target missing: raise error

- [ ] **Add hook execution**
  - After successful git worktree creation (when `ensure_worktree()` returns True)
  - Call `make worktree:prepare SLUG={slug}` or `npm run worktree:prepare -- {slug}`
  - Run from `cwd` (main repo), hook knows to operate on `trees/{slug}/`

- [ ] **Add error handling**
  - If hook not found: fatal error with clear message
  - If hook execution fails: fatal error, don't dispatch worker into broken worktree
  - Propagate error up to `next_work()` which returns error message to orchestrator

---

## Group 4: Command Cleanup

Remove confusing environment instructions from worker commands.

- [ ] **Remove Step 1.b from next-build.md**
  - Delete "Prepare Environment" section (lines 28-32) from `~/.agents/commands/next-build.md`
  - Worker commands must not contain environment setup instructions

---

## Group 5: Testing

- [ ] **Test guards**
  - Verify `make install` from worktree fails with clear error
  - Verify `make init` from worktree fails with clear error

- [ ] **Test preparation hook**
  - Verify `make worktree:prepare SLUG=test-slug` creates functional worktree
  - Verify worktree has `.venv/`, `config.yml`, `.env` symlink
  - Verify `make test` runs successfully from prepared worktree

- [ ] **Test ensure_worktree() integration**
  - Verify hook is called after worktree creation
  - Verify error when hook missing
  - Verify error propagation when hook fails

---

## Notes

- Worktree database is isolated: `trees/{slug}/teleclaude.db` (relative path in generated config)
- `.env` is symlinked (shared secrets are fine)
- `todos/{slug}/` folder is already in worktree via git (orchestrator commits it to main before `next_work()`)
- Existing worktrees (when `ensure_worktree()` returns False) skip preparation - assumed already prepared
