# ADR-001: Git Stash Prevention in Multi-Worktree Environment

**Status:** Accepted
**Date:** 2026-03-20
**Context:** Phantom git stash entries blocked the work state machine for months

## Problem

Git stash entries kept appearing in the shared repository stash, blocking the
work state machine's stash-debt precondition check. Multiple agents across
multiple worktrees were affected. The stash is repo-wide — an entry created
in one worktree blocks all worktrees.

## Investigation

Systematic elimination:
1. **Pre-commit** — uses `checkout -- .` + patch files, NOT `git stash`. Eliminated.
2. **Autostash (rebase/merge)** — disabled via `GIT_CONFIG` env vars in wrapper
   and `no_autostash_env()` in GitPython. Eliminated.
3. **Direct `git stash` calls** — wrapper blocks for non-integrator roles. Eliminated.
4. **Daemon GitPython** — only calls `stash("list")` (read-only). Eliminated.

A stash watchdog (polling `.git/refs/stash` with process tree capture) caught
the actual culprit: the **test suite**.

## Root Cause

`tests/unit/install/test_git_wrapper_permissions.py` ran `git stash` through
the wrapper to test permission enforcement. The `test_integrator_allowed` test
used `role="integrator"` which allows stash — and created a REAL stash entry
in the shared repo-wide stash. No `cwd` was set, so the stash landed in the
project repository.

When `run_build_gates` ran `make test` in a worktree, the test suite resolved
the wrapper from `Path(__file__).parents[3]` — which in a worktree pointed to
the worktree's stale copy of the wrapper (frozen at worktree creation time).
This old wrapper had different permission rules, compounding the problem.

## Decision

### Immediate fixes
- **Test isolation:** All stash tests use `tmp_path` temp repos via
  `_make_branch_repo()`. Stash entries stay in temp repos, cleaned by pytest.
- **mark-phase auto-commit:** Work phase state writes commit state.yaml
  atomically in the worktree with `--no-verify`. Idempotent writes (no change)
  skip the commit.
- **Worktree-preferring state IO:** `read_phase_state` and `write_phase_state`
  check if `trees/{slug}` exists and route there, preventing state drift
  between main and worktree.
- **Canonical project root resolution:** `mark-phase` resolves the project
  root via `git --git-common-dir` before looking for worktrees, preventing
  double-nesting when called from inside a worktree.

### Defense-in-depth
- **Autostash prevention in wrapper:** `GIT_CONFIG_COUNT` env vars inject
  `rebase.autoStash=false` and `merge.autoStash=false` for every git command.
- **Autostash prevention in GitPython:** `no_autostash_env()` helper and
  explicit `--no-autostash` flags on merge and pull-rebase calls.
- **Pre-merge dirty check:** `_merge_origin_main_into_worktree` commits
  pending changes before merging, with a warning log if the worktree was dirty.
- **Wrapper observability:** `TELECLAUDE_GIT_WRAPPER_LOG` logs every git
  command through the wrapper with role, subcommand, args, and cwd.
- **Stash watchdog:** Background poll of `.git/refs/stash` with process tree
  capture on change.

### Permission model
Three-tier git wrapper permissions:
- **DESTRUCTIVE** — blocked for all roles (restore, clean, switch, reset, revert)
- **PROTECTED** — integrator only (stash, push on main), integrator+system (commit on main)
- **RESTRICTED** — orchestrator cannot commit on any branch

## Consequences

- Stash entries no longer appear during normal operation
- Tests are isolated and don't pollute the shared repository
- State writes are atomic and consistent between main and worktrees
- The wrapper logs provide audit trail for git operations
- `PRE_COMMIT_NO_STASH` dead code removed (was never read by anything)

## Invariants

These must hold going forward:
1. **No test creates git state in the shared repo.** All tests that call git
   operations must use `tmp_path` fixtures.
2. **All state writes prefer worktrees.** `write_phase_state` routes to the
   worktree when it exists.
3. **mark-phase auto-commits.** Work phase state writes are committed atomically.
4. **Autostash is disabled everywhere.** Both wrapper and GitPython paths.
5. **The wrapper is resolved via symlink.** Worktree copies are stale and must
   not be invoked directly.
